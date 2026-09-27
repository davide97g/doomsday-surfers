# Asset credits

Source material the Blender scripts (`assets/blender/`) build the game's 3D
assets from. Everything here is CC0 (public domain dedication): no
attribution is required, we list it anyway so every asset stays traceable.
Source files are not committed; `bun run assets:setup` downloads them
(`scripts/setup-assets.sh`, `scripts/fetch-textures.ts`,
`assets/texture-manifest.json`). What ships is only what the scripts bake
and export into `public/assets/`.

Other credits: reel clips in `public/assets/reels/CREDITS.md`, sounds in
`public/assets/sfx/CREDITS.md`.

## Textures (`assets/textures/<id>/`)

| id | used as | source | res | page | licence |
|---|---|---|---|---|---|
| `knitted_fleece` | knit fabric | Poly Haven | 2k | https://polyhaven.com/a/knitted_fleece | CC0 1.0 |
| `jogging_melange` | fleece | Poly Haven | 2k | https://polyhaven.com/a/jogging_melange | CC0 1.0 |
| `denim_fabric` | denim | Poly Haven | 2k | https://polyhaven.com/a/denim_fabric | CC0 1.0 |
| `cotton_jersey` | cotton / jersey | Poly Haven | 2k | https://polyhaven.com/a/cotton_jersey | CC0 1.0 |
| `stretch_poplin` | cotton / jersey | Poly Haven | 2k | https://polyhaven.com/a/stretch_poplin | CC0 1.0 |
| `velour_velvet` | velvet | Poly Haven | 2k | https://polyhaven.com/a/velour_velvet | CC0 1.0 |
| `rough_linen` | bed sheet / linen | Poly Haven | 2k | https://polyhaven.com/a/rough_linen | CC0 1.0 |
| `Leather037` | leather | ambientCG | 1K | https://ambientcg.com/a/Leather037 | CC0 1.0 |
| `Leather026` | leather | ambientCG | 1K | https://ambientcg.com/a/Leather026 | CC0 1.0 |
| `Rubber004` | rubber | ambientCG | 1K | https://ambientcg.com/a/Rubber004 | CC0 1.0 |
| `Metal009` | brushed metal | ambientCG | 1K | https://ambientcg.com/a/Metal009 | CC0 1.0 |
| `Metal027` | painted metal | ambientCG | 1K | https://ambientcg.com/a/Metal027 | CC0 1.0 |
| `PaintedMetal006` | painted metal | ambientCG | 1K | https://ambientcg.com/a/PaintedMetal006 | CC0 1.0 |
| `Fingerprints002` | smudged glass | ambientCG | 1K | https://ambientcg.com/a/Fingerprints002 | CC0 1.0 |
| `SurfaceImperfections003` | smudged glass | ambientCG | 1K | https://ambientcg.com/a/SurfaceImperfections003 | CC0 1.0 |
| `sandstone_cracks` | sandstone | Poly Haven | 2k | https://polyhaven.com/a/sandstone_cracks | CC0 1.0 |
| `Rock051` | rock / cliff | ambientCG | 2K | https://ambientcg.com/a/Rock051 | CC0 1.0 |
| `Concrete044D` | wet concrete | ambientCG | 2K | https://ambientcg.com/a/Concrete044D | CC0 1.0 |
| `Asphalt025C` | wet concrete | ambientCG | 1K | https://ambientcg.com/a/Asphalt025C | CC0 1.0 |
| `Bricks097` | brick | ambientCG | 1K | https://ambientcg.com/a/Bricks097 | CC0 1.0 |
| `MetalWalkway013` | metal grate | ambientCG | 1K | https://ambientcg.com/a/MetalWalkway013 | CC0 1.0 |
| `Marble012` | marble | ambientCG | 2K | https://ambientcg.com/a/Marble012 | CC0 1.0 |
| `Marble021` | marble | ambientCG | 2K | https://ambientcg.com/a/Marble021 | CC0 1.0 |
| `Metal034` | brass | ambientCG | 1K | https://ambientcg.com/a/Metal034 | CC0 1.0 |
| `Carpet016` | carpet | ambientCG | 1K | https://ambientcg.com/a/Carpet016 | CC0 1.0 |
| `WoodFloor051` | wood floor | ambientCG | 1K | https://ambientcg.com/a/WoodFloor051 | CC0 1.0 |
| `Cardboard004` | cardboard | ambientCG | 1K | https://ambientcg.com/a/Cardboard004 | CC0 1.0 |
| `Plastic010` | plastic | ambientCG | 1K | https://ambientcg.com/a/Plastic010 | CC0 1.0 |
| `Asphalt031` | asphalt | ambientCG | 1K | https://ambientcg.com/a/Asphalt031 | CC0 1.0 |
| `Tiles107` | tiles | ambientCG | 1K | https://ambientcg.com/a/Tiles107 | CC0 1.0 |

- ambientCG (https://ambientcg.com), CC0 1.0: https://docs.ambientcg.com/license/
- Poly Haven (https://polyhaven.com), CC0 1.0: https://polyhaven.com/license

## Human bodies, skins, hair, clothes

- **MPFB 2** (MakeHuman plugin for Blender), installed from
  https://extensions.blender.org/add-ons/mpfb/ . MPFB's own code is GPL;
  models made with it (its base mesh, targets and rigs) are CC0.
- **MakeHuman system assets** (`makehuman_system_assets_cc0.zip`: skins, eyes,
  hair, eyebrows, eyelashes, teeth, proxy meshes, casual/sport/work/elegant
  suits, shoes, fedoras), CC0 1.0:
  https://static.makehumancommunity.org/assets/assetpacks/makehuman_system_assets.html
  (download: https://files2.makehumancommunity.org/asset_packs/makehuman_system_assets/makehuman_system_assets_cc0.zip)

## Tools (not shipped)

- KTX-Software (Khronos, Apache-2.0) for KTX2 texture compression:
  https://github.com/KhronosGroup/KTX-Software
- glTF Transform (MIT): https://gltf-transform.dev
- Basis Universal transcoder from three.js (`public/libs/basis/`, Apache-2.0).
