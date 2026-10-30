#!/bin/sh
# Runs inside the FreeBSD VM as root: clean BWNTEST build plus the
# firmware module, packed like bwntest-15.1.tar.
set -e
cd /usr/src
rm -rf /usr/obj/usr/src/amd64.amd64/sys/BWNTEST
make -j4 buildkernel KERNCONF=BWNTEST > /root/build-v2-clean.log 2>&1
rm -rf /root/dist2
mkdir -p /root/dist2
make installkernel KERNCONF=BWNTEST INSTKERNNAME=BWNTEST DESTDIR=/root/dist2 \
	-DNO_ROOT METALOG=/root/dist2/METALOG > /root/install-v2.log 2>&1
cd /root/bwnfw30
make clean > /dev/null
make SYSDIR=/usr/src/sys > /root/fw-v2.log 2>&1
cp bwn_v4_n30_ucode.ko /root/dist2/boot/BWNTEST/
kldxref /root/dist2/boot/BWNTEST
tar -xOf /root/bwntest-15.1.tar README > /root/dist2/README
cd /root/dist2
tar -cf /root/bwntest-15.1-v2.tar README boot
ls -la /root/bwntest-15.1-v2.tar
grep -c "warning:" /root/build-v2-clean.log || true
