#!/bin/sh
# Builds every doomscroller's .glb with Blender from MPFB2 humans
# (assets/blender/human.py; needs `bun run assets:setup` once: MPFB2 + the
# MakeHuman CC0 system assets, and the CC0 texture sets).
#   bun run assets                  all characters
#   bun run assets bro kid          just these
#   PREVIEW=/some/dir bun run assets goblin   also write review renders there (<dir>/<id>/)
# The old procedural builder (assets/blender/runner.py) is kept for reference.
set -e
cd "$(dirname "$0")/.."
BLENDER=${BLENDER:-blender}
command -v "$BLENDER" >/dev/null 2>&1 || BLENDER=/opt/homebrew/bin/blender
CHARACTERS=${*:-"goblin bro kid uncle influencer wellness doomer manager remote linkedin"}
LOG=$(mktemp -t human)
for c in $CHARACTERS; do
  set -- --character "$c"
  [ -n "$PREVIEW" ] && set -- "$@" --preview "$PREVIEW/$c"
  if ! "$BLENDER" -b --python-exit-code 1 -P assets/blender/human.py -- "$@" >"$LOG" 2>&1; then
    # The Metal kernel compile can crash when several Blenders bake at once: retry on the CPU.
    echo "human: $c failed, retrying with CPU bakes" >&2
    if ! "$BLENDER" -b --python-exit-code 1 -P assets/blender/human.py -- "$@" --cpu >"$LOG" 2>&1; then
      tail -30 "$LOG"
      echo "human: $c failed (full log: $LOG)" >&2
      exit 1
    fi
  fi
  grep "^human: $c:" "$LOG" | tail -1
done
rm -f "$LOG"
