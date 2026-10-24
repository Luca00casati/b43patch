# b43patch

Backup of b43 (Linux) work for the Broadcom BCM43228 (14e4:4359; d11 core
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
