# mmiotraces

Traces of a BCM43228 (14e4:4359, N-PHY rev 16, radio 2057 rev 9) at 2.4 GHz,
recorded with `tools/trace-wl-b43.sh` / `tools/b43-lab trace`. Each run loads the
driver, associates, and pings; `MARK` lines show where it connected.

| Trace | Driver |
|---|---|
| `raw/wl.trace` | wl 6.30.223.271 (proprietary) |
| `raw/b43.trace` | b43 from v7.0, unmodified |
| `raw/b43cal.trace` | b43 without the fixes, TX IQ/LO cal enabled |
| `raw/rssi2.trace` | b43 with the RSSI fix (patch 3) and the v1 RC cal patch (waits for run 1 to finish) |
| `raw/papd8.trace` | b43 development build with patches 1, 2, 5 and experimental PAPD |
| `raw/rccal1.trace`, `raw/rccal2.trace` | b43 with patches 1-3, 5 and `udelay(35)` before the stop of RC cal run 1 |
| `raw/rccal3.trace`, `raw/rccal4.trace` | b43 with patches 1-5 (patch 4: wl's delays in the RC cal) |

The `.info` files hold the link state and ping results of each run (BSSID
removed). `raw/lspci.txt` is the card's `lspci -vv`.

## Decoding

    tools/decode.py -v log traces/raw/wl.trace

turns the raw MMIO accesses into PHY, radio, table and SHM operations, with
register names from the b43 headers (set `B43_SRC` to a b43 source tree). The
timestamps in the decoded output are the ones in the raw trace, so a group of
operations can be found in either by searching for its timestamp.

## Excerpts per patch

The decoded operations behind each statement in the
`[PATCH wireless-next 0/5] b43: N-PHY: fix calibrations on rev7+ (BCM43228)`
series:

| Patch | Excerpt | wl | b43 |
|---|---|---|---|
| 1/5 tone sample table | `excerpts/patch1-tone-table.txt` | 55.783690 | b43cal 1230.638260 |
| 2/5 IQLOCAL_CMD busy poll | `excerpts/patch2-iqlo-poll.txt` | 55.797869 | b43cal 1230.663334 |
| 2/5 TRSW override, second core | `excerpts/patch2-trsw.txt` | 55.796751 | b43cal 1230.659560, papd8 21991.266674 |
| 2/5 final coefficients | `excerpts/patch2-coefficients.txt` | 55.856526 | papd8 21991.292103 |
| 3/5 RSSI VCM | `excerpts/patch3-rssi-vcm.txt` | 55.765602 | b43 125.617830, rssi2 23522.333972 |
| 4/5 RC cal delays | `excerpts/patch4-rccal.txt` | 55.752070 | b43 125.584546, rccal1 204625.562749, rccal4 207810.792997 |
| 5/5 TX_PU override | `excerpts/patch5-tx-pu.txt` | 55.865414 | papd8 21991.295718 |
