# Doomsday Surfers — project notes for Claude

Pitch: "An endless runner where you die if you stop doomscrolling."
Davide owns the product decisions; Claude builds. Discuss design changes before implementing them.

## Locked design
- Three lanes, swipe controls (feel close to the genre), but original "feed world" look: the track is giant phone screens, reels/ads slide down lanes like trains, faceless runner lit by their phone. Never copy Subway Surfers assets, UI, characters, or branding.
- Dopamine drains constantly. Content pickups refill it with **tolerance** (each type gives less every time you take it). Healthy habits are obstacles that drain it and slow you down. At zero you slow into grey reality and lose.
- Colour and audio follow dopamine (neon → grey silence).
- Death copy: "You are present. … Disgusting." → [SCROLL AGAIN].
- Hidden ending: stay idle on the death screen for 60s and something happens (still to be designed).
- Crashing into a barrier/post drops dopamine to zero (one death screen). Tolerance never recovers within a run. Dopamine meter is a phone battery.
- Seven playable doomscrollers, picked on a title-screen turntable (swipe left/right): Hoodie Goblin (craves Reels), Grindset Bro (Notifications), iPad Kid (Likes), Outrage Uncle (Outrage), Influencer (Likes), Wellness Girlie (no craving; healthy habits cost half), News Doomer (Notifications). The favourite content gives +50% but builds tolerance faster; physics identical. All faceless, lit by their screen. Meshes: one Blender script (`runner.py --character <id>`), shared rig + clips, one .glb per character, loaded on demand.
- Checkpoint gates (every `gate.every` m): a giant foldable phone unfolds over the track; crossing it starts bullet time, its panels form a halo, the camera rides the rail 360° round the runner while a profiling log types out, then the feed moves to a new zone (colour + favoured content type + speed step). No dopamine change; drain paused and input dropped during the scan.
- Comedy layer: fake push notifications, banner ads, streak guilt, confirmshaming declines, a "keep going?" prompt that pauses the run ([YES] [yes]), one fake-ad revive per run (+40 dopamine, tolerance kept), and a screen-time report on death. No fake shop/currency yet.
- Monetization is pure parody: fake ads, invented brands only, no real money.
- Tone: Black Mirror cold, funny because it hurts. Complicit, not preachy.
- No runtime LLM. Content comes from a pre-written bank + templates.

## Architecture rules (keep a future Godot port cheap)
- `src/sim` must not import Three.js or touch the DOM. Fixed timestep (1/120).
- All tuning numbers go in `src/config/tuning.json`. Content banks go in JSON.
- Renderer reads sim state, never mutates it; effects come from `SimEvent`s.
- Game UI is HTML overlays in `src/ui`; interactive elements need `data-ui`.
- Run `npm run typecheck` and `npm run check:gen` after sim/generator changes.

## Target
iPhone 14 at 60 fps. Pixel ratio capped at 2, instancing, half-res bloom.
Art: procedural grey box, plus Blender-scripted .glb hero assets (`assets/blender/*.py`, `npm run assets`); commit the exported .glb.

## Roadmap
- Day 1: controls, track, obstacles, perf gate ✅ (iPhone 14 native build: 60 fps, swipes clean)
- Day 2: dopamine meter + drain, content pickups with tolerance, healthy-habit obstacles, grade/audio tied to dopamine, death-into-reality sequence ✅ (pending on-device feel check)
- Day 3: comedy layer (content bank, fake ads, manipulative UI, end-of-run report, sound) ✅ (pending on-device check)
- Day 4: first Blender hero assets, juice (haptics, particles), TestFlight — runner asset, haptics, particles, icon, TestFlight script done; waiting on App Store Connect app record + on-device check. TestFlight internal only until the public name is decided ("Doomsday Surfers" risks a copycat rejection).
