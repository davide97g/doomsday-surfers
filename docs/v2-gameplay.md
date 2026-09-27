# v2: power-ups, a second level, five biomes, a realistic cast

Decided with Davide on 2026-09-27. The goal was for the game to feel like the
big endless runners (power-ups, distinct map zones, more ways to move) while
keeping the feed world. Top priority: realistic 3D models, built by our own
Blender scripts from free/open (CC0) sources. The asset contract is in
`docs/assets-v2.md`.

## Power-ups

Power-ups sit at the end of a short pickup line, one every 300–450 m (the
first at 250 m; `tuning.power`). Each lasts a little less every time you take
that kind again (its own tolerance: x0.85 per take, floor 0.6, never
recovers). Taking one that is already on tops it up to the longer of the two.
They give no dopamine by themselves.

| id | name (Work mode) | what it does | tuning |
|---|---|---|---|
| `protector` | Screen Protector (Do Not Disturb) | the next crash smashes through instead (glass shatters), then 1 s of grace | 25 s |
| `magnet` | For You Magnet (Synergy Magnet) | every pickup within 14 m ahead, any lane or height, flies into you | 10 s |
| `viral` | Going Viral (Thought Leadership) | a jetpack flight, 7 m up over a seeded sky line of content; no collisions; the landing stretch is cleared | 160 m |
| `mainchar` | Main Character Energy x2 (Employee of the Month x2) | engagement score x2 | 15 s |
| `kicks` | Delulu Kicks (Stretch Goals) | jumps x1.35 higher: enough to land on the reel roofs | 10 s |

"Hype Sneakers" was the first pick for the super jump; renamed to Delulu Kicks
because it sat too close to a well-known runner's "Super Sneakers".

Copy lives in `content.json` / `content.work.json` under `powers`
(pickup toast title + lines, the protector's break line, an end line).

## The second level

- **Reel roofs.** Every reel train has a walkable roof (2.8 m). Roof runs are
  a train with 7 m stairs up to its roof and one or two more trains to hop
  along. Walk off an end and you fall to the track (never a death); a runner
  who came off a roof and falls short of the next one catches its edge (the
  mantle). Followers stay in their lane or step toward the middle, and one
  lane is never used, so a runner on the ground always has a way out.
- **Grind rails.** A giant charger cable along one lane at 1.1 m, with a
  sloped start. Run into it or land on it and you grind (x1.15 speed,
  sparks); come in from the side and you hop up. It is the fast lane: nothing
  under it.
- **Tunnels.** Covered stretches with a 7.5 m ceiling (you bump your head).
  More trains and overhangs inside, no bouncers, thumbs or jetpacks.
- **Overhangs.** Something across all three lanes between 1.05 and 3.2 m:
  roll under it.

Surfaces are resolved in the sim after the runner moves (`World.settle`), so
the renderer only reads `player.on` (ground, stairs, roof, rail) and
`player.floor`.

## Biomes

Zones are now five biomes (`zone % 5`), each leaning on its own chunk mix
(`tuning.biomes.weights`) and favouring a content type:

| # | biome | favours | leans on |
|---|---|---|---|
| 0 | Feed City | none | balanced |
| 1 | Group Chat Canyon | notifications | rails, bouncers |
| 2 | Comment Section Sewer | outrage | tunnels, overhangs |
| 3 | 3 AM Bedroom | reels | roofs, rails |
| 4 | Infinite Mall | likes | autoplay travelators, roofs |

The lanes are always phone screens; each biome shows its own feed on them
(group chat, comment sections, 3 AM reels, product listings), its own deck,
scenery, tunnel and rail skins, sky panorama, light and ambience. Work mode
keeps its office look (only the zone names change).

## Checks

`bun run check:gen` adds: no traps, roof gaps short enough to mantle,
overhangs clear, rail lanes clean, tunnels away from gates/thrill rides,
power-up spacing and clear jetpack flights, per-tick soak checks (never
flying through a gate, no crash while flying, heads under ceilings), and a
roof-riding bot run that must never die up there.

## Dev flags

`?zone=N` starts just past gate N (another biome), `?power=<id>` hands out a
power-up at the start, `?bot=climb` rides every roof, `?perf` (or a
`VITE_PERF=1` build) plays forever and logs frame stats.

## Compatibility

The generator change rerolls every seed (the Daily too), and ghost links went
to v2 (old ones are ignored). Acceptable before launch.
