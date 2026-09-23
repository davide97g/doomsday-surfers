# Doomsday Surfers

An endless runner where you die if you stop doomscrolling.

Three.js + TypeScript + Vite, wrapped for iOS with Capacitor. Grey-box / day 1 build.

## Run it

```bash
npm install
npm run dev          # http://localhost:5173 (also exposed on your LAN)
```

Controls: swipe (or arrow keys / WASD). Left/right to switch lanes, up to jump, down to roll (in the air it fast-drops, then rolls).

URL flags:
- `?bot=1` turns on autopilot (soak test / attract mode)
- `?seed=123` gives a deterministic track

Tap the **fps pill** at the top to open the device-test panel: bloom, colour grade, pixel ratio, and a dopamine slider (a preview of the day-2 neon→grey grade). It also shows CPU ms per frame, draw calls and triangle count.

## Test on the iPhone

**Quick (Safari, same Wi-Fi):** run `npm run dev`, then open `http://<your-mac-ip>:5173` on the iPhone. Safari performance is close to the app's web view.

**Native app (Capacitor):**

`ios/` is already set up: signing team DA596D32QB, iPhone only, portrait only, status bar hidden.

```bash
npm run ios:run        # build, sync, pick a device, install and launch
npm run ios:sync       # build + copy web assets into the iOS project
npm run ios:open       # opens Xcode, if you prefer pressing Run there
```

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
  config/tuning.json   all gameplay numbers (speeds, jump, spawn gaps...)
  sim/                 pure simulation, no Three.js (portable to Godot)
    world.ts           fixed-timestep sim: movement, collisions, pickups
    generator.ts       chunk-based procedural track (future: "the Algorithm")
    rng.ts             seeded PRNG
  input/input.ts       swipe + keyboard to actions
  render/              Three.js view (reads sim state, never writes it)
    renderer.ts        feed-world grey box, obstacle pools, player, camera
    post.ts            half-res bloom + colour grade (dopamine uniform)
    textures.ts        canvas placeholder art (feed posts, fake ads, notifications)
  ui/hud.ts            HTML overlay UI
  dev/bot.ts           autopilot
scripts/check-generator.ts
```
