#!/usr/bin/env bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
#
# Turn the WebM recordings from scratchpad/clips.js into what the platforms take:
#   <name>.mp4   H.264, 1280 wide, for X / Bluesky / LinkedIn / Mastodon video
#   <name>.gif   960 wide, 12 fps, palette-optimised, for Reddit / GitHub / Mastodon
# A speed factor per clip keeps the boring stretches short (SPEED[name]=4 means 4x).
#
#   bash scratchpad/clips-encode.sh [clips-dir]
set -eu
DIR=${1:-launch/assets/clips}
declare -A SPEED=( [boot]=2 [workbenches]=3 [project-42mb]=1 )
for f in "$DIR"/*.webm; do
  n=$(basename "$f" .webm); s=${SPEED[$n]:-1}
  pts="setpts=PTS/$s"
  ffmpeg -v error -y -i "$f" -vf "$pts,scale=1280:-2,fps=30,format=yuv420p" \
    -c:v libx264 -preset slow -crf 22 -movflags +faststart -an "$DIR/$n.mp4"
  ffmpeg -v error -y -i "$f" -vf "$pts,fps=12,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle" \
    -loop 0 "$DIR/$n.gif"
  d=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$DIR/$n.mp4")
  printf '%-14s %4.0fs  mp4 %5d KB  gif %6d KB\n' "$n" "$d" $(( $(stat -c %s "$DIR/$n.mp4") / 1024 )) $(( $(stat -c %s "$DIR/$n.gif") / 1024 ))
done
