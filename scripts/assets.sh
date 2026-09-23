#!/bin/sh
# Builds every doomscroller's .glb with Blender (see assets/blender/runner.py).
#   npm run assets            all characters
#   npm run assets -- bro     just one
set -e
cd "$(dirname "$0")/.."
CHARACTERS=${*:-"goblin bro kid uncle influencer wellness doomer"}
for c in $CHARACTERS; do
  blender -b -P assets/blender/runner.py -- "public/assets/characters/$c.glb" --character "$c" | grep '^runner:'
done
