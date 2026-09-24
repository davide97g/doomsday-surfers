#!/bin/sh
# Builds every doomscroller's .glb with Blender (see assets/blender/runner.py).
#   bun run assets            all characters
#   bun run assets bro        just one
set -e
cd "$(dirname "$0")/.."
CHARACTERS=${*:-"goblin bro kid uncle influencer wellness doomer manager remote linkedin"}
for c in $CHARACTERS; do
  blender -b -P assets/blender/runner.py -- "public/assets/characters/$c.glb" --character "$c" | grep '^runner:'
done
