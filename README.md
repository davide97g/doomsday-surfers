# Doomsday Surfers

An endless runner where you die if you stop doomscrolling.

Three.js + TypeScript + Vite, wrapped for iOS with Capacitor. Procedural grey-box world, first Blender hero asset (the runner).

## Run it

```bash
npm install
npm run dev          # http://localhost:5173 (also exposed on your LAN)
```

Controls: swipe (or arrow keys / WASD). Left/right to switch lanes, up to jump, down to roll (in the air it fast-drops, then rolls).

URL flags:
- `?bot=1` turns on autopilot (soak test / attract mode)
- `?seed=123` gives a deterministic track

Tap the **fps pill** at the top to open the device-test panel: bloom, colour grade, pixel ratio, and a "no drain" switch. It also shows CPU ms per frame, draw calls and triangle count.

## Test on the iPhone

**Quick (Safari, same Wi-Fi):** run `npm run dev`, then open `http://<your-mac-ip>:5173` on the iPhone. Safari performance is close to the app's web view.

**Native app (Capacitor):**

`ios/` is already set up: signing team DA596D32QB, iPhone only, portrait only, status bar hidden.

```bash
npm run ios:run        # build, sync, pick a device, install and launch
npm run ios:sync       # build + copy web assets into the iOS project
npm run ios:open       # opens Xcode, if you prefer pressing Run there
```

Haptics only fire in the native app (not in Safari). Web Audio may follow the silent switch.

### TestFlight (internal testing)

One-time: create the app in App Store Connect (bundle id `com.davideghiotto.doomsdaysurfers`) and sign in to your Apple ID under Xcode > Settings > Accounts. Then:

```bash
npm run ios:testflight -- --dry   # Release archive only, nothing uploaded
npm run ios:testflight            # archive + upload (build number = timestamp)
```

The build shows in TestFlight after Apple's processing. Uploads are internal-only (`ios/App/ExportOptions.plist`), so there is no App Review; the public name is still undecided.

## Assets

The runner is built by a Blender script, and the exported `.glb` is committed so the game builds without Blender:

```bash
npm run assets       # needs Blender (brew install --cask blender --appdir=~/Applications)
```

`assets/blender/runner.py` builds the mesh, rig and clips (`run`, `idle`, `jump`, `roll`, `present`) into `public/assets/runner.glb`. Pass a folder as a second argument to also render preview PNGs. The app icon source is `assets/icon/icon.svg`.

### Day-1 perf gate

On the iPhone 14 with bloom + grade on at pixel ratio 2, the target is a steady **60 fps** with headroom (CPU ms well under 16). If it can't hold that, the plan is to move to Godot before any art gets built.

## Checks

```bash
npm run typecheck
npm run check:gen    # generator fairness + autopilot soak over 40 seeds
```

## Layout

```
src/
  config/tuning.json   all gameplay and UI timing numbers
  config/content.json  all copy: feed, brands, notifications, popups, report
  content/templates.ts {handle}/{thing} template filler for the content bank
  sim/                 pure simulation, no Three.js (portable to Godot)
    world.ts           fixed-timestep sim: movement, collisions, pickups
    generator.ts       chunk-based procedural track (future: "the Algorithm")
    rng.ts             seeded PRNG
  input/input.ts       swipe + keyboard to actions
  render/              Three.js view (reads sim state, never writes it)
    renderer.ts        feed world, obstacle pools, player, camera
    hero.ts            Blender runner: clip selection and crossfades
    particles.ts       pickup/habit/crash bursts, speed lines
    post.ts            half-res bloom + colour grade (dopamine uniform)
    textures.ts        canvas art (feed atlas, fake ads, notifications, habits)
  audio/audio.ts       procedural Web Audio music + sfx
  fx/haptics.ts        Capacitor haptics
  ui/                  HTML overlays: hud, title (streak), nags (notifications,
                       banners), keepGoing, death (revive ad, report)
  dev/bot.ts           autopilot
assets/blender/        Blender build scripts for hero assets
scripts/               check-generator.ts, testflight.sh
```
