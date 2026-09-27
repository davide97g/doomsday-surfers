# Asset contract (v2: realistic cast, prop kits, biomes)

Every 3D asset is built by a Blender script (`blender -b -P ...`), exported as
.glb, compressed, and committed under `public/assets/`. This file is the
contract between those scripts and the renderer (`src/render/*`). Change it
here first, then on both sides.

## Coordinates and units

- Metres. Blender is Z-up; glTF export converts to Y-up.
- **Forward (down the track, away from the camera) = Blender +Y** (glTF -Z,
  which is the game's forward: `z = -(s - d)`).
- Lateral = Blender X. Lane centres at x = -2.2, 0, +2.2 (lane width 2.2).
- Track surface (the lane screens) = Blender z = 0.
- The world is a ribbon in the air: the renderer bends everything onto the
  rollercoaster in the vertex shader (`src/render/bend.ts`). So:
  - Any mesh longer than 2 m along Y needs edge loops every <= 1 m (<= 0.5 m
    for the deck and tunnels), or it will not follow curves.
  - Scenery has no ground to stand on. Anything beside the track reaches down
    to z = -24 (like today's towers) so drops and climbs never show its base.
- Hitboxes live in `src/config/tuning.json` and do not change; visuals match
  them (numbers below).

## Pipeline

- Shared helpers: `assets/blender/lib/` (`mat.py`, `mesh.py`, `bake.py`,
  `export.py`, `preview.py`).
- Source textures (CC0, not committed): `assets/textures/<id>/`, fetched by
  `bun scripts/fetch-textures.ts`. Credits: `assets/CREDITS.md`.
- Export: glb with UVs (TEXCOORD_0), normals, no tangents (three.js derives
  them in the fragment shader, which also keeps normal maps right under the
  bend), `export_extras=True` for custom properties.
- Compress: `lib/export.py` runs gltf-transform: meshopt geometry, textures
  KTX2 (ETC1S colour/ORM, UASTC normals) when `tools/ktx/toktx` exists, else
  WebP. Max texture 1024 (characters, props), 2048 (kit atlases).
- The renderer's loader (`src/render/assets.ts`) has MeshoptDecoder and
  KTX2Loader; WebP needs nothing.
- Every asset script can write Eevee preview PNGs (front/side/back/3-4) for
  review: `-- --preview <dir>`.
- Materials: Principled BSDF only (exports to MeshStandardMaterial). Emission
  for screens/neon (use `KHR_materials_emissive_strength`). Alpha: CLIP
  (mask) for hair/foliage, BLEND only for glass.

## Characters: `public/assets/characters/<id>.glb`

Built by `assets/blender/human.py --character <id>` from MPFB2 (CC0 base mesh
and system assets).

- ids: goblin bro kid uncle influencer wellness doomer manager remote linkedin
- Root at the feet, facing forward (+Y Blender / -Z glTF), ~1.7 m tall
  adult (the kid is smaller; the renderer scales per character).
- One armature, MPFB `game_engine` rig (UE-style names: `pelvis`,
  `spine_01..03`, `neck_01`, `head`, `clavicle_l`, `upperarm_l`,
  `lowerarm_l`, `hand_l`, fingers, `thigh_l`, `calf_l`, `foot_l`, `ball_l`,
  and `_r`). Deform bones only.
- Materials by name (the renderer looks these up):
  - `Screen`, `ScreenAlt`, `ScreenNews`, `ScreenRing`: emissive phone/tablet/
    ring-light screens (the renderer dims `Screen*` into grey reality).
  - `Void`: the face, black glossy mirror (base #050507, metallic 1,
    roughness 0.06).
  - `Skin`, `Hair`, `Shoes` (the renderer tints `Shoes` emissive during Delulu
    Kicks), anything else free.
- Empty `PhoneLight` parented to the phone (the renderer puts the point light
  there); for two-phone characters, one is enough.
- Animation clips (30 fps, keys on every frame, root motion none: the root
  stays at the origin, the renderer moves it):

  | clip | frames | loop | note |
  |---|---|---|---|
  | `run` | 16 (one full stride) | yes | phone in hand(s), eyes (void) on it |
  | `idle` | 60 | yes | standing, thumb scrolling |
  | `jump` | 20 | no | take-off, tuck, reach down |
  | `fall` | 12 | yes | airborne, dropping (off a roof) |
  | `land` | 8 | no | knee absorb |
  | `roll` | 18 | no | knee slide under a barrier, phone held up |
  | `grind` | 24 | yes | surf stance on a rail, arms out, phone in one hand |
  | `fly` | 24 | yes | jetpack pose, leaning forward, legs trailing |
  | `stumble` | 12 | no | side bump |
  | `kicks` | 22 | no | front flip (Delulu Kicks jump) |
  | `present` | 36 | no | death: arms drop, head comes up |

- Budget: <= 35k triangles, <= 6 materials, textures <= 1024, glb <= 1.8 MB.

## Common prop kit: `public/assets/kits/common.glb`

One file, top-level mesh nodes named below. Origins noted per node. Where a
material name is given, the renderer replaces its texture at runtime with a
canvas (the in-game feed content), so give those faces clean 0..1 UVs.

- Reel train (the `post` obstacle, 2.0 wide, 2.8 tall, roof walkable):
  - `train_front` (origin at the front face, extends +Y 1 m),
    `train_mid` (a 2 m module from y 0 to 2, the renderer repeats it),
    `train_back` (1 m cap). Side screens use material `ReelScreen`
    (renderer supplies the reel canvas), the front screen `ReelFront`.
  - `train_stairs`: 7 m ramp/stairs rising from z 0 at y -7 to z 2.8 at y 0,
    placed in front of a train (origin at its top, back end).
  - `train_warn`: warning strobe bar for moving trains (material `Warn`).
- `barrier_low`: 1.9 wide, 0.9 tall, ~0.3 deep, origin at the centre of its
  depth on the ground. Face material `NotifFace` (512x128 UV aspect).
- `barrier_high`: two poles + banner. Banner bottom at 1.05, top at 3.2,
  width 2.0, origin centre of depth. Banner faces `AdFace` (2:1 UV aspect,
  both sides).
- Habits (<= 1.0 tall, <= 1.2 wide, <= 0.7 deep, origin at the ground,
  centre): `habit_water` (glass: material `Glass`), `habit_books`,
  `habit_shoe`, `habit_phone` (screen material `MumFace`, 1:2 aspect).
- `thumb`: giant thumb lying along the lane, 8 m long (+Y), 2.0 wide, 3.6
  tall, nail at the far end facing up, origin at its near end.
- Pads (origin at the near edge, extending +Y):
  - `pad_ramp`: 6 m long, rising to 1.4, 1.9 wide. Face `RampFace`.
  - `pad_bouncer`: radius 0.9 round trampoline, `pad_bouncer_top` and
    `pad_bouncer_spring` as separate nodes (the renderer squashes them).
  - `pad_autoplay`: 7 m x 1.8 travelator, belt material `AutoplayBelt`
    (renderer scrolls its UVs along V).
- Pickups (centred at origin, ~0.8 m): `pickup_like` (heart),
  `pickup_notif` (red badge "1"), `pickup_reel` (play tile), `pickup_outrage`
  (angry emoji).
- Power-ups (centred, ~1.0 m): `power_protector` (tempered glass pane,
  cracked corner), `power_magnet` (horseshoe magnet with a heart),
  `power_viral` (twin rocket cans with a view counter), `power_mainchar`
  (gold ring light with "x2"), `power_kicks` (chunky neon sneakers, cloud
  soles).
- `att_jetpack`: worn on the back (origin at the attach point, on the spine,
  +Y forward), used during Going Viral.
- Rails (grind): `rail_cable` (USB-C cable, 1 m module along +Y, top at
  z 1.1, radius ~0.1, on little stands every module), `rail_pipe` (steel
  pipe, same), `rail_end` (the sloped start: from z 0 at y -1.5 up to 1.1 at
  y 0).

## Biome kits: `public/assets/kits/<biome>.glb` + `<biome>-sky.jpg`

Biomes: `feed` (Feed City), `canyon` (Group Chat Canyon), `sewer` (Comment
Section Sewer), `bedroom` (3 AM Bedroom), `mall` (Infinite Mall).

- `deck`: one 4.4 m track row (y -2.2 .. 2.2, centred), ~9.6 wide, >= 9
  edge loops along Y. Top at z 0 with three screen openings 1.92 x 4.06 at
  x -2.2, 0, 2.2 (the renderer draws the screens at z 0.011) and bezels
  around them. Lane seams (between/outside lanes, at x -3.3, -1.1, 1.1,
  3.3) as a separate node `deck_seam` with material `Seam` (the renderer
  gives it the zone glow). Underside may hang down (<= 1.5 m).
- `side_*`: scenery pieces. Custom properties (exported as glTF extras) tell
  the renderer where to put them:
  - `slot`: `wall` (face 4.6-7 m from the centre line), `mid` (8-20 m),
    `far` (20-60 m).
  - `every`: mean spacing along the track in metres.
  - `chance`: 0..1 chance per slot.
  - `side`: `both`, `left`, `right` (left = -X). The renderer mirrors for
    the other side.
  - Model them for the RIGHT side (+X), facing the track (-X).
  Screens on scenery that should show the feed use material `ScreenFeed`
  (0..1 UVs per screen); the renderer gives each instance a random feed cell.
- `tunnel`: one 4.4 m module (y -2.2 .. 2.2), inner clearance >= 7.5 m tall
  and >= 11 m wide, edge loops every 0.5 m.
- `overhang`: spans all three lanes (~7.5 m wide), solid part between z 1.05
  and 3.2 (you roll under it), supports outside x +-3.6. Origin at the
  centre of its depth on the ground.
- Optional `rail_<biome>` if the biome's rails differ from the common ones.
- Budget per kit: <= 45k unique triangles total, wall pieces <= 4k, far
  pieces <= 8k; one atlas material (2048 albedo + normal + ORM, optional
  emissive) plus at most two extra materials (emissive signage, glass).
- Sky: `public/assets/kits/<biome>-sky.jpg`, 2048x1024 equirectangular,
  Cycles render of the biome's distant surroundings from the track; horizon
  at the middle row, below the horizon fades to the biome's fog colour. Used
  for the sky dome and, via PMREM, for reflections.

## Art direction (all kits)

- **Realistic materials, surreal world.** Real-world PBR (CC0 textures from
  `assets/textures/`, bevelled edges, worn edges, baked AO, believable
  scale detail: screws, seams, vents, stitching, grime) applied to the feed
  world's giant objects: phones as skyscrapers, chat bubbles as rock, cables
  as rails. Black Mirror cold, not cartoon. Look at real references online
  (product shots, architecture, Poly Haven models) before modelling.
- **Faceless**: no human faces anywhere (mannequins are smooth, blank).
- **Invented brands only** (see `src/config/content.json` `brands`); never
  real logos or app UI. Screens that should show the in-game feed use the
  runtime materials listed above, so don't paint UI into textures.
- **Readability first**: obstacles must read instantly at 60 m in a dark,
  foggy, bloomy scene. Scenery stays darker and less saturated than the
  track and obstacles; neon/emissive accents are fine but sparse.
- Everything goes grey when dopamine drops (a screen-space grade does it):
  no need to author grey variants.

## Performance budget (iPhone 14, WebGL, 60 fps)

The renderer draws everything within ~210 m, instanced, no culling. Aim:

- Whole visible scene <= 600k triangles and <= 180 draw calls. A biome's
  scenery as placed (sum over pieces of `200 m / every x sides x chance x
  triangles`) <= 220k triangles. Report this number.
- Deck row <= 1.5k tris; tunnel module <= 2k; rail module <= 150.
- Common kit: train front/back <= 3k each, train mid module <= 800,
  stairs <= 2.5k, barriers <= 2k, habits <= 2.5k, thumb <= 6k, pads <= 2k,
  pickups <= 300 each (many on screen), power-ups <= 2k, jetpack <= 3k.
- One atlas material per kit (2048: albedo + normal + ORM, optional
  emissive), plus the runtime-overridden materials, plus at most two extra
  (glass, emissive signage). Textures KTX2 (the lib's `compress`).
- Every glb <= 4 MB compressed; sky jpg <= 600 KB.

## Review loop

Every kit script renders previews (`lib/preview.py`) of each piece and a
"game" view (camera 3.5 m up, 6.4 m behind the runner position, looking
down the track, dark fog) into the session scratchpad. Look at them and
iterate until they are genuinely convincing before exporting.
