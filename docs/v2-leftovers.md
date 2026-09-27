# v2 handoff: state and leftovers (2026-09-27)

Branch `feat/v2-realism` (not merged, not pushed). Spec: `docs/v2-gameplay.md`.
Asset contract, art direction and budgets: `docs/assets-v2.md`. Plan the work
followed: `~/.claude/plans/i-need-you-to-woolly-shore.md`.

## Done

- **Sim**: five power-ups (Screen Protector, For You Magnet, Going Viral
  jetpack, Main Character x2, Delulu Kicks) with their own tolerance; reel
  roofs with stairs, grind rails, tunnels, overhangs; five biomes with chunk
  mixes; ghost links v2. `bun run check:gen` covers all of it (traps, roof
  gaps, overhangs, rails, tunnels, power-ups, per-tick soak, a roof-riding
  bot). All green.
- **Render**: shared glTF loader (meshopt + KTX2), kit loading, instanced part
  sets, BiomeView (per-biome feed on the lane screens, kit decks/scenery/
  tunnels/rails/overhangs, panorama skies + PMREM reflections, light/fog/
  exposure crossfading through the gate), glass lane screens (High tier),
  the phone as a point light, power-up VFX and HUD chips, quality tiers
  (Auto steps down), perf logging, on-screen debug console.
- **Assets** (all committed, all from our Blender scripts on CC0 sources):
  realistic MPFB2 cast of 10 with a void face and 11 clips
  (`assets/blender/human.py`); common prop kit; Feed City, Group Chat
  Canyon, Comment Section Sewer, 3 AM Bedroom and Infinite Mall kits with
  panoramas (`assets/blender/kits/*.py`).
- **Audio/haptics/UI copy** for every new event, both modes.
- **Install**: `bun run ios:device` (iPhone over Wi-Fi/cable), `--sim`
  (iPhone 17 simulator), `--perf` (bot plays forever, frame stats streamed),
  `--debug` (errors on screen). Last build is installed on the iPhone 14 and
  the simulator.

## Measured on the iPhone 14 (perf build, High tier, pixel ratio 2)

| zone | fps (5 s avg) | p95 frame | draw calls | triangles |
|---|---|---|---|---|
| Feed City | 58.8–60 (53.8 while loading) | 17–20 ms | 45–99 | 114–235k |
| Group Chat Canyon | 60 | 17 ms | 31–84 | 51–114k |

The Wi-Fi console dropped after ~2 min (phone auto-lock), so **Sewer,
Bedroom and Mall are not measured on device yet**.

## Leftovers, in priority order

1. **Measure the last three biomes on device.** Set Auto-Lock to Never (or use
   the cable), then `bun run ios:device --perf`: it logs a `perf fps=... zone=`
   line every 5 s. The bot reaches the Mall (zone 4) after ~4000 m (~3 min).
   Anything under 58 fps: lower that kit's scenery `chance`/`every` extras,
   or check the Mall's alpha-MASK atlas (it disables early-z on Apple GPUs;
   leaves as geometry would fix it).
2. **Finish the review pass of Canyon, Bedroom and Sewer** (their agents hit
   the API limit before their last review):
   - Their proposed look values never arrived. Tune `look` / `sky` / `light` /
     `seam` in `src/config/content.json` `zones[1..3]` against screenshots
     (`?zone=1..3&bot=1`).
   - Bedroom: the books had a UV overlap in the atlas; re-check
     `side_books`. Sewer: the "final full bake" may not have run after its
     last sky change; re-run `blender -b -P assets/blender/kits/sewer.py`
     and compare.
   - Previews lived in the session scratchpad (gone). Re-render with
     `-- --preview <dir>`.
3. **Review all 10 characters** (`blender -b -P assets/blender/human.py --
   --character <id> --preview <dir>`). The agent stopped while reworking the
   cast configs, but the exported glbs are from its completed passes.
   - Known: the Hoodie Goblin reads slightly feminine in the chest; check the
     macros.
   - Re-measure `CHARACTER_LOOKS` scales in `src/render/renderer.ts` (the kid
     should be ~0.72).
   - Check that `PhoneLight` is exported. The goblin's scene root is `rig`,
     and the light falls back to a fixed spot if the node is missing.
4. **Look tuning** (screenshot, adjust, repeat):
   - Feed City ring-light lamps glare too much through the bloom; lower their
     emissive or the bloom threshold.
   - Realistic runners go dark in dark biomes; add a rim/fill light that only
     lights the hero, or raise the phone light.
   - 3D pickups are drawn at 0.72 scale; check readability at speed.
   - The Mall panorama is bright; it may want a darker `exposure`.
5. **Simulator only:** the iOS Simulator's WebKit GPU process can segfault
   (`com.apple.WebKit.GPU quit unexpectedly`, parent `launchd_sim`) under this
   scene. That's the simulator's WebGL-on-Metal layer; the real iPhone 14
   ran the same build at 60 fps. On the simulator, pick Medium or Low in the
   device-test panel (tap the fps pill).
6. **Plan items not done:**
   - A real hero shadow map. The blob shadow was kept, because the lane
     screens are unlit emissive and can't show a shadow.
   - The jetpack should hang on the `spine_03` bone, not the player group.
   - A "this link is from an older feed" toast for v1 ghost links (they're
     ignored silently).
   - Office biome kits for Work mode. Work mode keeps Feed City geometry with
     office screens; its five zone names are in `content.work.json`.
   - The checkpoint gate is still procedural (it could become a foldable-phone
     kit piece).
7. **Feel check on the phone:**
   - Roofs and mantles, rails, tunnels (head bonk), overhang rolls.
   - Power-up frequency (`tuning.power`: every 300–450 m) and durations.
   - The biome sound beds.
   - Delulu Kicks' flip clip vs normal jumps.
   - The main test bot never climbs roofs (the roof-rider in check:gen does).
8. **Housekeeping:**
   - Merge `feat/v2-realism` into `main` when happy.
   - Delete `assets/blender/runner.py` once the new cast is approved.
   - Update the README asset section (still describes runner.py).
   - The untracked `Claude outputs/` folder was left alone.
   - The Daily and all seeds changed with the new generator (fine before
     launch).

## Gotchas for the next session

- Port 5173 may be taken by another project's Vite. Run ours with
  `bunx vite --port 5199 --strictPort`.
- Blender 5.2 is headless-only here. `bun run assets:setup` re-installs
  MPFB2, the CC0 textures (into gitignored `assets/textures/`) and the KTX
  tools (`tools/ktx/`).
- Kit nodes lose their transforms at load (`Kit.clone()` resets them): bake
  transforms into meshes and set origins per the contract.
- Runtime material names in kits: `ScreenFeed` (live feed per instance),
  `AdFace`, `NotifFace`, `ReelScreen`, `ReelFront`, `MumFace`, `RampFace`,
  `AutoplayBelt`, `Warn`, `Glass`, `Seam`. `gltf-transform dedup` merges
  materials that differ only by name, so keep their colours different.
- A kit that loads mid-run retires on-screen stand-ins through `kitGen`. Keep
  that pattern for any new pooled kit piece (a missing pool used to crash
  every frame).
