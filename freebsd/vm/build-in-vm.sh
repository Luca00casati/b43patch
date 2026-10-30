#!/bin/sh
# Runs inside the FreeBSD VM as root: fetch 15.1 sources, apply the bwn
# patch, and build a kernel with the GPL N-PHY code and debug output.
set -e
if [ ! -f /usr/src/Makefile ]; then
	fetch -o /tmp/src.txz https://download.freebsd.org/releases/amd64/15.1-RELEASE/src.txz
	tar -C / -xf /tmp/src.txz
	rm /tmp/src.txz
fi
cd /usr/src
if ! patch -R -s -f -p1 --check < /root/bwn-bcm43228.patch >/dev/null 2>&1; then
	patch -s -p1 < /root/bwn-bcm43228.patch
fi
cat > sys/amd64/conf/BWNTEST <<'CONF'
include GENERIC
ident BWNTEST
options BWN_GPL_PHY
options BWN_DEBUG
CONF
make -j"$(sysctl -n hw.ncpu)" buildkernel KERNCONF=BWNTEST 2>&1 | tail -20
