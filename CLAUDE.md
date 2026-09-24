# Doomsday Surfers — project notes for Claude

Pitch: "An endless runner where you die if you stop doomscrolling."
Davide owns the product decisions; Claude builds. Discuss design changes before implementing them.

## Locked design
- Three lanes, swipe controls (feel close to the genre), but original "feed world" look: the track is giant phone screens, reels/ads slide down lanes like trains, faceless runner lit by their phone. Never copy Subway Surfers assets, UI, characters, or branding.
- Dopamine never drains on its own. Only healthy habits (obstacles) drain it and slow you down. Content pickups refill it with **tolerance** (each type gives less every time you take it). At zero you slow into grey reality and lose.
- "The more distracted the better": push notifications are big and pile up, but only at the top or bottom edge (they never cover the track), and bump dopamine just by landing. Tapping/clicking one opens it: big dopamine hit (own tolerance) + super boost (faster, smash through every obstacle for `notify.boostTime` s). A swipe that starts on a card flings it and still steers. About half are reel shares ("A friend sent you a reel. Watch it now"): opening one plays a 5 s clip in a phone panel in a top corner (within the top 35% of the screen; new cards use the bottom slot meanwhile), and it deliberately outlasts the 3 s boost (you keep watching after immunity ends). Clips are free-licence Mixkit stock (`public/assets/reels/`, sources in its CREDITS.md), never YouTube or other copyrighted footage; handles/captions are invented.
- Colour and audio follow dopamine (neon → grey silence).
- Death copy: "You are present. … Disgusting." → [SCROLL AGAIN].
- Hidden ending: stay idle on the death screen for 60s and something happens (still to be designed).
- The track is a rollercoaster laid out from the seed (`src/sim/course.ts`): banked curves (auto-follow, swipes stay lane changes), rollers, climbs, "infinite scroll" drops, airtime hills, loops and corkscrews. Gates always sit on flat straights. Downhill builds a speed rush; crests make jumps float and steep ones lift you off by themselves. Loops, corkscrews, drops and big air (landing after `thrill.airMin` s) give a thrill: dopamine with one shared thrill tolerance. Thrill rides are obstacle-free (pickups ride through). Optional pads: "Swipe up" ramps and pull-to-refresh bouncers launch you through an arc of content, autoplay strips give a short speed burst. No gaps or falling deaths.
- Crashing into a barrier/post drops dopamine to zero (one death screen). Tolerance never recovers within a run. Dopamine meter is a phone battery.
- Seven playable doomscrollers, picked on a title-screen turntable (swipe left/right): Hoodie Goblin (craves Reels), Grindset Bro (Notifications), iPad Kid (Likes), Outrage Uncle (Outrage), Influencer (Likes), Wellness Girlie (no craving; healthy habits cost half), News Doomer (Notifications). The favourite content gives +50% but builds tolerance faster; physics identical. All faceless, lit by their screen. Meshes: one Blender script (`runner.py --character <id>`), shared rig + clips, one .glb per character, loaded on demand.
- Work mode (corporate parody, `docs/work-mode.md`): the Focus pill on the title switches Personal / Work (it restarts the app). Same sim; `content.work.json` reskins everything: office app cards (invented suite "Synergy 365": Huddle, Sync, Inbox, Calendar, Tickets, Humbl), incoming calls that ring and open a faceless meeting grid, a presence pill (Available / Away / Be right back / Offline) instead of the battery, and an office-suite world. Own cast: Middle Manager, Remote Worker, LinkedIn Lunatic. Real app names, logos, fonts and colours (Slack, Teams, Outlook, Meet, Jira, LinkedIn) show only when `realBrands` is on: dev builds or `?brands=real`, for local fun. Production builds fall back to the parody suite, so TestFlight never ships third-party branding. Sounds: free-licence community sound-alikes (Freesound, Pixabay) (`public/assets/sfx/`, credits in its CREDITS.md) plus synth fallbacks. Never recordings ripped from the real apps.
- Checkpoint gates (every `gate.every` m): a giant foldable phone unfolds over the track; crossing it starts bullet time, its panels form a halo, the camera rides the rail 360° round the runner while a profiling log types out, then the feed moves to a new zone (colour + favoured content type + speed step). No dopamine change; input dropped during the scan.
- Comedy layer: fake push notifications, banner ads, streak guilt, confirmshaming declines, a "keep going?" prompt that pauses the run ([YES] [yes]), one fake-ad revive per run (+40 dopamine, tolerance kept), and a "Proof of Doom" receipt on death (prints out of a slot, shares as a 9:16 image; `src/ui/receipt.ts`). No fake shop/currency yet.
- Monetization is pure parody: fake ads, invented brands only, no real money.
- Tone: Black Mirror cold, funny because it hurts. Complicit, not preachy.
- No runtime LLM. Content comes from a pre-written bank + templates.

## Architecture rules (keep a future Godot port cheap)
- `src/sim` must not import Three.js or touch the DOM. Fixed timestep (1/120).
- All tuning numbers go in `src/config/tuning.json`. Content banks go in JSON.
- Renderer reads sim state, never mutates it; effects come from `SimEvent`s.
- The renderer lays everything out on a straight track (z = -(s - d)); `src/render/bend.ts` bends it onto the course in the vertex shader. Subdivide long meshes along z. Objects added to the scene after the constructor need `bend.patchTree`.
- Game UI is HTML overlays in `src/ui`; interactive elements need `data-ui`.
- Package manager is Bun (`bun install`, `bun run <script>`, `bunx`); never npm/npx.
- Run `bun run typecheck` and `bun run check:gen` after sim/generator changes.

## Target
iPhone 14 at 60 fps. Pixel ratio capped at 2, instancing, half-res bloom.
Art: procedural grey box, plus Blender-scripted .glb hero assets (`assets/blender/*.py`, `bun run assets`); commit the exported .glb.

## Roadmap
- Day 1: controls, track, obstacles, perf gate ✅ (iPhone 14 native build: 60 fps, swipes clean)
- Day 2: dopamine meter + drain, content pickups with tolerance, healthy-habit obstacles, grade/audio tied to dopamine, death-into-reality sequence ✅ (pending on-device feel check)
- Day 3: comedy layer (content bank, fake ads, manipulative UI, end-of-run report, sound) ✅ (pending on-device check)
- Day 4: first Blender hero assets, juice (haptics, particles), TestFlight — runner asset, haptics, particles, icon, TestFlight script done; waiting on App Store Connect app record + on-device check. TestFlight internal only until the public name is decided ("Doomsday Surfers" risks a copycat rejection).
- Next: viral features, one per session, in the order in `docs/viral-plan.md`. Follow its pre-build ritual: re-check current trends, then ask Davide every doubt with concrete meme/slang references before coding.
