#!/bin/sh
# Download/upload test while sampling the station's RX/TX rates. No root needed.
dev=${1:-$(iw dev | awk '/Interface/ {print $2; exit}')}
log=$(mktemp)
( while :; do iw dev "$dev" station dump | grep -E 'rx bitrate|tx bitrate' | tr -s '\t ' ' ' >> "$log"; sleep 0.5; done ) &
s=$!
down=$(curl -s -o /dev/null -m 60 -w '%{speed_download}' 'https://speed.cloudflare.com/__down?bytes=50000000')
up=$(head -c 10000000 /dev/zero | curl -s -o /dev/null -m 60 -w '%{speed_upload}' --data-binary @- 'https://speed.cloudflare.com/__up')
kill $s
LC_ALL=C awk -v d="$down" -v u="$up" 'BEGIN { printf "down %.1f Mbit/s, up %.1f Mbit/s\n", d*8/1e6, u*8/1e6 }'
echo "rx rates seen:"; grep 'rx bitrate' "$log" | sed 's/ *rx bitrate: //' | sort | uniq -c | sort -rn | head -8
echo "tx rates chosen:"; grep 'tx bitrate' "$log" | sed 's/ *tx bitrate: //' | sort | uniq -c | sort -rn | head -5
iw dev "$dev" station dump | grep -E 'tx retries|tx failed|rx drop|signal:|beacon signal'
rm -f "$log"
