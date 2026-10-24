#!/bin/sh
# Record every MMIO access (plus PCI config writes, for bcma core-window
# switches) that wl and then b43 make while bringing up the BCM43228 and
# connecting to the 2.4 GHz router. Run with sudo straight after a reboot
# (wl must be working). Reboot again afterwards to get wl back.
#
# mmiotrace needs a single online CPU; CPUs 1..N are offlined during each
# trace and brought back afterwards. Everything is slow while tracing.
DIR=/home/luca/dev/mmiotrace
B43KO=/home/luca/dev/b43-combined.ko
SSID="YOUR_SSID"
BSSID=00:00:00:00:00:00
T=/sys/kernel/tracing
WAIT=60

lsmod | grep -q '^b43 ' && { echo "b43 is loaded: reboot first so wl starts clean"; exit 1; }
lsmod | grep -q '^wl ' || { echo "wl is not loaded: reboot first"; exit 1; }
[ -d "$T/events" ] || mount -t tracefs nodev "$T" || exit 1

cpus_offline() {
	for c in /sys/devices/system/cpu/cpu[1-9]*; do
		[ -f "$c/online" ] && echo "$1" > "$c/online"
	done
}

trace_start() {
	cpus_offline 0
	echo nop > $T/current_tracer
	echo > $T/trace
	echo 262144 > $T/buffer_size_kb
	echo 'p:cfgw pci_bus_write_config_dword devfn=%si:u32 where=%dx:s32 val=%cx:x32' >> $T/kprobe_events
	echo 1 > $T/events/kprobes/cfgw/enable
	echo mmiotrace > $T/current_tracer
	cat $T/trace_pipe > "$DIR/$1.trace" &
	READER=$!
	sleep 1
}

mark() { echo "$1" > $T/trace_marker; echo "-- $1"; }

trace_stop() {
	echo 0 > $T/events/kprobes/cfgw/enable
	sleep 2
	# The tracer can't be changed while trace_pipe is open (EBUSY), so the
	# reader has to go first. Never bring CPUs back with mmiotrace still
	# armed: kmmio is not SMP-safe and oopses on the next MMIO race.
	kill $READER 2>/dev/null
	wait $READER 2>/dev/null
	echo nop > $T/current_tracer
	if [ "$(cat $T/current_tracer)" != nop ]; then
		echo "mmiotrace still active, leaving CPUs 1..N offline"
		return 1
	fi
	echo '-:cfgw' >> $T/kprobe_events
	cpus_offline 1
}

wait_connected() {
	sleep $WAIT
	dev=$(iw dev | awk '/Interface/ {print $2; exit}')
	[ -n "$dev" ] || { echo "no interface"; return; }
	if ! iw dev "$dev" link | grep -qi "$BSSID"; then
		nmcli device wifi connect "$SSID" ifname "$dev" >/dev/null 2>&1
		sleep 20
	fi
	iw dev "$dev" link | grep -E "Connected|signal" | tee -a "$DIR/$2.info"
	mark "connected"
	ping -c 20 -i 0.2 -W 1 1.1.1.1 | tail -2 | tee -a "$DIR/$2.info"
	mark "traffic done"
}

lspci -nn -vv -d 14e4:4359 > "$DIR/lspci.txt" 2>&1

echo "===== wl"
rmmod wl
sleep 2
trace_start wl
mark "loading wl"
modprobe wl
wait_connected wl wl
trace_stop

echo "===== b43"
rmmod wl
sleep 2
trace_start b43
mark "loading b43"
modprobe -a cfg80211 mac80211 cordic
modprobe bcma
modprobe ssb
insmod "$B43KO"
wait_connected b43 b43
trace_stop

for f in wl b43; do
	echo "$f: $(wc -l < "$DIR/$f.trace") lines, $(grep -c '^W ' "$DIR/$f.trace") writes, lost: $(grep -c LOST "$DIR/$f.trace")"
done
chown -R luca:luca "$DIR"
echo "traces in $DIR (reboot to get wl back)"
