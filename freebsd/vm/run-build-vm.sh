#!/bin/sh
# FreeBSD 15.1 build VM for the bwn BCM43228 patch (no passthrough).
# SSH: ssh -p 2222 root@localhost
cd "$(dirname "$0")"
exec qemu-system-x86_64 -enable-kvm -cpu host -m 6G -smp 4 \
  -drive file=bwn-build.qcow2,if=virtio \
  -drive file=seed.iso,media=cdrom \
  -nic user,model=virtio-net-pci,hostfwd=tcp:127.0.0.1:2222-:22 \
  -display none -serial file:serial.log -daemonize -pidfile vm.pid
