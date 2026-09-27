# Infinite Mall (biome 4): bright, clean, soulless consumerism. Pinks, whites, brass, polished marble,
# invented brands only (src/config/content.json "brands"). Contract: docs/assets-v2.md "Biome kits".
#
#   blender -b -P assets/blender/kits/mall.py -- [--preview <dir>] [--only deck,side_store] [--no-bake] [--src]
#          [--no-sky] [--sky-only] [--game-only] [--size 2048]
#
# Writes public/assets/kits/mall.glb and public/assets/kits/mall-sky.jpg. Shared kit helpers (shape
# builders, detail decals, atlas bake, game view, sky camera, text sheets) live in feed.py.
#
# Materials: one atlas (MallKit, alpha MASK for the fig leaves and cart wire) + runtime Seam,
# ScreenFeed, AdFace + two extras: Glass (balustrades, shopfronts, the arcade roof) and Signage (the
# brand wordmarks and SALE lightboxes, a text sheet rendered here from system fonts).

import json
import math
import os
import random
import sys

sys.dont_write_bytecode = True  # no __pycache__ in the repo
_d = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _d if os.path.isdir(os.path.join(_d, "lib")) else os.path.dirname(_d))

import bpy  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402

import lib  # noqa: E402
from lib import log, mat, mesh  # noqa: E402
from kits.feed import (MB, PIECE_VIEWS, SCENERY_VIEWS, TAU, G, Kit, R, T, away_parts, bake_kit, basis,  # noqa: E402
                       cache_nodes, decorate, emission_material, export_kit, finish, fit_screens, game_view, glow,
                       join, lathe, load_nodes, loops, metal, phone, preview_piece, pano_camera, rbox, render_sky,
                       rrect_pts, smudged, split_faces, sweep, text_sheet, tube, uv_to_cell, weight, world_nodes, xf,
                       KITS_OUT)

FOG = "#d9c6d0"   # blush haze: the mall's air (reported for content.json zones[4].sky)
LOOK = dict(fog=FOG, near=50.0, far=165.0, hemi=1.2, hemi_sky="#ffe3f1", hemi_ground="#8a6f7e", sun="#fff4f8",
            sunI=1.8, exposure=1.0, env=0.9)
MALL_YS = [-2.2, -2.09, -1.67, -1.25, -0.83, -0.42, 0.0, 0.42, 0.83, 1.25, 1.67, 2.09, 2.2]
LANES = (-2.2, 0.0, 2.2)
CONTENT = os.path.join(lib.ROOT, "src", "config", "content.json")
BRANDS = json.load(open(CONTENT))["brands"]
BRAND_FONTS = {"SlopCola": "Futura.ttc", "GrindsetGPT": "DIN Condensed Bold.ttf", "DopaMint": "Avenir Next.ttc",
               "FOMOfone": "HelveticaNeue.ttc", "BrainFog": "DIN Alternate Bold.ttf", "Lonely.ai": "Didot.ttc",
               "NapLess": "Futura.ttc", "Serotonin+": "Avenir Next.ttc"}
SHEET_COLS, SHEET_ROWS = 4, 8
EXTRA_SIGNS = [
    dict(key="SALE", text="SALE", fg="#ffffff", bg="#ff2d6f", font="DIN Condensed Bold.ttf", size=0.8),
    dict(key="SALE_W", text="SALE", fg="#ff2d6f", bg="#fff6f9", font="DIN Condensed Bold.ttf", size=0.8),
    dict(key="70", text="-70%", fg="#ffffff", bg="#ff2d6f", font="DIN Alternate Bold.ttf", size=0.72),
    dict(key="BIO", text="LINK IN BIO", fg="#2a0020", bg="#ffd6ea", font="Futura.ttc", size=0.5, shape="round"),
    dict(key="NEW", text="NEW IN", fg="#ffffff", bg="#1a1418", font="Futura.ttc", size=0.5),
    dict(key="HERE", text="YOU ARE HERE", fg="#1a1418", bg="#fbf5f0", font="Avenir Next.ttc", size=0.45),
    dict(key="LAST", text="LAST CHANCE", fg="#ffffff", bg="#b8002e", font="DIN Condensed Bold.ttf", size=0.62),
    dict(key="GO", text="EVERYTHING MUST GO", fg="#ffffff", bg="#ff2d6f", font="DIN Condensed Bold.ttf", size=0.55),
    dict(key="OPEN", text="OPEN 24/7/365", fg="#fff6d8", bg="#2b1d14", font="Didot.ttc", size=0.5),
    dict(key="SALE_T", text="SALE", fg="#ffffff", bg=None, font="DIN Condensed Bold.ttf", size=0.8),
    dict(key="70_T", text="-70%", fg="#ffffff", bg=None, font="DIN Alternate Bold.ttf", size=0.72),
    dict(key="EXIT", text="EXIT  →  SOLD OUT", fg="#ffffff", bg="#1f7a4d", font="DIN Condensed Bold.ttf",
         size=0.55),
    dict(key="CARTS", text="RETURN CARTS HERE", fg="#ffffff", bg="#7a1f4d", font="DIN Condensed Bold.ttf",
         size=0.5),
    dict(key="LOW", text="lowkey the only phone with a feed", fg="#ffffff", bg="#7b2eff", font="Avenir Next.ttc",
         size=0.36, pad=0.08),
]


class MallMats:
    def __init__(self, sheet_path):
        self.marble = mat.pbr("M_Marble", "Marble021", mapping="BOX", box_scale=2.4, roughness_scale=0.35,
                              tint="#fbf4f6")
        self.marble_big = mat.pbr("M_MarbleBig", "Marble021", mapping="BOX", box_scale=6.0, roughness_scale=0.4,
                                  tint="#fbf4f6")
        self.marble_grey = mat.pbr("M_MarbleGrey", "Marble012", mapping="BOX", box_scale=2.0, roughness_scale=0.4,
                                   tint="#e8e0e4")
        self.brass = mat.pbr("M_Brass", "Metal034", mapping="BOX", box_scale=0.6, saturation=0.72, value=0.9,
                             roughness_offset=0.12, metallic=1.0)
        self.brass_big = mat.pbr("M_BrassBig", "Metal034", mapping="BOX", box_scale=2.5, saturation=0.72, value=0.9,
                                 roughness_offset=0.14, metallic=1.0)
        self.lacquer = smudged("M_Lacquer", "#f4ecef", rough=0.18, amount=0.12, scale=2.0,
                               smudge="SurfaceImperfections003")
        self.lacquer_big = smudged("M_LacquerBig", "#f4ecef", rough=0.2, amount=0.1, scale=8.0,
                                   smudge="SurfaceImperfections003")
        self.blush = smudged("M_Blush", "#eaa9c3", rough=0.22, amount=0.12, scale=2.0,
                             smudge="SurfaceImperfections003")
        self.plastic = mat.pbr("M_Plastic", "Plastic010", mapping="BOX", box_scale=1.0, tint="#f3eff1")
        self.chrome = mat.flat("M_Chrome", "#d9d6dc", rough=0.1, metal=1.0)
        self.rubber = mat.pbr("M_Rubber", "Rubber004", mapping="BOX", box_scale=0.6, tint="#3a3438")
        self.dark = mat.flat("M_Dark", "#16121a", rough=0.5)
        self.black_glass = smudged("M_BlackGlass", "#060507", rough=0.05, amount=0.25, scale=1.0)
        self.velvet = mat.pbr("M_Velvet", "velour_velvet", mapping="BOX", box_scale=0.5, tint="#d0306a")
        self.soil = mat.flat("M_Soil", "#2a2019", rough=0.95)
        self.bark = mat.flat("M_Bark", "#5a4636", rough=0.8)
        self.off = mat.flat("M_Off", "#0a090b", rough=0.2)
        self.led = glow("M_Led", "#fff3ea", 2.6)
        self.warm = glow("M_Warm", "#ffd8b0", 2.2)
        self.leaf = leaf_material("M_Leaf")
        self.wire = wire_material("M_Wire")
        self.screen = mat.emissive_screen("ScreenFeed", "#f6c6dc", 1.3, base="#050507")
        self.ad = mat.emissive_screen("AdFace", "#ff3d7f", 1.6, base="#050507")
        self.seam = mat.flat("Seam", "#ff66b3", rough=0.3, emission="#ff66b3", strength=3.0)
        # clean glass: a smudge map would export as plain roughness (glTF has no multiply-add)
        self.glass = mat.glass("Glass", color=(0.93, 0.96, 0.98), rough=0.05, alpha=0.16)
        self.sign = signage_material("Signage", sheet_path)


def signage_material(name, path):
    """The one emissive signage material: the text sheet as colour and glow (lightboxes)."""
    m = mat.new_material(name)
    g = G(m)
    t = g.node("ShaderNodeTexImage", interpolation="Linear")
    t.image = bpy.data.images.load(path, check_existing=True)
    uv = g.node("ShaderNodeTexCoord")
    g.link(uv.outputs["UV"], t.inputs["Vector"])
    g.link(t.outputs["Color"], g.p.inputs["Base Color"])
    g.link(t.outputs["Color"], g.p.inputs["Emission Color"])
    g.p.inputs["Emission Strength"].default_value = 1.8
    g.p.inputs["Roughness"].default_value = 0.3
    return m


def leaf_material(name):
    """Fiddle-leaf fig leaf on a 0..1 card: violin-shaped (wider toward the tip), waxy green, midrib and
    side veins; alpha is the leaf (baked into the atlas alpha, glTF MASK)."""
    m = mat.flat(name, "#2f5a2c", rough=0.58)
    g = G(m)
    tc = g.node("ShaderNodeTexCoord")
    sep = g.node("ShaderNodeSeparateXYZ")
    g.link(tc.outputs["UV"], sep.inputs[0])
    u, v = sep.outputs[0], sep.outputs[1]
    vv = g.math("MULTIPLY_ADD", g.sub(v, 0.04), 1.0 / 0.94, 0.0, clamp=True)
    s = g.math("POWER", g.math("SINE", g.mul(vv, math.pi)), 0.55)
    half = g.mul(g.mul(s, g.mad(vv, 0.42, 0.55)), 0.47)
    du = g.abs(g.sub(u, 0.5))
    alpha = g.mad(g.sub(du, half), -60.0, 0.5, clamp=True)
    # stem
    stem = g.mul(g.math("LESS_THAN", du, 0.02), g.math("LESS_THAN", v, 0.06))
    alpha = g.mx(alpha, stem)
    g.link(alpha, g.p.inputs["Alpha"])
    # colour: darker at the rim, a pale midrib and curved side veins
    rim = g.math("POWER", g.sat(g.math("DIVIDE", du, g.add(half, 0.001))), 3.0)
    base = g.lerpc(rim, "#3a6b33", "#1f3d1d")
    mid = g.mad(du, -120.0, 1.8, clamp=True)
    side = g.mul(g.mad(g.abs(g.sub(g.math("FRACT", g.mul(g.sub(v, g.mul(du, 1.4)), 7.0)), 0.5)), -30.0, 2.5,
                       clamp=True), 0.5)
    vein = g.mx(mid, side)
    col = g.lerpc(g.mul(vein, 0.7), base, "#8fb56f")
    g.link(col, g.p.inputs["Base Color"])
    mat.set_alpha(m, "CLIP", alpha)
    return m


def wire_material(name, pitch=9.0):
    """Chrome shopping-cart wire mesh on a 0..1 panel: a grid of wires, alpha elsewhere."""
    m = mat.flat(name, "#d6d4da", rough=0.18, metal=1.0)
    g = G(m)
    tc = g.node("ShaderNodeTexCoord")
    sep = g.node("ShaderNodeSeparateXYZ")
    g.link(tc.outputs["UV"], sep.inputs[0])
    wu = g.abs(g.sub(g.math("FRACT", g.mul(sep.outputs[0], pitch)), 0.5))
    wv = g.abs(g.sub(g.math("FRACT", g.mul(sep.outputs[1], pitch * 0.6)), 0.5))
    a = g.mx(g.mad(wu, 30.0, -13.0, clamp=True), g.mad(wv, 30.0, -13.0, clamp=True))
    edge = g.mx(g.math("LESS_THAN", g.mn(sep.outputs[0], g.sub(1.0, sep.outputs[0])), 0.03),
                g.math("LESS_THAN", g.mn(sep.outputs[1], g.sub(1.0, sep.outputs[1])), 0.03))
    a = g.mx(a, edge)
    mat.set_alpha(m, "CLIP", a)
    return m


def card(name, corners, m, both=True):
    """A quad with 0..1 UVs (corners p00, p10, p11, p01); `both` adds the back face."""
    b = MB([m])
    idx = b.verts(corners)
    b.face(idx)
    if both:
        idx2 = b.verts(corners)
        b.face(list(reversed(idx2)))
    o = b.build(name)
    lay = o.data.uv_layers["UVMap"]
    uvs = [(0, 0), (1, 0), (1, 1), (0, 1)]
    for p in o.data.polygons:
        for k, li in enumerate(p.loop_indices):
            vi = o.data.loops[li].vertex_index % 4
            lay.data[li].uv = uvs[vi]
    return o


def sign(name, M, cells, key, w, h, center, front, up=(0, 0, 1), depth=0.12, box=True, both=False):
    """A lightbox: a thin box (white lacquer sides) with the sheet cell on its front (and back)."""
    parts = []
    c = Vector(center)
    f = Vector(front).normalized()
    B = basis(f, up, c)
    if box:
        parts.append(rbox(f"{name}_box", w + 0.08, h + 0.08, depth, 0.03, 0.01, M.lacquer, seg=1,
                          xform=B @ T(0, 0, -depth / 2)))
    for sgn in ((1, -1) if both else (1,)):
        b = MB([M.sign])
        zz = 0.004 if box else 0.0
        q = [(-w / 2, -h / 2, zz), (w / 2, -h / 2, zz), (w / 2, h / 2, zz), (-w / 2, h / 2, zz)]
        if sgn < 0:
            q = [(-x, y, -depth - 0.004) for x, y, _ in q]
        b.face(b.verts(q))
        o = b.build(f"{name}_face{sgn:+d}")
        mesh.uv_fit_faces(o, material="Signage")
        uv_to_cell(o, "Signage", cells[key])
        o.data.transform(B)
        parts.append(o)
    return parts


# ------------------------------------------------------------------ deck

def mall_deck(M, kit, cells):
    """Polished white marble with brass-framed floor screens, brass-edged shoulders with floor stickers,
    a lacquered fascia and a downlit white underside."""
    bez = 0.06            # brass frame width around each screen
    sw, sh = 1.92, 4.06
    xs = [-4.8, -4.72]
    for cx in LANES:
        xs += [cx - sw / 2 - bez, cx + sw / 2 + bez]
    xs += [4.72, 4.8]
    ys = MALL_YS
    ye = sh / 2 + bez     # 2.09: bezel ends

    def in_lane(x0, x1):
        return any(cx - sw / 2 - bez - 1e-6 <= x0 and x1 <= cx + sw / 2 + bez + 1e-6 for cx in LANES)

    sticker = [
        # floor vinyl: a SALE disc on the right shoulder, -70% on the left, marble grout lines
        dict(kind="circle", plane="xy", c=(4.0, 0.9), s=(0.52, 0), color="#ff2d6f", rough=0.35, face=(0, 0, 1)),
        dict(kind="ring", plane="xy", c=(4.0, 0.9), s=(0.46, 0.012), color="#ffffff", face=(0, 0, 1)),
        dict(kind="image", plane="xy", c=(4.0, 0.9), s=(0.4, 0.1), image=cells["_path"], cell=cells["SALE_T"],
             rough=0.35, face=(0, 0, 1)),
        dict(kind="circle", plane="xy", c=(-4.0, -1.0), s=(0.5, 0), color="#ffffff", rough=0.35, face=(0, 0, 1)),
        dict(kind="circle", plane="xy", c=(-4.0, -1.0), s=(0.44, 0), color="#ff2d6f", rough=0.35, face=(0, 0, 1)),
        dict(kind="image", plane="xy", c=(-4.0, -1.0), s=(0.36, 0.09), image=cells["_path"], cell=cells["70_T"],
             rough=0.35, face=(0, 0, 1)),
        dict(kind="lines", plane="xy", axis="v", pitch=2.2, width=0.004, color="#cdbfc4", depth=-0.001),
        dict(kind="lines", plane="xy", axis="u", pitch=1.1, phase=0.0, width=0.004, color="#cdbfc4", depth=-0.001,
             w=(-1, 1)),
    ]
    marble = decorate(mat.pbr("M_DeckMarble", "Marble021", mapping="BOX", box_scale=2.2, roughness_scale=0.3,
                              tint="#fbf4f6"), sticker, soft=0.006)
    b = MB([marble])
    grid = {}
    for yi, y in enumerate(ys):
        for xi, x in enumerate(xs):
            grid[(xi, yi)] = b.verts([(x, y, 0.0)])[0]
    for yi in range(len(ys) - 1):
        for xi in range(len(xs) - 1):
            x0, x1 = xs[xi], xs[xi + 1]
            y0, y1 = ys[yi], ys[yi + 1]
            if in_lane(x0, x1) and -ye + 1e-6 <= y0 and y1 <= ye + 1e-6:
                continue  # the framed screen goes here
            if abs(x0) >= 4.72 - 1e-6 and abs(x1) >= 4.72 - 1e-6:
                continue  # brass nosing (swept below)
            b.face((grid[(xi, yi)], grid[(xi + 1, yi)], grid[(xi + 1, yi + 1)], grid[(xi, yi + 1)]))
    top = b.build("deck_top")
    # brass nosing and white lacquer fascia on both edges, the underside
    fascia = decorate(smudged("M_DeckFascia", "#f4ecef", rough=0.2, amount=0.1, scale=2.0,
                              smudge="SurfaceImperfections003"), [
        dict(kind="rect", plane="yz", c=(0.0, -0.26), s=(10.0, 0.012), color="#c9a46a", metal=1.0, rough=0.25),
    ], soft=0.006)
    right = [(4.72, 0.0), (4.772, -0.008), (4.8, -0.04), (4.8, -0.09), (4.8, -0.5), (4.76, -0.54)]
    left = [(-x, z) for x, z in reversed(right)]
    edge_mats = [M.brass, M.brass, M.brass, fascia, fascia]
    side_r = sweep("deck_edge_r", lambda y: right, ys, lambda j, k: edge_mats[j], [M.brass, fascia])
    side_l = sweep("deck_edge_l", lambda y: left, ys, lambda j, k: edge_mats[::-1][j], [M.brass, fascia])
    under_m = decorate(smudged("M_DeckUnder", "#f1ebee", rough=0.35, amount=0.1, scale=3.0,
                               smudge="SurfaceImperfections003"), [
        *[dict(kind="circle", plane="xy", c=(x, 0.0), s=(0.09, 0), emit=("#fff1e0", 2.0), color="#fff8f0")
          for x in (-3.3, -1.1, 1.1, 3.3)],
        *[dict(kind="ring", plane="xy", c=(x, 0.0), s=(0.11, 0.015), color="#c9a46a", metal=1.0)
          for x in (-3.3, -1.1, 1.1, 3.3)],
        dict(kind="lines", plane="xy", axis="u", pitch=2.2, width=0.01, color="#d8cfd3", depth=-0.002),
    ], soft=0.008)
    under = sweep("deck_under", lambda y: [(4.76, -0.54), (-4.76, -0.54)], ys, lambda j, k: 0, [under_m])
    # brass screen frames: outer chamfer down to the marble, a flat top, the inner lip
    frames, hidden = [], []
    for cx in LANES:
        rings = [(sw + 2 * bez, sh + 2 * bez, 0.0), (sw + 2 * bez - 0.02, sh + 2 * bez - 0.02, 0.014),
                 (sw + 0.012, sh + 0.012, 0.014), (sw, sh, 0.0), (sw, sh, -0.012)]
        bb = MB([M.brass])
        rr = [bb.verts([(cx + x, y, z) for x, y in rrect_pts(w, h, 0.006, 1)]) for w, h, z in rings]
        for i in range(len(rr) - 1):
            bb.bridge(rr[i], rr[i + 1], 0)
        frames.append(bb.build(f"deck_frame{cx:+.0f}"))
        hb = MB([M.off])
        hb.cap(hb.verts([(cx + x, y, -0.012) for x, y in rrect_pts(sw, sh, 0.006, 1)]), 0)
        hidden.append(hb.build(f"deck_hidden{cx:+.0f}"))
    top_all = join([top, side_r, side_l] + frames, "deck_top")
    hid = join(hidden, "deck_hidden")
    for o in (top_all, hid, under):
        loops(o, positions=ys[1:-1])
        mesh.clean(o, recalc_normals=False)
        finish(o, 35)
    kit.add("deck", [weight(top_all, 5.0), weight(hid, 0.02), weight(under, 0.5)], share=0.2)
    seams = []
    for sx in (-3.3, -1.1, 1.1, 3.3):
        w2 = 0.02
        pr = [(sx - w2, 0.0), (sx - w2, 0.008), (sx + w2, 0.008), (sx + w2, 0.0)]
        seams.append(sweep("seam", lambda y, pr=pr: pr, ys, lambda j, k: 0, [M.seam]))
    seam = join(seams, "deck_seam")
    finish(seam, 30)
    kit.add_plain("deck_seam", seam)


# ------------------------------------------------------------------ figures and props

def mannequin(M, name, m=None):
    """A faceless fashion mannequin (1.87 m), local: feet at the origin, facing +Y, doomscrolling: the right
    hand holds a phone up in front of a smooth, blank head; the left hand on the hip."""
    m = m or M.lacquer
    parts = []
    torso = lathe(f"{name}_torso", [(0.0, 0.84), (0.13, 0.86), (0.175, 0.96), (0.165, 1.04), (0.135, 1.13),
                                    (0.15, 1.24), (0.185, 1.34), (0.19, 1.41), (0.12, 1.47), (0.055, 1.5),
                                    (0.0, 1.51)], 14, m)
    for v in torso.data.vertices:
        v.co.y *= 0.62
    parts.append(torso)
    parts.append(lathe(f"{name}_neck", [(0.052, 1.46), (0.046, 1.6), (0.0, 1.61)], 10, m))
    head = lathe(f"{name}_head", [(0.0, 0.0), (0.06, 0.012), (0.094, 0.07), (0.1, 0.13), (0.09, 0.2), (0.058, 0.25),
                                  (0.0, 0.268)], 14, m)
    for v in head.data.vertices:
        v.co.y *= 1.12
    xf(head, T(0, 0.02, 1.58) @ R("X", -16))
    parts.append(head)
    # legs (contrapposto: the right knee bends a little)
    parts.append(tube(f"{name}_legl", [(0.09, 0.0, 0.93), (0.11, 0.02, 0.52), (0.115, -0.01, 0.1)],
                      [0.078, 0.055, 0.038], 10, m))
    parts.append(tube(f"{name}_legr", [(-0.09, 0.0, 0.93), (-0.1, 0.07, 0.52), (-0.15, 0.0, 0.1)],
                      [0.078, 0.055, 0.038], 10, m))
    for x, y in ((0.115, 0.06), (-0.15, 0.07)):
        parts.append(rbox(f"{name}_foot", 0.085, 0.24, 0.07, 0.035, 0.02, m, seg=2, center=(x, y, 0.035)))
    # arms: right raised with the phone, left on the hip
    parts.append(tube(f"{name}_armr", [(-0.19, 0.0, 1.4), (-0.25, 0.14, 1.17), (-0.07, 0.3, 1.5)],
                      [0.05, 0.038, 0.03], 8, m))
    parts.append(tube(f"{name}_arml", [(0.19, 0.0, 1.4), (0.31, -0.06, 1.13), (0.16, 0.0, 0.98)],
                      [0.05, 0.038, 0.03], 8, m))
    parts.append(rbox(f"{name}_handr", 0.05, 0.1, 0.03, 0.02, 0.01, m, seg=1,
                      xform=T(-0.05, 0.32, 1.54) @ R("X", 70)))
    parts.append(rbox(f"{name}_handl", 0.05, 0.1, 0.03, 0.02, 0.01, m, seg=1, xform=T(0.15, 0.02, 0.96)))
    # the phone faces the blank head; we see its back with the camera bump
    ph = phone(f"{name}_phone", 0.075, 0.155, 0.009, 0.012, M.chrome, M.black_glass, M.blush,
               screen=(0.07, 0.148, 0, 0.01), screen_mat=M.screen, seg=2,
               xform=basis(Vector((0.0, -1.0, 0.25)), (0, 0, 1), (-0.035, 0.36, 1.6)))
    parts.append(ph)
    return join(parts, name)


def mall_mannequin(M, kit, cells):
    """Wall: a mannequin on a tall marble plinth, like a statue lining the track, scrolling."""
    x = 0.8
    plinth = rbox("mq_plinth", 1.0, 1.0, 31.0, 0.05, 0.02, M.marble, seg=1, center=(x, 0, 1.0 - 15.5))
    cap = rbox("mq_cap", 1.12, 1.12, 0.08, 0.05, 0.02, M.brass, seg=1, center=(x, 0, 1.04))
    band = rbox("mq_band", 1.06, 1.06, 0.06, 0.05, 0.01, M.brass, seg=1, center=(x, 0, 0.1))
    fig = mannequin(M, "mq_fig")
    xf(fig, T(x, 0, 1.08) @ R("Z", 75) @ Matrix.Scale(1.3, 4))
    tag = sign("mq_tag", M, cells, "NEW", 0.7, 0.175, (x - 0.505, 0, 0.62), (-1, 0, 0), depth=0.03)
    o = join([plinth, cap, band, fig] + tag, "side_mannequin")
    finish(o, 40)
    kit.add("side_mannequin", away_parts(o, "side_mannequin", 1.5, w_back=0.4, deep=-2.0),
            dict(slot="wall", every=17.0, chance=0.55, side="both"), share=0.07)


def mall_ringlight(M, kit, cells):
    """Wall: the mall's street lamp: a brass ring-light stand leaning over the track, a phone in the ring."""
    px = 0.55
    prof = [(0.15, -30.0), (0.15, -0.6), (0.2, -0.55), (0.2, -0.3), (0.12, -0.25), (0.12, 3.2), (0.14, 3.24),
            (0.14, 3.4), (0.09, 3.44), (0.09, 6.9), (0.12, 6.94), (0.12, 7.1), (0.0, 7.16)]
    band = []
    for i in range(len(prof) - 1):
        (r0, z0), (r1, z1) = prof[i], prof[i + 1]
        band.append(M.lacquer if (abs(r0 - r1) < 1e-6 and z1 - z0 < 0.3) else M.brass)
    pole = lathe("rl_pole", prof, 8, band, xform=T(px, 0, 0))
    head_c = Vector((-0.55, 0.0, 6.65))
    arm = tube("rl_arm", [(px, 0, 7.1), (px - 0.3, 0, 7.3), (head_c.x + 0.45, 0, head_c.z + 0.6)], 0.065, 8, M.brass)
    nrm = Vector((-0.55, 0.0, -0.84)).normalized()
    ringM = basis(nrm, (1, 0, 0.6), head_c)
    rp = [(0.62, 0.02), (0.64, -0.1), (1.0, -0.1), (1.02, 0.02), (0.99, 0.05), (0.65, 0.05), (0.62, 0.02)]
    ring = lathe("rl_ring", rp, 22, [M.lacquer, M.lacquer, M.lacquer, M.led, M.led, M.led], xform=ringM)
    ph = phone("rl_phone", 0.5, 1.02, 0.06, 0.08, M.brass, M.black_glass, M.blush, screen=(0.46, 0.96, 0, 0.06),
               screen_mat=M.screen, seg=3, xform=ringM @ T(0, 0, 0.015))
    clamp = rbox("rl_clamp", 0.64, 0.12, 0.08, 0.04, 0.02, M.brass, seg=2, xform=ringM)
    spoke = rbox("rl_spoke", 0.08, 1.28, 0.05, 0.02, 0.01, M.brass, seg=1, xform=ringM @ T(0, 0, -0.04))
    o = join([pole, arm, ring, ph, clamp, spoke], "side_ringlight")
    finish(o, 40)
    kit.add("side_ringlight", away_parts(o, "side_ringlight", 1.4, w_back=0.4, deep=-3.0),
            dict(slot="wall", every=15.0, chance=0.8, side="both"), share=0.05)


def mall_plant(M, kit, cells):
    """Wall: a fiddle-leaf fig in a lacquered planter with a brass band, on a marble plinth."""
    rnd = random.Random(5)
    x = 0.9
    plinth = rbox("pl_plinth", 1.5, 1.5, 30.6, 0.05, 0.02, M.marble, seg=1, center=(x + 0.1, 0, 0.3 - 15.3))
    pot = lathe("pl_pot", [(0.0, 0.3), (0.52, 0.3), (0.64, 1.25), (0.68, 1.3), (0.62, 1.32), (0.58, 1.24),
                           (0.0, 1.24)], 20, [M.lacquer, M.lacquer, M.brass, M.brass, M.lacquer, M.soil],
                xform=T(x + 0.1, 0, 0))
    band = lathe("pl_band", [(0.59, 0.72), (0.6, 0.8)], 20, M.brass, xform=T(x + 0.1, 0, 0))
    parts = [plinth, pot, band]
    base = Vector((x + 0.1, 0.0, 1.24))
    trunk_pts = [base, base + Vector((0.06, 0.02, 0.8)), base + Vector((-0.05, 0.06, 1.7)),
                 base + Vector((0.03, -0.02, 2.7))]
    parts.append(tube("pl_trunk", [tuple(p) for p in trunk_pts], [0.06, 0.05, 0.04, 0.025], 6, M.bark))
    k = 0
    for i in range(110):
        t = rnd.uniform(0.22, 1.0)
        # a point on the trunk, then out to a leaf
        seg = min(2, int(t * 3))
        a, b_ = trunk_pts[seg], trunk_pts[seg + 1]
        p = a.lerp(b_, (t * 3) - seg)
        az = rnd.uniform(0, TAU)
        out = Vector((math.cos(az), math.sin(az), rnd.uniform(0.1, 0.9))).normalized()
        L = rnd.uniform(0.42, 0.6) * (1.1 - 0.3 * t)
        W = L * 0.72
        root = p + out * rnd.uniform(0.05, 0.4)
        tip_dir = (out + Vector((0, 0, rnd.uniform(-0.2, 0.5)))).normalized()
        side = tip_dir.cross(Vector((0, 0, 1)))
        if side.length < 1e-3:
            side = Vector((1, 0, 0))
        side.normalize()
        side.rotate(Matrix.Rotation(rnd.uniform(-0.6, 0.6), 3, tip_dir))
        c00 = root - side * W / 2
        c10 = root + side * W / 2
        c11 = root + side * W / 2 + tip_dir * L
        c01 = root - side * W / 2 + tip_dir * L
        parts.append(card(f"pl_leaf{i}", [tuple(c00), tuple(c10), tuple(c11), tuple(c01)], M.leaf))
        k += 1
    o = join(parts, "side_plant")
    finish(o, 40)
    kit.add("side_plant", away_parts(o, "side_plant", 1.2, w_back=0.8, deep=-2.0, away=0.95),
            dict(slot="wall", every=19.0, chance=0.6, side="both"), share=0.05)


def cart(M, name, xform):
    """A shopping cart (1.0 m long, basket of wire mesh panels, chrome frame, pink grip, castors); local:
    pushed toward +Y, wheels on z=0."""
    parts = []
    L, Wb, Wf, H0, H1 = 0.95, 0.56, 0.48, 0.5, 0.98
    # basket corners (back at y=0 wider, front at y=L narrower, bottom slightly shorter)
    bl, br = Vector((-Wb / 2, 0.05, H0)), Vector((Wb / 2, 0.05, H0))
    fl, fr = Vector((-Wf / 2, L, H0 + 0.05)), Vector((Wf / 2, L, H0 + 0.05))
    tbl, tbr = Vector((-Wb / 2, -0.02, H1)), Vector((Wb / 2, -0.02, H1))
    tfl, tfr = Vector((-Wf / 2 - 0.02, L + 0.04, H1)), Vector((Wf / 2 + 0.02, L + 0.04, H1))
    panels = [(bl, br, fr, fl), (bl, fl, tfl, tbl), (fr, br, tbr, tfr), (fl, fr, tfr, tfl), (br, bl, tbl, tbr)]
    for i, (a, b, c, d) in enumerate(panels):
        parts.append(card(f"{name}_p{i}", [tuple(a), tuple(b), tuple(c), tuple(d)], M.wire))
    rim = [tbl, tbr, tfr, tfl, tbl]
    parts.append(tube(f"{name}_rim", [tuple(p) for p in rim], 0.012, 4, M.chrome, caps=False))
    # chassis: two rails from the castors up to the handle
    for sx in (-1, 1):
        parts.append(tube(f"{name}_leg{sx}", [(sx * 0.24, -0.05, 0.12), (sx * 0.27, -0.12, 1.02),
                                              (sx * 0.27, -0.2, 1.06)], 0.014, 5, M.chrome, caps=False))
        parts.append(tube(f"{name}_base{sx}", [(sx * 0.24, -0.05, 0.12), (sx * 0.2, L - 0.05, 0.12)], 0.014, 5,
                          M.chrome, caps=False))
    parts.append(tube(f"{name}_grip", [(-0.29, -0.2, 1.06), (0.29, -0.2, 1.06)], 0.025, 8, M.blush))
    for x, y in ((-0.24, -0.05), (0.24, -0.05), (-0.2, L - 0.05), (0.2, L - 0.05)):
        parts.append(lathe(f"{name}_w", [(0.0, -0.03), (0.06, -0.03), (0.06, 0.03), (0.0, 0.03)], 8,
                           M.rubber, xform=T(x, y, 0.06) @ R("Y", 90)))
    o = join(parts, name)
    xf(o, xform)
    return o


def mall_cart(M, kit, cells):
    """Wall: a cart return bay: nested shopping carts on a floating marble plinth, a RETURN CARTS sign."""
    x = 1.0
    plinth = rbox("ct_plinth", 1.6, 5.0, 30.6, 0.05, 0.02, M.marble, seg=1, center=(x + 0.4, 0, 0.3 - 15.3))
    edge = rbox("ct_edge", 1.66, 5.06, 0.06, 0.05, 0.01, M.brass, seg=1, center=(x + 0.4, 0, 0.27))
    carts = [cart(M, f"ct_cart{i}", T(x + 0.4, -1.7 + i * 0.42, 0.3) @ Matrix.Scale(1.5, 4)) for i in range(5)]
    post = rbox("ct_post", 0.08, 0.08, 2.9, 0.02, 0.0, M.brass, seg=1, center=(x + 1.05, 2.2, 1.75))
    sg = sign("ct_sign", M, cells, "CARTS", 2.0, 0.5, (x + 1.05, 2.2, 3.4), (-1, 0, 0), depth=0.06, both=True)
    o = join([plinth, edge, post] + carts + sg, "side_cart")
    loops(o, 1.0)
    finish(o, 40)
    kit.add("side_cart", away_parts(o, "side_cart", 1.0, w_back=0.5, deep=-2.0, away=0.95),
            dict(slot="wall", every=38.0, chance=0.4, side="both"), share=0.06)


def mall_column(M, kit, cells):
    """Wall: an atrium column in marble with brass rings, a portrait digital poster on its track side."""
    x = 0.95
    prof = [(0.8, -30.0), (0.8, -0.2), (0.86, -0.15), (0.86, 0.1), (0.8, 0.15), (0.8, 7.8), (0.86, 7.85),
            (0.86, 8.1), (0.8, 8.15), (0.8, 15.8), (0.95, 16.3), (1.25, 16.6), (1.25, 16.9), (0.0, 16.95)]
    mats = []
    for i in range(len(prof) - 1):
        (r0, _), (r1, _) = prof[i], prof[i + 1]
        mats.append(M.brass if (r0 >= 0.85 or r1 >= 0.85) and i < len(prof) - 2 else M.marble)
    col = lathe("cl_col", prof, 16, mats, xform=T(x, 0, 0))
    # the poster: a brass-framed ScreenFeed portrait 1.3 x 2.6 on the track side
    frame = rbox("cl_frame", 1.74, 3.34, 0.12, 0.04, 0.02, M.brass, seg=1,
                 xform=basis((-1, 0, 0), (0, 0, 1), (x - 0.84, 0, 2.9)) @ T(0, 0, -0.06))
    b = MB([M.screen])
    q = [(-0.8, -1.6, 0.004), (0.8, -1.6, 0.004), (0.8, 1.6, 0.004), (-0.8, 1.6, 0.004)]
    b.face(b.verts(q))
    scr = b.build("cl_screen")
    mesh.uv_fit_faces(scr, material="ScreenFeed")
    xf(scr, basis((-1, 0, 0), (0, 0, 1), (x - 0.84, 0, 2.9)))
    o = join([col, frame, scr], "side_column")
    finish(o, 38)
    kit.add("side_column", away_parts(o, "side_column", 0.9, w_back=0.2, deep=-3.0),
            dict(slot="wall", every=26.0, chance=0.5, side="both"), share=0.05)


def mall_kiosk(M, kit, cells):
    """Mid: a 'link in bio' kiosk on a round marble island: blush counter, brass top, a portrait screen
    totem with a LINK IN BIO lightbox, a ring light and two stools."""
    cx = 3.2
    island = lathe("ks_island", [(0.0, -30.0), (1.2, -30.0), (1.2, -2.2), (2.9, -0.35), (3.2, -0.3), (3.2, 0.0),
                                 (0.0, 0.0)], 32, [M.marble_big, M.lacquer_big, M.lacquer_big, M.brass, M.brass,
                                                   M.marble], xform=T(cx, 0, 0))
    counter = rbox("ks_counter", 2.6, 1.3, 1.05, 0.6, 0.08, M.blush, seg=4, center=(cx, 0, 0.525))
    ctop = rbox("ks_ctop", 2.75, 1.45, 0.06, 0.66, 0.02, M.brass, seg=4, center=(cx, 0, 1.08))
    post = lathe("ks_post", [(0.08, 1.1), (0.08, 2.0)], 10, M.brass, xform=T(cx + 0.3, 0, 0))
    tot = rbox("ks_totem", 1.24, 2.36, 0.12, 0.08, 0.03, M.lacquer, seg=2,
               xform=basis((-1, 0, 0), (0, 0, 1), (cx + 0.3, 0, 3.2)) @ T(0, 0, -0.06))
    b = MB([M.screen])
    b.face(b.verts([(-0.56, -1.1, 0.004), (0.56, -1.1, 0.004), (0.56, 1.1, 0.004), (-0.56, 1.1, 0.004)]))
    scr = b.build("ks_screen")
    mesh.uv_fit_faces(scr, material="ScreenFeed")
    xf(scr, basis((-1, 0, 0), (0, 0, 1), (cx + 0.3 - 0.06, 0, 3.2)))
    bio = sign("ks_bio", M, cells, "BIO", 1.8, 0.45, (cx + 0.3, 0, 4.75), (-1, 0, 0), depth=0.14, both=True)
    slang = sign("ks_slang", M, cells, "LOW", 2.2, 0.28, (cx - 0.66, 0, 0.62), (-1, 0, 0), depth=0.02, box=False)
    # a ring light on a thin stand beside the counter, facing the stools
    rl_c = Vector((cx - 0.9, -1.2, 2.2))
    rlM = basis(Vector((-0.3, 0.9, -0.1)), (0, 0, 1), rl_c)
    ring = lathe("ks_ring", [(0.3, 0.02), (0.32, -0.05), (0.5, -0.05), (0.52, 0.02), (0.5, 0.03), (0.32, 0.03),
                             (0.3, 0.02)], 18, [M.lacquer, M.lacquer, M.lacquer, M.led, M.led, M.led], xform=rlM)
    rl_pole = lathe("ks_rlpole", [(0.03, 0.0), (0.03, 1.7)], 6, M.brass, xform=T(rl_c.x, rl_c.y, 0))
    stools = []
    for sy in (-0.6, 0.6):
        stools.append(lathe("ks_stool", [(0.0, 0.0), (0.22, 0.0), (0.2, 0.03), (0.04, 0.05), (0.04, 0.72),
                                         (0.2, 0.74), (0.22, 0.8), (0.0, 0.82)], 12,
                            [M.brass, M.brass, M.brass, M.brass, M.velvet, M.velvet, M.velvet],
                            xform=T(cx - 1.5, sy, 0)))
    o = join([island, counter, ctop, post, tot, scr, ring, rl_pole] + bio + slang + stools, "side_kiosk")
    loops(o, 1.0)
    finish(o, 38)
    kit.add("side_kiosk", away_parts(o, "side_kiosk", 0.6, deep=-4.0, away=0.8),
            dict(slot="mid", every=55.0, chance=0.5, side="both"), share=0.07)


# ------------------------------------------------------------------ architecture

def shop_level(M, cells, name, brand_key, zf, L, depth_front=3.0, height=5.2, x0=0.0):
    """One mall level facing the track (-X): slab edge at x0 with a lacquered fascia and brass line,
    a glass balustrade with a brass rail, a shopfront set back (brass mullions, glass), a lightbox
    fascia sign with the brand, and inside a feed poster and warm shelves."""
    parts = []
    sd = 0.55
    slab_m = decorate(smudged(f"M_Slab{name}", "#f4ecef", rough=0.2, amount=0.1, scale=4.0,
                              smudge="SurfaceImperfections003"), [
        dict(kind="rect", plane="yz", c=(0.0, zf - 0.18), s=(L, 0.02), color="#c9a46a", metal=1.0, rough=0.25,
             face=(-1, 0, 0)),
        # recessed downlights under the slab
        dict(kind="dots", plane="xy", c=(x0 + 1.4, 0.0), s=(0.9, L / 2), pitch=(1.6, 1.6), hole=0.1,
             emit=("#fff3e6", 2.4), color="#fffaf2", stagger=False, face=(0, 0, -1)),
    ], soft=0.02)
    slab = rbox(f"{name}_slab", 9.0, L, sd, 0.02, 0.0, slab_m, top=M.marble, seg=1, center=(x0 + 4.5, 0, zf - sd / 2))
    parts.append(slab)
    # glass balustrade + brass handrail
    b = MB([M.glass])
    b.face(b.verts([(x0 + 0.18, L / 2 - 0.1, zf), (x0 + 0.18, -L / 2 + 0.1, zf), (x0 + 0.18, -L / 2 + 0.1, zf + 1.05),
                    (x0 + 0.18, L / 2 - 0.1, zf + 1.05)]))
    parts.append(b.build(f"{name}_bal"))
    ys = [(-L / 2 + 0.1) + k * (L - 0.2) / math.ceil(L - 0.2) for k in range(int(math.ceil(L - 0.2)) + 1)]
    parts.append(tube(f"{name}_rail", [(x0 + 0.18, y, zf + 1.1) for y in ys], 0.045, 4, M.brass, flat_y=True))
    # the shopfront plane at xs
    xs = x0 + depth_front
    hf = height - 1.1  # glass height (fascia above)
    b = MB([M.glass])
    b.face(b.verts([(xs, L / 2 - 0.3, zf), (xs, -L / 2 + 0.3, zf), (xs, -L / 2 + 0.3, zf + hf),
                    (xs, L / 2 - 0.3, zf + hf)]))
    parts.append(b.build(f"{name}_front"))
    nm = max(2, int(L / 2.8))
    for i in range(nm + 1):
        y = -L / 2 + 0.3 + i * (L - 0.6) / nm
        parts.append(rbox(f"{name}_mull{i}", 0.12, 0.1, hf, 0.02, 0.0, M.brass, seg=1, center=(xs, y, zf + hf / 2)))
    # fascia band + brand lightbox
    fas = rbox(f"{name}_fascia", 0.3, L - 0.2, 1.1, 0.02, 0.0, M.lacquer, seg=1, center=(xs - 0.05, 0, zf + hf + 0.55))
    parts.append(fas)
    parts += sign(f"{name}_sign", M, cells, brand_key, 3.8, 0.95,
                  (xs - 0.21, 0, zf + hf + 0.55), (-1, 0, 0), depth=0.1)
    # inside: a feed poster, warm shelf lines, the back wall
    back = decorate(smudged(f"M_Back{name}", "#efe3e7", rough=0.4, amount=0.1, scale=3.0,
                            smudge="SurfaceImperfections003"), [
        dict(kind="lines", plane="yz", c=(0, zf + 1.6), s=(L / 2 - 0.5, 1.4), axis="v", pitch=0.7, width=0.05,
             emit=("#ffd9b8", 2.0), color="#fff0e0"),
    ], soft=0.02)
    wall = MB([back])
    xb = xs + 3.2
    wall.face(wall.verts([(xb, L / 2, zf), (xb, -L / 2, zf), (xb, -L / 2, zf + height), (xb, L / 2, zf + height)]))
    parts.append(wall.build(f"{name}_backwall"))
    b = MB([M.screen])
    pw, ph_ = 1.6, 3.0
    yc = -L / 4
    b.face(b.verts([(xs + 1.6, yc + pw / 2, zf + 0.7), (xs + 1.6, yc - pw / 2, zf + 0.7),
                    (xs + 1.6, yc - pw / 2, zf + 0.7 + ph_), (xs + 1.6, yc + pw / 2, zf + 0.7 + ph_)]))
    poster = b.build(f"{name}_poster")
    mesh.uv_fit_faces(poster, material="ScreenFeed")
    parts.append(poster)
    parts.append(rbox(f"{name}_postf", 0.08, pw + 0.12, ph_ + 0.12, 0.02, 0.0, M.brass, seg=1,
                      center=(xs + 1.65, yc, zf + 0.7 + ph_ / 2)))
    # a display plinth with a mannequin silhouette-ish form in the window
    parts.append(rbox(f"{name}_disp", 0.9, 0.9, 0.5, 0.05, 0.02, M.marble, seg=1, center=(xs + 1.0, L / 4, zf + 0.25)))
    parts.append(lathe(f"{name}_form", [(0.0, 0.5), (0.2, 1.1), (0.24, 1.5), (0.1, 1.75), (0.1, 2.05), (0.0, 2.12)],
                       8, M.lacquer,
                       xform=T(xs + 1.0, L / 4, zf)))
    return parts


def mall_store(M, kit, cells, node, brands, share):
    """Mid: a three-level block of shops facing the track, each level a different brand."""
    L = 16.0
    parts = []
    for i, (zf, bk) in enumerate(zip((-7.4, -1.4, 4.6), brands)):
        parts += shop_level(M, cells, f"{node}_l{i}", bk, zf, L)
    # roof slab + balustrade, base wall into the void, two columns at the front
    parts.append(rbox(f"{node}_roof", 9.0, L, 0.6, 0.02, 0.0, M.lacquer_big, seg=1, center=(4.5, 0, 10.3)))
    b = MB([M.glass])
    b.face(b.verts([(0.18, L / 2 - 0.1, 10.6), (0.18, -L / 2 + 0.1, 10.6), (0.18, -L / 2 + 0.1, 11.65),
                    (0.18, L / 2 - 0.1, 11.65)]))
    parts.append(b.build(f"{node}_roofbal"))
    base = decorate(smudged(f"M_Base{node}", "#e9dfe3", rough=0.35, amount=0.1, scale=6.0,
                            smudge="SurfaceImperfections003"), [
        dict(kind="lines", plane="yz", c=(0, -20), s=(L, 20), axis="v", pitch=3.0, width=0.03, color="#c9a46a",
             metal=1.0),
    ], soft=0.03)
    parts.append(rbox(f"{node}_base", 8.6, L, 23.0, 0.02, 0.0, base, seg=1, center=(4.7, 0, -7.95 - 11.5)))
    for y in (-L / 2 + 0.5, L / 2 - 0.5):
        parts.append(lathe(f"{node}_col", [(0.36, -8.0), (0.36, 10.0)], 12, M.lacquer_big, xform=T(0.9, y, 0)))
        for z in (-7.4, -1.4, 4.6):
            parts.append(lathe(f"{node}_colring", [(0.4, z + 0.02), (0.4, z + 0.18)], 12, M.brass_big,
                               xform=T(0.9, y, 0)))
    o = join(parts, node)
    loops(o, 1.0)
    mesh.clean(o, recalc_normals=False)
    finish(o, 38)
    kit.add(node, away_parts(o, node, 0.3, deep=-9.0, away=0.8),
            dict(slot="mid", every=34.0, chance=0.55, side="both"), share=share)


def escalator_run(M, name, x0, width, y0, z0, y1, z1, up=True):
    """One escalator from (y0, z0) to (y1, z1) at lateral offset x0 (width across X)."""
    parts = []
    run, rise = y1 - y0, z1 - z0
    nstep = int(round(math.hypot(run, rise) / 0.42))
    # steps: a sawtooth sweep across X (profile in YZ, swept along X) -> build as quads directly
    b = MB([decorate(metal(f"M_Step{name}", "Metal009", scale=0.4, tint="#b9b6bf", rough_scale=0.6), [
        dict(kind="lines", plane="xz", axis="u", pitch=0.04, width=0.012, color="#403c44", depth=-0.004),
    ], soft=0.004)])
    pts = []
    flat = 0.9
    pts.append((y0 - flat, z0))
    for k in range(nstep + 1):
        t = k / nstep
        y = y0 + run * t
        z = z0 + rise * t
        pts.append((y, z))
        if k < nstep:
            pts.append((y, z + rise / nstep))
    pts.append((y1 + flat, z1))
    L_ = b.verts([(x0, y, z) for y, z in pts])
    Rr = b.verts([(x0 + width, y, z) for y, z in pts])
    for i in range(len(pts) - 1):
        b.face((L_[i], Rr[i], Rr[i + 1], L_[i + 1]))
    parts.append(b.build(f"{name}_steps"))
    # the truss: skirts both sides (brushed steel), white cladding underneath
    th = 0.9
    for sx, xx in ((-1, x0 - 0.08), (1, x0 + width + 0.08)):
        sk = MB([M.chrome, M.lacquer])
        a0 = Vector((xx, y0 - flat, z0 + 0.15))
        a1 = Vector((xx, y0, z0 + 0.15))
        a2 = Vector((xx, y1, z1 + 0.15))
        a3 = Vector((xx, y1 + flat, z1 + 0.15))
        top_ = [a0, a1, a2, a3]
        bot = [p - Vector((0, 0, th)) for p in top_]
        tv = sk.verts(top_)
        bv = sk.verts(bot)
        for i in range(3):
            q = (bv[i], bv[i + 1], tv[i + 1], tv[i])
            sk.face(q, 1)
            sk.face(tuple(reversed(q)), 0)
        parts.append(sk.build(f"{name}_skirt{sx}"))
        # glass balustrade on the skirt and a black rubber handrail
        h = 0.95
        gt = [p + Vector((0, 0, h)) for p in top_]
        g2 = MB([M.glass])
        gv = g2.verts([top_[0], top_[3], gt[3], gt[0]])
        g2.face(gv)
        parts.append(g2.build(f"{name}_glass{sx}"))
        rail = [tuple(p + Vector((0, 0, 0.05))) for p in gt]
        parts.append(tube(f"{name}_rail{sx}", rail, 0.045, 6, M.rubber))
    under = MB([M.lacquer])
    bl = [Vector((x0 - 0.1, y0 - flat, z0 - th + 0.15)), Vector((x0 + width + 0.1, y0 - flat, z0 - th + 0.15)),
          Vector((x0 + width + 0.1, y1 + flat, z1 - th + 0.15)), Vector((x0 - 0.1, y1 + flat, z1 - th + 0.15))]
    under.face(tuple(reversed(under.verts(bl))))
    parts.append(under.build(f"{name}_under"))
    return parts


def mall_escalator(M, kit, cells):
    """Mid: a pair of escalators (up and down) crossing between two landings, glass balustrades, rubber
    handrails, a hanging SALE sign; the landings stand on lacquered piers into the void."""
    parts = []
    y0, y1, z0, z1 = -5.0, 5.4, -1.4, 4.6
    for i, x0 in enumerate((1.2, 2.9)):
        parts += escalator_run(M, f"es_run{i}", x0, 1.2, y0, z0, y1, z1, up=(i == 0))
    for (yy, zz) in ((y0 - 2.8, z0), (y1 + 2.8, z1)):
        parts.append(rbox("es_land", 4.6, 3.8, 0.5, 0.05, 0.0, M.lacquer_big, seg=1, center=(2.7, yy, zz - 0.25)))
        parts.append(rbox("es_landtop", 4.5, 3.7, 0.02, 0.05, 0.0, M.marble, seg=1, center=(2.7, yy, zz + 0.01)))
        parts.append(rbox("es_pier", 1.2, 1.2, 30.0, 0.05, 0.0, M.lacquer_big, seg=1, center=(2.7, yy, zz - 15.5)))
        parts.append(rbox("es_pierband", 1.26, 1.26, 0.12, 0.05, 0.0, M.brass, seg=1, center=(2.7, yy, zz - 0.62)))
    parts += sign("es_sale", M, cells, "SALE", 2.4, 0.6, (2.7, 0.2, 7.4), (-1, 0, 0), depth=0.14, both=True)
    for sy in (-0.9, 0.9):
        parts.append(tube("es_wire", [(2.7, 0.2 + sy, 7.7), (2.7, 0.2 + sy, 12.0)], 0.01, 3, M.chrome, caps=False))
    o = join(parts, "side_escalator")
    loops(o, 1.0)
    finish(o, 38)
    kit.add("side_escalator", away_parts(o, "side_escalator", 0.5, deep=-6.0, away=0.8),
            dict(slot="mid", every=62.0, chance=0.45, side="both"), share=0.08)


def mall_atrium(M, kit, cells):
    """Far: the atrium's other side: levels of balconies stacked up and down into the haze, shop windows
    glowing behind the balustrades, a column at each end."""
    L = 20.0
    fl = 6.0
    levels = [(-30.0 + fl * i) for i in range(12)]  # slab tops from -30 to 36
    # facade sweep: per level: slab edge (front), balustrade band, recess to the shopfront
    face_m = decorate(smudged("M_AtriumFace", "#f2eaee", rough=0.25, amount=0.1, scale=8.0,
                              smudge="SurfaceImperfections003"), [
        # brass line on each slab edge
        dict(kind="lines", plane="yz", c=(0, 0), s=(L, 100), axis="v", pitch=fl, width=0.08, phase=2.7,
             color="#c9a46a", metal=1.0, rough=0.25, w=(-0.1, 0.1)),
        # balustrade glass: a pale band with a brass handrail line
        dict(kind="lines", plane="yz", c=(0, 0), s=(L, 100), axis="v", pitch=fl, width=1.0, phase=3.55,
             color="#dde6ec", rough=0.05, w=(-0.1, 0.1)),
        dict(kind="lines", plane="yz", c=(0, 0), s=(L, 100), axis="v", pitch=fl, width=0.05, phase=4.05,
             color="#c9a46a", metal=1.0, rough=0.25, w=(-0.1, 0.1)),
        # shop windows glowing on the recess wall (warm, pink), mullions, a brand-colour sign band
        dict(kind="grid", plane="yz", c=(0.0, 0.25), s=(L, 100), pitch=(2.5, fl), frame=(0.15, 1.1), lit=0.85,
             seed=2.0, emit=("#ffe2c8", 1.6), color="#fff1e4", w=(2.8, 3.2)),
        dict(kind="grid", plane="yz", c=(1.25, 0.25), s=(L, 100), pitch=(5.0, fl), frame=(0.4, 1.1), lit=0.3,
             seed=9.0, emit=("#ffb3d1", 1.8), color="#ffd6e6", w=(2.8, 3.2)),
        dict(kind="grid", plane="yz", c=(0.0, 1.9), s=(L, 100), pitch=(5.0, fl), frame=(0.4, 2.7), lit=0.75,
             seed=4.0, emit=("#ff5c9a", 1.4), color="#ff8ab8", w=(2.8, 3.2)),
    ], soft=0.04)
    prof = []
    for zf in levels:  # bottom to top: slab edge + balustrade band, ledge, shop recess wall, slab underside
        prof += [(0.0, zf - 0.6), (0.0, zf + 1.1), (3.0, zf + 1.1), (3.0, zf + fl - 0.6)]
    ys = [-L / 2 + i for i in range(int(L) + 1)]
    b = MB([face_m])
    rings = [b.verts([(x, y, z) for x, z in prof]) for y in ys]
    for k in range(len(ys) - 1):
        for j in range(len(prof) - 1):
            # e1 along the profile, e2 = +Y: normal = e1 x Y (facade toward -X)
            b.face((rings[k][j], rings[k][j + 1], rings[k + 1][j + 1], rings[k + 1][j]))
    facade = b.build("at_facade")
    cols = []
    for y in (-L / 2 + 0.6, L / 2 - 0.6):
        cols.append(lathe("at_col", [(0.55, -32.0), (0.55, 40.0)], 10, M.lacquer_big, xform=T(0.2, y, 0)))
    o = join([facade] + cols, "side_atrium")
    loops(o, 1.0)
    finish(o, 30)
    kit.add("side_atrium", away_parts(o, "side_atrium", 0.12, deep=-12.0, away=0.8),
            dict(slot="far", every=22.0, chance=0.95, side="both"), share=0.08)


# ------------------------------------------------------------------ tunnel and overhang

def mall_tunnel(M, kit, cells):
    """A glass-roofed shopping arcade: marble ledges, lacquered wainscot, shop windows with feed
    posters behind glass, a fascia band, brass ribs springing into a glass barrel vault."""
    ys = [-2.2, -2.1, -1.68, -1.26, -0.84, -0.42, 0.0, 0.42, 0.84, 1.26, 1.68, 2.1, 2.2]
    xw = 6.2
    parts = []
    # ledge from the deck edge to the wall, the wainscot, the fascia band (sweeps, both sides)
    wall_m = decorate(smudged("M_ArcWall", "#f3ebee", rough=0.22, amount=0.1, scale=2.5,
                              smudge="SurfaceImperfections003"), [
        dict(kind="rect", plane="yz", c=(0.0, 1.05), s=(3.0, 0.015), color="#c9a46a", metal=1.0, rough=0.25),
        dict(kind="rect", plane="yz", c=(0.0, 6.35), s=(3.0, 0.015), color="#c9a46a", metal=1.0, rough=0.25),
    ], soft=0.006)
    for sx in (-1, 1):
        # right side profile (x, z) up the wall; mirrored on the left (reverse for normals)
        prof = [(4.8, -0.02), (xw, -0.02), (xw, 1.1)]
        fas = [(xw, 5.6), (xw - 0.25, 5.6), (xw - 0.25, 6.4), (xw, 6.4), (xw, 7.6)]
        pr = prof if sx > 0 else [(-x, z) for x, z in reversed(prof)]
        fr = fas if sx > 0 else [(-x, z) for x, z in reversed(fas)]
        # the sweep normal is e1 x Y: on the right wall, going up gives -X (into the arcade)
        ledge_j = 0 if sx > 0 else 1
        parts.append(sweep(f"arc_low{sx}", lambda y, pr=pr: pr, ys, lambda j, k, lj=ledge_j: 0 if j == lj else 1,
                           [M.marble, wall_m]))
        parts.append(sweep(f"arc_fas{sx}", lambda y, fr=fr: fr, ys, lambda j, k: 1, [M.marble, wall_m]))
        # shop window: glass from 1.1 to 5.6, a feed poster behind, brass mullions at the module ends
        g_ = MB([M.glass])
        q = [(sx * xw, -2.2, 1.1), (sx * xw, 2.2, 1.1), (sx * xw, 2.2, 5.6), (sx * xw, -2.2, 5.6)]
        g_.face(g_.verts(q if sx > 0 else list(reversed(q))))
        parts.append(g_.build(f"arc_glass{sx}"))
        b = MB([M.screen])
        xp = sx * (xw + 1.2)
        q = [(xp, -1.3, 1.5), (xp, 1.3, 1.5), (xp, 1.3, 5.2), (xp, -1.3, 5.2)]
        if sx > 0:
            q = [q[1], q[0], q[3], q[2]]
        b.face(b.verts(q))
        post = b.build(f"arc_poster{sx}")
        mesh.uv_fit_faces(post, material="ScreenFeed")
        parts.append(post)
        back = MB([wall_m])
        xb = sx * (xw + 1.3)
        q = [(xb, -2.2, -0.02), (xb, 2.2, -0.02), (xb, 2.2, 5.6), (xb, -2.2, 5.6)]
        back.face(back.verts(q if sx < 0 else list(reversed(q))))
        parts.append(back.build(f"arc_back{sx}"))
        sh = MB([M.marble])  # shop floor
        q = [(sx * xw, -2.2, -0.02), (sx * xw, 2.2, -0.02), (xb, 2.2, -0.02), (xb, -2.2, -0.02)]
        sh.face(sh.verts(q if sx < 0 else list(reversed(q))))
        parts.append(sh.build(f"arc_shopfloor{sx}"))
        sc = MB([wall_m])  # shop ceiling
        q = [(sx * xw, -2.2, 5.6), (sx * xw, 2.2, 5.6), (xb, 2.2, 5.6), (xb, -2.2, 5.6)]
        sc.face(sc.verts(q if sx > 0 else list(reversed(q))))
        parts.append(sc.build(f"arc_shopceil{sx}"))
        for yy in (-2.18, 2.18):
            parts.append(rbox(f"arc_mull{sx}", 0.14, 0.08, 4.5, 0.02, 0.0, M.brass, seg=1,
                              center=(sx * xw, yy, 1.1 + 2.25)))
        # a brand lightbox on the fascia, one brand each side
        key = BRANDS[5]["name"] if sx > 0 else BRANDS[6]["name"]
        parts += sign(f"arc_sign{sx}", M, cells, key, 2.4, 0.6, (sx * (xw - 0.26), 0.0, 6.0), (-sx, 0, 0), depth=0.08)
    # glass barrel vault from the wall tops (z 7.6) to the crown (z 11)
    n = 10
    arc = [(xw * math.cos(math.pi * i / n), 7.6 + 3.4 * math.sin(math.pi * i / n)) for i in range(n + 1)]
    roof = sweep("arc_roof", lambda y: arc, ys, lambda j, k: 0, [M.glass])
    parts.append(roof)
    # brass ribs at the module ends and a ridge
    for yy in (-2.2 + 0.06, 2.2 - 0.06):
        rib = MB([M.brass])
        inner = [(x * 0.985, z - 0.02) for x, z in arc]
        outer = [(x * 1.0, z + 0.2) for x, z in arc]
        a = rib.verts([(x, yy - 0.06, z) for x, z in inner])
        b_ = rib.verts([(x, yy - 0.06, z) for x, z in outer])
        c = rib.verts([(x, yy + 0.06, z) for x, z in outer])
        d = rib.verts([(x, yy + 0.06, z) for x, z in inner])
        rib.bridge(a, d, 0, closed=False)
        rib.bridge(d, c, 0, closed=False)
        rib.bridge(c, b_, 0, closed=False)
        rib.bridge(b_, a, 0, closed=False)
        parts.append(rib.build("arc_rib"))
    parts.append(tube("arc_ridge", [(0.0, y, 11.05) for y in ys], 0.08, 6, M.brass, caps=False, flat_y=True))
    # hanging pendant lights from the ribs
    for sx in (-1, 1):
        parts.append(tube("arc_cord", [(sx * 2.5, 0.0, 10.4), (sx * 2.5, 0.0, 8.6)], 0.01, 3, M.dark, caps=False))
        parts.append(lathe("arc_pend", [(0.0, 8.6), (0.3, 8.35), (0.34, 8.3), (0.0, 8.3)], 12,
                           [M.brass, M.brass, M.warm], xform=T(sx * 2.5, 0, 0)))
    o = join(parts, "tunnel")
    mesh.clean(o, recalc_normals=False)
    loops(o, positions=ys[1:-1])
    finish(o, 30)
    kit.add("tunnel", [weight(o, 1.0)], share=0.12)


def mall_overhang(M, kit, cells):
    """A hanging SALE gantry: a white box truss across the lanes on two brass-footed posts outside
    x +-3.6, the ad banner hanging under it (AdFace, 2:1, both faces) between SALE lightboxes."""
    parts = []
    zb, zt = 1.05, 3.2
    hb = zt - zb
    aw = 2 * hb
    # banner: AdFace both faces, a thin backing
    for sgn in (1, -1):
        b = MB([M.ad])
        yy = -sgn * 0.03
        q = [(-aw / 2, yy, zb), (aw / 2, yy, zb), (aw / 2, yy, zt), (-aw / 2, yy, zt)]
        if sgn < 0:
            q = [(-x, y, z) for x, y, z in q]
        b.face(b.verts(q))
        o = b.build(f"oh_ad{sgn:+d}")
        mesh.uv_fit_faces(o, material="AdFace")
        parts.append(o)
    parts.append(rbox("oh_back", aw + 0.08, 0.05, hb + 0.08, 0.02, 0.0, M.lacquer, seg=1,
                      center=(0, 0, (zb + zt) / 2)))
    # SALE lightboxes either side of the ad, both faces
    for sx in (-1, 1):
        for key, zz in ((("SALE", "70")[sx > 0], zt - 0.5), (("LAST", "SALE_W")[sx > 0], zb + 0.5)):
            parts += sign(f"oh_sign{sx}{key}", M, cells, key, 1.72, 0.43, (sx * (aw / 2 + 1.0), 0.0, zz), (0, -1, 0),
                          depth=0.14, both=True)
    # truss beam 7.8 wide at the top, hangers down to the banner
    beam = rbox("oh_beam", 9.2, 0.36, 0.42, 0.04, 0.02, M.lacquer, seg=1, center=(0, 0, zt + 0.35))
    parts.append(beam)
    parts.append(rbox("oh_beamline", 9.22, 0.37, 0.05, 0.04, 0.0, M.brass, seg=1, center=(0, 0, zt + 0.35)))
    for x in (-aw / 2 + 0.2, aw / 2 - 0.2, -(aw / 2 + 0.95), aw / 2 + 0.95):
        parts.append(tube("oh_hanger", [(x, 0, zt + 0.15), (x, 0, zt)], 0.012, 4, M.chrome, caps=False))
    # posts outside the lanes, brass feet, velvet ropes to little stanchions
    for sx in (-1, 1):
        x = sx * 4.25
        parts.append(rbox("oh_post", 0.22, 0.22, zt + 0.55, 0.05, 0.02, M.lacquer, seg=1,
                          center=(x, 0, (zt + 0.55) / 2)))
        parts.append(lathe("oh_foot", [(0.0, 0.0), (0.3, 0.0), (0.3, 0.05), (0.16, 0.1), (0.0, 0.1)], 16, M.brass,
                           xform=T(x, 0, 0)))
        parts.append(lathe("oh_cap", [(0.0, zt + 0.55), (0.16, zt + 0.55), (0.0, zt + 0.75)], 12, M.brass,
                           xform=T(x, 0, 0)))
        st = Vector((sx * 4.3, -1.1, 0))
        parts.append(lathe("oh_stanch", [(0.0, 0.0), (0.16, 0.0), (0.16, 0.03), (0.03, 0.05), (0.03, 0.95),
                                         (0.06, 1.0), (0.0, 1.04)], 10, M.brass, xform=T(st.x, st.y, 0)))
        rope = [(x, -0.12, 0.92), (x + (st.x - x) * 0.5, -0.6, 0.72), (st.x, st.y + 0.02, 0.92)]
        parts.append(tube("oh_rope", rope, 0.035, 6, M.velvet))
    o = join(parts, "overhang")
    finish(o, 35)
    kit.add("overhang", [weight(o, 2.0)], share=0.09)


# ------------------------------------------------------------------ sky

def mall_sky(out_jpg, preview_dir=None):
    """The atrium: a hall of balconies receding forever both ways under a ribbed skylight, shop lights
    in every level, haze to the mall's blush fog."""
    rnd = random.Random(21)
    col = lib.collection("_msky")
    made = []

    def put(ob):
        for cl in ob.users_collection:
            cl.objects.unlink(ob)
        col.objects.link(ob)
        made.append(ob)
        return ob

    world, nt = world_nodes("_mall_sky")
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Generated"], sep.inputs[0])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    cr = ramp.color_ramp
    stops = [(0.0, FOG), (0.5, FOG), (0.56, "#f4e9f2"), (0.8, "#e8f0fb"), (1.0, "#f7fbff")]
    while len(cr.elements) < len(stops):
        cr.elements.new(0.5)
    for i, (p, c) in enumerate(stops):
        cr.elements[i].position = p
        cr.elements[i].color = mat.rgba(c)
    mr = nt.nodes.new("ShaderNodeMapRange")
    mr.inputs["From Min"].default_value = -1.0
    mr.inputs["From Max"].default_value = 1.0
    nt.links.new(sep.outputs["Z"], mr.inputs["Value"])
    nt.links.new(mr.outputs["Result"], ramp.inputs["Fac"])
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Strength"].default_value = 1.0
    nt.links.new(ramp.outputs["Color"], bg.inputs["Color"])
    out = nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(bg.outputs[0], out.inputs["Surface"])

    def hazed(name, build_color, near=60.0, far=2600.0, power=0.75, strength=1.0, shade=True):
        """Emission with aerial haze toward the fog colour by camera distance. build_color(g) -> socket."""
        m = mat.new_material(name)
        t = m.node_tree
        t.nodes.clear()
        o = t.nodes.new("ShaderNodeOutputMaterial")
        g = G.__new__(G)
        g.m, g.nt, g._xyz, g._n = m, t, None, None
        c = build_color(g)
        if shade:
            n = g.nrm()
            L = Vector((0.25, -0.35, 0.9)).normalized()
            d = g.add(g.add(g.mul(n[0], L.x), g.mul(n[1], L.y)), g.mul(n[2], L.z))
            k = g.mad(g.mx(d, 0.0), 0.35, 0.62)
            sc_ = g.node("ShaderNodeVectorMath", operation="SCALE")
            g.link(c, sc_.inputs[0]) if isinstance(c, bpy.types.NodeSocket) else None
            if not isinstance(c, bpy.types.NodeSocket):
                sc_.inputs[0].default_value = tuple(c[:3])
            g.link(k, sc_.inputs["Scale"])
            c = sc_.outputs[0]
        cam = t.nodes.new("ShaderNodeCameraData")
        r = t.nodes.new("ShaderNodeMapRange")
        r.inputs["From Min"].default_value = near
        r.inputs["From Max"].default_value = far
        t.links.new(cam.outputs["View Distance"], r.inputs["Value"])
        pw = g.math("POWER", r.outputs["Result"], power)
        em = t.nodes.new("ShaderNodeEmission")
        em.inputs["Strength"].default_value = strength
        g.link(g.lerpc(pw, c, FOG), em.inputs["Color"])
        t.links.new(em.outputs[0], o.inputs["Surface"])
        return m

    def shop_col(g):
        # local x runs along the hall, local y is the height inside the level (-2.8..2.8)
        x, y, z = g.xyz()
        info = g.node("ShaderNodeObjectInfo")
        seed = g.mul(info.outputs["Random"], 53.0)
        cw = g.mad(info.outputs["Random"], 8.0, 7.0)
        iu = g.math("FLOOR", g.math("DIVIDE", x, cw))
        fu = g.abs(g.sub(g.math("FRACT", g.math("DIVIDE", x, cw)), 0.5))
        h1 = g.hash2(iu, seed)
        h2 = g.hash2(g.add(iu, 17.0), g.add(seed, 3.0))
        win = g.mul(g.math("LESS_THAN", fu, 0.36), g.math("LESS_THAN", y, 1.3))
        ramp_ = g.node("ShaderNodeValToRGB")
        c2 = ramp_.color_ramp
        c2.interpolation = "CONSTANT"
        pal = ["#f6dcc0", "#f4c1d4", "#f8e6d3", "#f7d2b2", "#f4c1d4", "#eeb0c8", "#f6dcc0", "#f9ece0"]
        while len(c2.elements) < len(pal):
            c2.elements.new(0.5)
        for i, c in enumerate(pal):
            c2.elements[i].position = i / len(pal)
            c2.elements[i].color = mat.rgba(c)
        g.link(h1, ramp_.inputs["Fac"])
        sc = g.node("ShaderNodeVectorMath", operation="SCALE")
        g.link(ramp_.outputs["Color"], sc.inputs[0])
        g.link(g.mul(g.mad(h2, 0.35, 0.65), win), sc.inputs["Scale"])
        fascia = g.math("GREATER_THAN", y, 1.3)
        c = g.lerpc(win, g.lerpc(fascia, "#5e4f58", "#e6dcde"), sc.outputs[0])
        band = g.mul(g.math("GREATER_THAN", y, 1.65), g.math("LESS_THAN", y, 2.2))
        band = g.mul(band, g.math("LESS_THAN", fu, 0.26))
        h3 = g.hash2(g.add(iu, 5.0), g.add(seed, 11.0))
        ramp2 = g.node("ShaderNodeValToRGB")
        c3 = ramp2.color_ramp
        c3.interpolation = "CONSTANT"
        pal2 = [b["bg"] for b in BRANDS]
        while len(c3.elements) < len(pal2):
            c3.elements.new(0.5)
        for i, cc in enumerate(pal2):
            c3.elements[i].position = i / len(pal2)
            c3.elements[i].color = mat.rgba(cc)
        g.link(h3, ramp2.inputs["Fac"])
        return g.lerpc(band, c, ramp2.outputs["Color"])

    slab_col = (lambda g: mat.rgba("#e9e1e0"))
    slab_m = hazed("_msky_slab", slab_col)
    shop_m = hazed("_msky_shop", shop_col, strength=1.15)
    col_m = hazed("_msky_col", lambda g: mat.rgba("#e3dbdb"))
    rib_m = hazed("_msky_rib", lambda g: mat.rgba("#b9b0b2"), far=3200.0, shade=False)
    sky_m = hazed("_msky_glass", lambda g: mat.rgba("#f2f6ff"), far=5000.0, strength=1.35, shade=False)
    banner_m = hazed("_msky_banner", lambda g: mat.rgba("#f0508f"))
    bal_m = hazed("_msky_bal", lambda g: mat.rgba("#aab6bf"), shade=False)
    W, Ly = 70.0, 5000.0
    for sx in (-1, 1):
        for i in range(-22, 18):
            zf = i * 7.0
            if zf < -120:
                continue
            # slab edge band (white, 1.4 m), the shop level glowing behind it
            sl = put(rbox(f"_mslab{sx}{i}", 2 * Ly, 1.6, 1.4, 0.01, 0.0, slab_m, seg=1))
            sl.matrix_world = Matrix.Translation((sx * (W + 0.8), 0, zf - 0.7)) @ R("Z", 90)
            gl = put(rbox(f"_mbal{sx}{i}", 2 * Ly, 0.1, 1.0, 0.01, 0.0, bal_m, seg=1))
            gl.matrix_world = Matrix.Translation((sx * W, 0, zf + 0.5)) @ R("Z", 90)
            sh = put(rbox(f"_mshop{sx}{i}", 2 * Ly, 5.6, 0.2, 0.01, 0.0, shop_m, seg=1))
            sh.matrix_world = Matrix.Translation((sx * (W + 5.0), 0, zf + 2.8)) @ R("Z", 90) @ R("X", 90)
        # columns every 18 m
        for k in range(-60, 60):
            y = k * 18.0 + (9.0 if sx > 0 else 0.0)
            if abs(y) > 1100:
                continue
            c = put(lathe(f"_mcol{sx}{k}", [(0.9, -130.0), (0.9, 126.0)], 8, col_m))
            c.matrix_world = Matrix.Translation((sx * (W + 0.4), y, 0))
    # skylight: a barrel vault of glass between ribs, 126 m up
    zr = 126.0
    arc = [((W + 2) * math.cos(math.pi * i / 16), zr + 26.0 * math.sin(math.pi * i / 16)) for i in range(17)]
    bb = MB([sky_m])
    rings = [bb.verts([(x, y, z) for x, z in arc]) for y in (-Ly, Ly)]
    for j in range(len(arc) - 1):
        bb.face((rings[0][j], rings[1][j], rings[1][j + 1], rings[0][j + 1]))
        bb.face((rings[0][j + 1], rings[1][j + 1], rings[1][j], rings[0][j]))
    put(bb.build("_mglass"))
    rb = MB([rib_m])
    for k in range(-120, 121):
        y = k * 14.0
        inner = [(x * 0.99, y - 0.6, z - 0.4) for x, z in arc]
        outer = [(x * 0.99, y + 0.6, z - 0.4) for x, z in arc]
        a = rb.verts(inner)
        c = rb.verts(outer)
        for j in range(len(arc) - 1):
            rb.face((a[j], c[j], c[j + 1], a[j + 1]))
            rb.face((a[j + 1], c[j + 1], c[j], a[j]))
    put(rb.build("_mribs"))
    for sx in (-1, 1):  # longitudinal beams along the springing
        be = put(rbox(f"_mbeam{sx}", 3.0, 2 * Ly, 3.0, 0.01, 0.0, rib_m, seg=1))
        be.matrix_world = Matrix.Translation((sx * (W + 1.0), 0, zr - 1.0))
    # hanging banners and a few bridges crossing the hall far away
    for k in range(-14, 15):
        y = k * 70.0 + rnd.uniform(-10, 10)
        if abs(y) < 30:
            continue
        x = rnd.uniform(-40, 40)
        if k % 2:
            continue
        bn = put(rbox(f"_mban{k}", 4.0, 0.2, 16.0, 0.01, 0.0, banner_m, seg=1))
        bn.matrix_world = Matrix.Translation((x, y, 70.0 + rnd.uniform(-10, 20)))
    for k in (-9, -5, -3, 3, 6, 11):
        y = k * 90.0
        br = put(rbox(f"_mbr{k}", 2 * W, 5.0, 1.6, 0.01, 0.0, slab_m, seg=1))
        br.matrix_world = Matrix.Translation((0, y, rnd.choice((14.0, 28.0, 42.0, -14.0))))
    # clusters of warm pendant globes hanging in front of the balconies
    globe_m = hazed("_msky_globe", lambda g: mat.rgba("#ffe2bf"), strength=1.6, shade=False)
    for sx in (-1, 1):
        for k in range(-60, 61):
            y = k * 24.0 + sx * 7.0
            for j in range(3):
                gz = 22.0 + 14.0 * j + 5.0 * math.sin(k * 1.7 + j)
                gb = put(lathe(f"_mgl{sx}{k}{j}", [(0.0, -1.1), (0.95, -0.6), (1.1, 0.0), (0.95, 0.6), (0.0, 1.1)], 8,
                               globe_m))
                gb.matrix_world = Matrix.Translation((sx * (W - 9.0 - 2.5 * j), y + 3.0 * j, gz))
    # escalators criss-crossing the void between the levels
    esc_m = hazed("_msky_esc", lambda g: mat.rgba("#e7dfdf"))
    for sx in (-1, 1):
        for k in range(-12, 13):
            y = k * 150.0 + sx * 40.0 + rnd.uniform(-20, 20)
            z0 = rnd.choice((-14.0, 0.0, 14.0, 28.0, 42.0))
            e = put(rbox(f"_mesc{sx}{k}", 3.0, 30.0, 1.4, 0.01, 0.0, esc_m, seg=1))
            e.matrix_world = Matrix.Translation((sx * (W - 7.0), y, z0 + 7.0)) @ R("X", math.degrees(math.atan2(14.0, 28.0)))
            gb_ = put(rbox(f"_mescg{sx}{k}", 3.1, 30.0, 1.0, 0.01, 0.0, bal_m, seg=1))
            gb_.matrix_world = Matrix.Translation((sx * (W - 7.0), y, z0 + 8.2)) @ R("X", math.degrees(math.atan2(14.0, 28.0)))
    floor_m = emission_material("_msky_floor", FOG, 1.0)
    put(lathe("_msky_floor", [(0.0, -60.0), (9000.0, -60.0)], 32, floor_m))
    cam = pano_camera(4.0)
    made.append(cam)
    render_sky(out_jpg, cam, world, samples=48, only=made)
    if preview_dir:
        import shutil
        shutil.copy(out_jpg, os.path.join(preview_dir, "sky.jpg"))
    for o in made:
        bpy.data.objects.remove(o, do_unlink=True)
    return out_jpg


# =================================================================== main

def make_sheet(path):
    cells = []
    keys = []
    for b in BRANDS:
        cells.append(dict(text=b["name"], fg=b["fg"], bg=b["bg"], font=BRAND_FONTS.get(b["name"], "Futura.ttc"),
                          size=0.6, pad=0.14))
        keys.append(b["name"])
    for e in EXTRA_SIGNS:
        cells.append({k: v for k, v in e.items() if k != "key"})
        keys.append(e["key"])
    rects = text_sheet(path, cells, SHEET_COLS, SHEET_ROWS)
    out = {k: rects[i] for i, k in enumerate(keys)}
    out["_path"] = path
    return out


def game_shots(prev, nodes, extras, sky_path):
    game_view(os.path.join(prev, "game.png"), nodes, extras, sky_path, LOOK, overhang_at=34.0)
    game_view(os.path.join(prev, "game_tunnel.png"), nodes, extras, sky_path, LOOK, tunnel=(-20.0, 120.0),
              cam_y=40.0)


def main():
    size = lib.arg("size", 2048, int)
    prev = lib.arg("preview")
    only = lib.arg("only")
    only = set(only.split(",")) if only else None
    sky_path = os.path.join(KITS_OUT, "mall-sky.jpg")
    cache_dir = os.path.join(lib.TOOLS, "cache", "kits")
    cache = os.path.join(cache_dir, "mall_baked.blend")
    extras_path = os.path.join(cache_dir, "mall_extras.json")
    lib.reset_scene()
    if prev:
        os.makedirs(prev, exist_ok=True)
    if lib.flag("sky-only"):
        mall_sky(sky_path, prev)
        if not lib.flag("game"):
            return
    if lib.flag("sky-only") or lib.flag("game-only"):
        nodes = load_nodes(cache)
        game_shots(prev, nodes, json.load(open(extras_path)), sky_path)
        return
    os.makedirs(os.path.join(cache_dir, "mall"), exist_ok=True)
    cells = make_sheet(os.path.join(cache_dir, "mall", "MallSigns.png"))
    M = MallMats(cells["_path"])
    kit = Kit("mall", keep=("ScreenFeed", "AdFace", "Seam", "Glass", "Signage"))
    stores = [("side_store", [BRANDS[0]["name"], BRANDS[3]["name"], BRANDS[5]["name"]], 0.1),
              ("side_store_b", [BRANDS[2]["name"], BRANDS[7]["name"], BRANDS[1]["name"]], 0.1)]
    builders = [("deck", mall_deck), ("side_mannequin", mall_mannequin), ("side_ringlight", mall_ringlight),
                ("side_plant", mall_plant), ("side_cart", mall_cart), ("side_column", mall_column),
                ("side_kiosk", mall_kiosk), ("side_escalator", mall_escalator), ("side_atrium", mall_atrium),
                ("tunnel", mall_tunnel), ("overhang", mall_overhang)]
    for name, fn in builders:
        if only is None or name in only:
            fn(M, kit, cells)
    for node, brands, share in stores:
        if only is None or node in only:
            mall_store(M, kit, cells, node, brands, share)
    kit.report()
    if prev and lib.flag("src"):
        src = os.path.join(prev, "src")
        for n, ps in list(kit.parts.items()):
            scenery = n.startswith("side_")
            preview_piece(src, n, ps, SCENERY_VIEWS if scenery else PIECE_VIEWS, zmin=-4.0 if scenery else None)
    if lib.flag("no-bake"):
        return
    res, nodes = bake_kit(kit, size, os.path.join(cache_dir, "mall"), "MallKit", alpha="CLIP")
    out = os.path.join(KITS_OUT, "mall.glb") if only is None else os.path.join(cache_dir, "mall_partial.glb")
    export_kit(nodes, out, size)
    extras = {n: kit.extras[n] for n in kit.extras if n.startswith("side_")}
    if only is None:
        cache_nodes(nodes, cache)
        json.dump(extras, open(extras_path, "w"), indent=1)
    if prev:
        for n, o in nodes.items():
            if n == "deck_seam":
                continue
            scenery = n.startswith("side_")
            preview_piece(prev, n, [o], SCENERY_VIEWS if scenery else PIECE_VIEWS, zmin=-4.0 if scenery else None)
    if not lib.flag("no-sky") and (only is None or lib.flag("sky")):
        mall_sky(sky_path, prev)
    if prev and not lib.flag("no-game") and os.path.exists(sky_path):
        game_shots(prev, nodes, extras, sky_path)


if __name__ == "__main__":
    main()
