# Example kit (and the lib smoke test): three small pieces with CC0 and flat
# materials, a canvas screen kept out of the atlas, baked into one 512 atlas,
# exported, compressed, previewed. Copy it to start a kit script.
#
#   blender -b -P assets/blender/kits/_example.py -- [--out path.glb] [--preview dir] [--size 512]
#
# Default output: tools/cache/example/example.glb (gitignored).

import os
import sys

sys.dont_write_bytecode = True  # no __pycache__ in the repo
_d = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _d if os.path.isdir(os.path.join(_d, "lib")) else os.path.dirname(_d))

import lib  # noqa: E402
from lib import bake, export, log, mat, mesh, preview  # noqa: E402

OUT = lib.arg("out", os.path.join(lib.TOOLS, "cache", "example", "example.glb"))
PREVIEW = lib.arg("preview")
SIZE = lib.arg("size", 512, int)
TEX_DIR = os.path.join(os.path.dirname(os.path.abspath(OUT)), "textures")

lib.reset_scene()

# ---------------------------------------------------------------- materials
cardboard = mat.pbr("Cardboard", "Cardboard004", mapping="BOX", box_scale=0.6)
marble = mat.pbr("Marble", "Marble012", mapping="BOX", box_scale=1.2, roughness_scale=0.6)
brass = mat.pbr("Brass", "Metal034", tiling=2.0)
rubber = mat.pbr("Rubber", "Rubber004", mapping="BOX", box_scale=0.5)
glow = mat.flat("Glow", "#ff2d6f", rough=0.4, emission="#ff2d6f", strength=4.0)
screen = mat.emissive_screen("ScreenFeed", (0.55, 0.8, 1.0), 5.0)  # the renderer fills it with a feed cell

# ---------------------------------------------------------------- pieces
# 1. A crate: bevel + weighted normals on a box, origin on the ground.
crate = mesh.box("crate", (0.9, 0.9, 0.6), location=(-1.6, 0, 0.3))
mesh.bevel(crate, 0.02, segments=3)
mesh.weighted_normals(crate)
mesh.apply_modifiers(crate)
mat.assign(crate, cardboard)
mesh.set_origin(crate, z="min")

# 2. A 4 m slab along +Y (needs bend loops), marble top, brass trim, a screen
#    face with clean 0..1 UVs that stays out of the atlas.
slab = mesh.box("slab", (1.2, 4.0, 0.25), location=(0, 0, 0.125), bevel=0.01, segments=2)
mat.assign(slab, marble)
trim = mesh.box("slab_trim", (1.26, 4.06, 0.06), location=(0, 0, 0.03))
mat.assign(trim, brass)
panel = mesh.box("slab_panel", (1.0, 0.04, 0.6), location=(0, -2.02, 0.55))
mat.assign(panel, rubber)
mat.assign(panel, screen, faces=lambda p: p.normal.y < -0.9)
mesh.uv_box(panel, 0.5)
mesh.uv_fit_faces(panel, material="ScreenFeed")
slab = mesh.join([slab, trim, panel], name="slab")
mesh.apply_transform(slab)
mesh.subdivide_along(slab, "Y", 0.5)
mesh.weighted_normals(slab)
mesh.apply_modifiers(slab)
mesh.set_origin(slab, y="min", z="min")
slab["slot"] = "wall"  # custom properties export as glTF extras
slab["every"] = 12.0

# 3. A glowing post (emission gets baked into the emissive atlas).
post = mesh.cylinder("post", 0.12, 1.6, verts=24, location=(1.6, 0, 0.8))
mat.assign(post, rubber)
cap = mesh.cylinder("post_cap", 0.16, 0.2, verts=24, location=(1.6, 0, 1.7))
mat.assign(cap, glow)
post = mesh.join([post, cap], name="post")
mesh.smooth(post, 40)
mesh.set_origin(post, z="min")

pieces = [crate, slab, post]
log("tris", {o.name: mesh.tri_count(o) for o in pieces}, "max Y segment of slab", round(mesh.max_segment(slab), 3))

if PREVIEW:  # the procedural source, to compare with the baked result
    preview.render_previews(PREVIEW, pieces, views=("three_quarter", "back"), size=(768, 576), prefix="src_")

# ---------------------------------------------------------------- bake + export
res = bake.bake_kit_atlas(pieces, SIZE, TEX_DIR, name="ExampleKit", keep_materials=("ScreenFeed",), ao_samples=64)
log("atlas", res["paths"], "emissive strength", round(res["emissive_strength"], 2))
for o in pieces:
    log(o.name, "materials", [m.name for m in o.data.materials], "uv", [l.name for l in o.data.uv_layers])

path = export.export_glb(OUT, pieces)
export.compress(path, max_texture=SIZE, inspect=True)

if PREVIEW:
    preview.render_previews(PREVIEW, pieces, views=("three_quarter", "back", "side", "front"), size=(768, 576),
                            prefix="baked_")
    preview.render_each(PREVIEW, pieces, views=("three_quarter",), size=(512, 512), sheet=False)
