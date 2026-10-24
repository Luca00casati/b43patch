#!/usr/bin/env python3
"""Decode mmiotrace logs of the BCM43228 (wl or b43) into PHY/radio/table/SHM ops.

  decode.py [opts] log   TRACE         decoded event stream
  decode.py [opts] state TRACE         last written (else read) value of
                                       every register and table entry
  decode.py [opts] diff  WL B43        state differences between two traces

Options go before the command:
  --from MARK / --to MARK   only use events between trace_marker lines
                            (e.g. --to connected)
  -m PATTERN                only show entries whose name or address matches
                            (regex, case-insensitive), e.g. -m 'EPS|PAPD|0x17d'
  -k KINDS                  comma list of phy,radio,tab,shm,mac,bar (default
                            all but mac,bar for state/diff)
  -v                        log: don't collapse table/ucode runs

The bcma core-window switches (PCI config 0x80) are not in the traces, so
BAR0 0x0000-0x0fff is assumed to be the d11 core. That holds after the
early EROM scan; the few R4 accesses before it show up as harmless "mac"
reads. BAR0 0x1000 is the d11 wrapper, 0x2000 the PCIe core and 0x3000
chipcommon.

wl and b43 use different paths for the same thing: wl writes PHY
registers as one 32-bit store to 0x3fc (data << 16 | reg) and reaches the
radio through 0x3d8/0x3da; b43 uses 16-bit 0x3fc/0x3fe and 0x3f6/0x3fa,
with 0x200 or'ed into the radio address on reads. Both end up as the same
PHY/RAD events here.
"""
import argparse
import os
import re
import sys

B43 = os.environ.get("B43_SRC",
                     "/home/luca/dev/linux-7.0/drivers/net/wireless/broadcom/b43")
BAR0_DEFAULT = 0xd0500000

SHM_ROUTE = {0: "ucode", 1: "shared", 2: "scratch", 3: "hw", 4: "rcmta"}
SHM_AUTOINC_W = 0x100
SHM_AUTOINC_R = 0x200

PHY_TABLE_ADDR, PHY_TABLE_LO, PHY_TABLE_HI = 0x72, 0x73, 0x74


def load_names():
    """Register names from the b43 headers (first define wins)."""
    phy, radio, mac, tabs = {}, {}, {}, {}

    def scan(fname, rx, store, prefix):
        try:
            text = open(os.path.join(B43, fname)).read()
        except OSError:
            return
        for name, val in re.findall(rx, text, re.M):
            store.setdefault(int(val, 0), name[len(prefix):])

    scan("phy_n.h", r"^#define\s+(B43_NPHY_\w+)\s+B43_PHY_N\((0x[0-9A-Fa-f]+)\)",
         phy, "B43_NPHY_")
    scan("radio_2057.h", r"^#define\s+(R2057_\w+)\s+(0x[0-9A-Fa-f]+)\b", radio, "R2057_")
    scan("b43.h", r"^#define\s+(B43_MMIO_\w+)\s+(0x[0-9A-Fa-f]+)\b", mac, "B43_MMIO_")
    try:
        text = open(os.path.join(B43, "tables_nphy.h")).read()
        for name, tid, off in re.findall(
                r"^#define\s+B43_NTAB_(\w+)\s+B43_NTAB(?:8|16|32)\(\s*(\w+),\s*(\w+)\)",
                text, re.M):
            tabs.setdefault(int(tid, 0), []).append((int(off, 0), name))
    except OSError:
        pass
    for v in tabs.values():
        v.sort()
    return phy, radio, mac, tabs


PHY_NAMES, RADIO_NAMES, MAC_NAMES, TAB_NAMES = load_names()


def tab_name(tid, off):
    best = None
    for o, n in TAB_NAMES.get(tid, []):
        if o <= off:
            best = (o, n)
    if not best:
        return ""
    return best[1] if best[0] == off else "%s+0x%x" % (best[1], off - best[0])


class Ev:
    __slots__ = ("t", "kind", "op", "addr", "val", "name", "count")

    def __init__(self, t, kind, op, addr, val, name="", count=1):
        self.t, self.kind, self.op, self.addr = t, kind, op, addr
        self.val, self.name, self.count = val, name, count

    def akey(self):
        """Printable address, also used as state key."""
        if self.kind == "tab":
            return "%02x:%03x" % self.addr
        if self.kind == "shm":
            return "%s:%04x" % self.addr
        return "%03x" % self.addr


class Decoder:
    """Turns raw MMIO accesses into decoded events."""

    def __init__(self):
        self.phy_addr = None
        self.radio_addr = None
        self.tab_id = self.tab_off = None
        self.tab_hi = None          # pending DATAHI write
        self.tab_rd = None          # pending table read waiting for DATAHI
        self.shm_ctl = None
        self.out = []

    def emit(self, *a, **kw):
        self.out.append(Ev(*a, **kw))

    def flush_tab_read(self):
        if self.tab_rd:
            self.out.append(self.tab_rd)
            self.tab_rd = None

    # --- PHY and tables
    def phy(self, t, op, reg, val):
        if not (reg == PHY_TABLE_HI and op == "R"):
            self.flush_tab_read()
        self.emit(t, "phy", op, reg, val, PHY_NAMES.get(reg, ""))
        if reg == PHY_TABLE_ADDR and op == "W":
            self.tab_id, self.tab_off, self.tab_hi = val >> 10, val & 0x3ff, None
        elif self.tab_id is None:
            return
        elif reg == PHY_TABLE_HI:
            if op == "W":
                self.tab_hi = val
            elif self.tab_rd:
                self.tab_rd.val |= val << 16
                self.flush_tab_read()
        elif reg == PHY_TABLE_LO:
            v = val if self.tab_hi is None else (self.tab_hi << 16) | val
            ev = Ev(t, "tab", op, (self.tab_id, self.tab_off), v,
                    tab_name(self.tab_id, self.tab_off))
            self.tab_hi = None
            self.tab_off += 1
            if op == "R":
                self.tab_rd = ev
            else:
                self.out.append(ev)

    # --- one raw access, offset relative to BAR0
    def access(self, t, op, width, off, val):
        if off == 0x3fc and width == 4:             # wl: data << 16 | reg
            if op == "W":
                self.phy_addr = val & 0xffff
                self.phy(t, "W", self.phy_addr, val >> 16)
            return
        if off == 0x3fc:
            if op == "W":
                self.phy_addr = val
            return
        if off == 0x3fe:
            if self.phy_addr is not None:
                self.phy(t, op, self.phy_addr, val)
            return
        if off in (0x3d8, 0x3f6):
            if op == "W":
                self.radio_addr = val & ~0x200      # b43 read flag
            return
        if off in (0x3da, 0x3fa):
            if self.radio_addr is not None:
                self.emit(t, "radio", op, self.radio_addr, val,
                          RADIO_NAMES.get(self.radio_addr, ""))
            return
        if off == 0x160 and width == 4:
            if op == "W":
                self.shm_ctl = val
            return
        if off in (0x164, 0x166) and self.shm_ctl is not None:
            self.shm(t, op, width, off, val)
            return
        if off < 0x1000:
            self.emit(t, "mac", op, off, val, MAC_NAMES.get(off, ""))
        else:
            region = ("wrap", "pcie", "cc")[min(off >> 12, 3) - 1]
            self.emit(t, "bar", op, off, val, "%s+0x%03x" % (region, off & 0xfff))

    def shm(self, t, op, width, off, val):
        route = (self.shm_ctl >> 16) & 0xff
        flags = self.shm_ctl >> 16
        word = self.shm_ctl & 0xffff
        rname = SHM_ROUTE.get(route, "r%d" % route)
        if route == 1:      # shared memory is byte addressed in b43 terms
            a = word * 4 + (2 if off == 0x166 else 0)
        else:
            a = word
        self.emit(t, "shm", op, (rname, a), val, "", )
        self.out[-1].count = width
        inc = SHM_AUTOINC_W if op == "W" else SHM_AUTOINC_R
        if flags & inc:
            self.shm_ctl = (self.shm_ctl & ~0xffff) | ((word + 1) & 0xffff)


def parse(path, bar0=BAR0_DEFAULT, start=None, stop=None):
    """Return (events, marks) for one trace file."""
    d = Decoder()
    marks = []
    active = start is None
    with open(path, errors="replace") as f:
        for line in f:
            p = line.split()
            if not p:
                continue
            if p[0] == "MARK":
                text = " ".join(p[2:])
                marks.append((float(p[1]), text))
                if start is not None and text == start:
                    active = True
                if stop is not None and text == stop:
                    break
                if active:
                    d.flush_tab_read()
                    d.emit(float(p[1]), "mark", "", 0, 0, text)
                continue
            if p[0] not in ("R", "W") or len(p) < 6:
                continue
            addr = int(p[4], 16)
            if not (bar0 <= addr < bar0 + 0x4000):
                continue
            if not active:
                # keep decoder address state current, drop the events
                n = len(d.out)
                d.access(float(p[2]), p[0], int(p[1]), addr - bar0, int(p[5], 16))
                del d.out[n:]
                d.tab_rd = None
                continue
            d.access(float(p[2]), p[0], int(p[1]), addr - bar0, int(p[5], 16))
    d.flush_tab_read()
    return d.out, marks


def matcher(pattern):
    if not pattern:
        return lambda ev: True
    rx = re.compile(pattern, re.I)
    return lambda ev: bool(rx.search(ev.name) or rx.search("0x" + ev.akey())
                           or rx.search(ev.akey()))


def fmt_val(ev):
    if ev.kind == "tab" or (ev.kind in ("mac", "bar") and ev.val > 0xffff):
        return "0x%08x" % ev.val
    if ev.kind == "shm" and ev.count == 4:
        return "0x%08x" % ev.val
    return "0x%04x" % ev.val


def cmd_log(a):
    evs, _ = parse(a.trace, a.bar0, a.start, a.stop)
    kinds = set(a.kinds.split(",")) if a.kinds else None
    want = matcher(a.match)
    run = []        # collapsed run of table writes / ucode upload

    def flush():
        if not run:
            return
        e0 = run[0]
        if len(run) == 1:
            show(e0)
        else:
            vals = " ".join(fmt_val(e)[2:] for e in run[:6])
            print("%12.6f %-5s %s %-9s %-28s %d entries: %s%s" % (
                e0.t, e0.kind.upper(), e0.op, e0.akey(), e0.name, len(run),
                vals, " ..." if len(run) > 6 else ""))
        run.clear()

    def show(ev):
        if ev.kind == "mark":
            print("%12.6f ===== %s" % (ev.t, ev.name))
            return
        print("%12.6f %-5s %s %-9s %-28s %s" % (
            ev.t, ev.kind.upper(), ev.op, ev.akey(), ev.name, fmt_val(ev)))

    for ev in evs:
        if ev.kind != "mark":
            if kinds and ev.kind not in kinds:
                continue
            if not want(ev):
                continue
            # table accesses drive PHY 0x72-0x74; hide those unless asked for
            if ev.kind == "phy" and ev.addr in (PHY_TABLE_ADDR, PHY_TABLE_LO,
                                               PHY_TABLE_HI) and not a.match:
                if not kinds or "tab" in kinds:
                    continue
        collapsible = (not a.verbose and ev.op == "W" and
                       ev.kind in ("tab", "shm"))
        if collapsible and run:
            p = run[-1]
            if p.kind == ev.kind and p.op == "W":
                if ev.kind == "tab" and ev.addr == (p.addr[0], p.addr[1] + 1):
                    run.append(ev)
                    continue
                if (ev.kind == "shm" and ev.addr[0] == p.addr[0] == "ucode"):
                    run.append(ev)
                    continue
        flush()
        if collapsible:
            run.append(ev)
        else:
            show(ev)
    flush()


STATE_KINDS = "phy,radio,tab,shm"


def build_state(a, path):
    """{(kind, key): (val, op, name)}: last value seen, write or read."""
    evs, _ = parse(path, a.bar0, a.start, a.stop)
    kinds = set((a.kinds or STATE_KINDS).split(","))
    want = matcher(a.match)
    st = {}
    for ev in evs:
        if ev.kind not in kinds or not want(ev):
            continue
        if ev.kind == "shm" and ev.addr[0] == "ucode":
            continue
        if ev.kind == "phy" and ev.addr in (PHY_TABLE_LO, PHY_TABLE_HI):
            continue
        k = (ev.kind, ev.akey())
        # what the driver wrote is the config; reads only fill in registers
        # it never wrote (table reads are often LO-only, so they would
        # clobber 32-bit entries anyway)
        if ev.op == "R" and st.get(k, (0, ""))[1] == "W":
            continue
        st[k] = (ev.val, ev.op, ev.name, fmt_val(ev))
    return st


KIND_ORDER = {"phy": 0, "radio": 1, "tab": 2, "shm": 3, "mac": 4, "bar": 5}


def sort_key(k):
    return (KIND_ORDER.get(k[0], 9), k[1])


def cmd_state(a):
    st = build_state(a, a.trace)
    for k in sorted(st, key=sort_key):
        val, op, name, s = st[k]
        print("%-5s %-9s %-30s %s %s" % (k[0].upper(), k[1], name, s,
                                         "" if op == "W" else "(read)"))


def cmd_diff(a):
    sa, sb = build_state(a, a.a), build_state(a, a.b)
    la, lb = os.path.basename(a.a).split(".")[0], os.path.basename(a.b).split(".")[0]
    print("%-5s %-9s %-30s %-12s %-12s" % ("", "addr", "name", la, lb))
    ndiff = 0
    tabs = {}       # table id -> number of differing entries
    for k in sorted(set(sa) | set(sb), key=sort_key):
        va, vb = sa.get(k), sb.get(k)
        if va and vb and va[0] == vb[0]:
            continue
        # registers neither driver wrote (status, counters) aren't config
        if not a.reads and not any(v and v[1] == "W" for v in (va, vb)):
            continue
        ndiff += 1
        if k[0] == "tab" and not a.verbose:
            tid = k[1].split(":")[0]
            tabs.setdefault(tid, []).append((k, va, vb))
            continue
        show_diff(k, va, vb)
    for tid, rows in sorted(tabs.items()):
        name = tab_name(int(tid, 16), int(rows[0][0][1].split(":")[1], 16))
        print("TAB   %-9s %-30s %d entries differ, first:" % (tid, name, len(rows)))
        for k, va, vb in rows[:4]:
            show_diff(k, va, vb, indent="  ")
    print("-- %d differences" % ndiff, file=sys.stderr)


def show_diff(k, va, vb, indent=""):
    def cell(v):
        if not v:
            return "-"
        return v[3] + ("" if v[1] == "W" else "r")
    name = (va or vb)[2]
    print("%s%-5s %-9s %-30s %-12s %-12s" % (indent, k[0].upper(), k[1], name,
                                             cell(va), cell(vb)))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bar0", type=lambda s: int(s, 0), default=BAR0_DEFAULT)
    ap.add_argument("--from", dest="start")
    ap.add_argument("--to", dest="stop")
    ap.add_argument("-m", dest="match")
    ap.add_argument("-k", dest="kinds")
    ap.add_argument("-v", dest="verbose", action="store_true")
    ap.add_argument("--reads", action="store_true",
                    help="diff: include registers that were only read")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("log").add_argument("trace")
    sub.add_parser("state").add_argument("trace")
    p = sub.add_parser("diff")
    p.add_argument("a")
    p.add_argument("b")
    a = ap.parse_args()
    try:
        {"log": cmd_log, "state": cmd_state, "diff": cmd_diff}[a.cmd](a)
    except BrokenPipeError:
        pass


if __name__ == "__main__":
    main()
