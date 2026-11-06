# b43patch

Backup of b43 (Linux) and bwn (FreeBSD) work for the Broadcom BCM43228 (14e4:4359; d11 core
rev 30, N-PHY rev 16, radio 2057 rev 9), developed against wl 6.30.223.271
mmiotraces.

## patches/

`git format-patch` series on top of Linux v7.0 (`028ef9c96`), from branch
`b43-combined`. Recreate with:

    git checkout -b b43-combined v7.0
    git am patches/*.patch

Build out of tree in `drivers/net/wireless/broadcom/b43`:

    make -C /usr/src/linux-headers-$(uname -r) M=$PWD CONFIG_B43=m modules

## tools/

- `b43-lab`: root test helper (install to /usr/local/sbin, sudoers rule in
  `b43-lab.sudoers`). Set SSID/BSSID for your router first.
- `decode.py`: mmiotrace decoder (log / state / diff) for the b43/wl traces.
- `trace-wl-b43.sh`: original trace script.
- `wifi-bench.sh`: benchmark used by `b43-lab bench`.

## traces/

mmiotraces of wl and b43 on the BCM43228, with the decoded operations behind
each patch of the upstream series. See `traces/README.md`.

## freebsd/

FreeBSD bwn(4) port. `freebsd/patches/` is a `git format-patch` series from
branch `bwn-bcm43228`: the BCM43227/BCM43228 attach change, then the same
five N-PHY calibration fixes as the Linux upstream series, ported to
`sys/gnu/dev/bwn/phy_n/if_bwn_phy_n_core.c`. It is based on FreeBSD main
(`91bff7d`) and also applies to 15.1-RELEASE sources. Recreate with:

    git checkout -b bwn-bcm43228 91bff7d
    git am freebsd/patches/*.patch

Needs a kernel with `options BWN_GPL_PHY` (and `BWN_DEBUG` for the debug
output). Not yet tested on hardware.

`freebsd/vm/` has the scripts for the FreeBSD 15.1 build VM:
`run-build-vm.sh` starts it, `build-in-vm.sh` builds the BWNTEST kernel, and
`pack-v2.sh` does a clean build and packs the boot tarball. `README.bwntest`
has the install steps. The firmware module (ucode30_mimo and initvals,
extracted with b43-fwcutter) and the kernel tarball are not included: the
firmware is not redistributable.
