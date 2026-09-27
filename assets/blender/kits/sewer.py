# Comment Section Sewer (biome 2): where content goes to rot. Underground,
# toxic green, wet, rage-bait graffiti. Contract: docs/assets-v2.md "Biome kits".
#
#   blender -b -P assets/blender/kits/sewer.py -- [--preview <dir>] [--work <dir>]
#       [--size 2048] [--ao 48] [--only deck,tunnel] [--nobake] [--nosky] [--skyonly]
#       [--sky-samples 96] [--sky-res 2048] [--noexport] [--packonly]
#       [--views [--exposure 1.2 --hemi 1.1 --sunI 0.8 --sun "#d2ffdc" --env 0.7 --fog 22,125]]
#
# --packonly packs the atlas and writes <work>/uvmap.png (who owns which texels);
# --views re-renders the game views from <work>/sewer_baked.blend (saved by a
# full run) with other look values, for tuning content.json zones[2].look.
#
# The atlas is baked with the lib (bake.bake_maps, mat.atlas,
# mesh.finalize_uvs) but packed here (kit_atlas/pack_atlas): each part's own
# metric unwrap ("Unwrap" UV layer), islands scaled by sqrt(atlas_weight) and
# skyline-packed. Blender's packer left ~55% of the atlas empty on this kit.
#
# Outputs public/assets/kits/sewer.glb (+ sewer-sky.jpg). Nodes:
#   deck, deck_seam (Seam), tunnel (the hero: brick egg-shaped sewer tube),
#   overhang (a fallen giant pipe), rail_sewer (steel pipe on brackets),
#   side_* scenery with extras slot/every/chance/side.
# Materials: one baked atlas (SewerKit) + Seam + Sludge (glossy toxic liquid)
# + SewerLight (caged fluorescent tubes; the renderer may flicker it).
# Text on the walls is drawn here as spray-paint strokes (no fonts), baked
# into the atlas. Generated textures and bakes go to --work (default
# tools/cache/sewer, gitignored).

import math
import os
import random
import sys

sys.dont_write_bytecode = True  # no __pycache__ in the repo
_d = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _d if os.path.isdir(os.path.join(_d, "lib")) else os.path.dirname(_d))

import bmesh  # noqa: E402
import bpy  # noqa: E402
import numpy as np  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402

import lib  # noqa: E402
from lib import bake, export, log, mat, mesh, preview  # noqa: E402

OUT = lib.arg("out", os.path.join(lib.PUBLIC, "kits", "sewer.glb"))
SKY_OUT = lib.arg("sky", os.path.join(lib.PUBLIC, "kits", "sewer-sky.jpg"))
PREVIEW = lib.arg("preview")
WORK = lib.arg("work", os.path.join(lib.TOOLS, "cache", "sewer"))
SIZE = lib.arg("size", 2048, int)
AO_SAMPLES = lib.arg("ao", 48, int)
ONLY = set(filter(None, (lib.arg("only") or "").split(",")))
NOBAKE = lib.flag("nobake")
NOEXPORT = lib.flag("noexport") or NOBAKE
SKIP_SKY = lib.flag("nosky")
SKY_ONLY = lib.flag("skyonly")
SKY_SAMPLES = lib.arg("sky-samples", 96, int)
SKY_RES = lib.arg("sky-res", 2048, int)
PACKONLY = lib.flag("packonly")  # pack the atlas UVs, dump a map of who owns which texels, stop
VIEWS = lib.flag("views")  # re-render the game views from the last baked scene (WORK/sewer_baked.blend)
TEX = os.path.join(WORK, "tex")

# In-game look this kit is tuned for (proposed for content.json zones[2].look).
LOOK = dict(sky="#030805", fog=(22, 125), hemi=1.1, hemi_sky="#8dffa4", hemi_ground="#150a24", sun="#d2ffdc",
            sunI=0.8, exposure=1.2, env=0.7, seam=(0.35, 1.7, 0.35))
SKY_GAIN = 0.72  # the vault stays darker than the scenery in front of it

for _k, _c in (("exposure", float), ("hemi", float), ("sunI", float), ("env", float)):
    if lib.arg(_k) is not None:
        LOOK[_k] = lib.arg(_k, cast=_c)
if lib.arg("sun"):
    LOOK["sun"] = lib.arg("sun")
if lib.arg("fog"):
    LOOK["fog"] = tuple(float(v) for v in lib.arg("fog").split(","))

LANE = 2.2
SCREEN_W, SCREEN_L = 1.92, 4.06
ROW = 4.4

# ------------------------------------------------------------------ small helpers


def stations(a, b, max_len, extra=()):
    """Coordinates from a to b, no gap over max_len, plus `extra` cuts."""
    n = max(1, math.ceil((b - a) / max_len - 1e-6))
    pts = {round(a + (b - a) * k / n, 5) for k in range(n + 1)}
    pts |= {round(e, 5) for e in extra if a < e < b}
    return sorted(pts)


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def to_srgb(x):
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def hexlin(h):
    return np.array(mat.rgb(h), dtype=np.float32)


def np_image(name, arr, data=False, alpha=True):
    """A bpy image from an (h, w, 4) float array (rows bottom-up, values as
    stored: sRGB-encoded for colour images, raw for data)."""
    h, w = arr.shape[:2]
    old = bpy.data.images.get(name)
    if old is not None:
        bpy.data.images.remove(old)
    img = bpy.data.images.new(name, w, h, alpha=alpha)
    img.colorspace_settings.name = "Non-Color" if data else "sRGB"
    img.pixels.foreach_set(np.ascontiguousarray(arr, dtype=np.float32).ravel())
    img.update()
    img.pack()
    return img


def save_np_png(arr, path):
    img = np_image("_save_tmp", arr)
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)
    return path


def box_blur(a, r):
    """Separable box blur (edge-clamped) of a 2D array, radius r px."""
    if r < 1:
        return a
    r = int(r)
    out = a
    for axis in (0, 1):
        pad = [(0, 0), (0, 0)]
        pad[axis] = (r + 1, r)
        p = np.pad(out, pad, mode="edge")
        c = np.cumsum(p, axis=axis)
        if axis == 0:
            out = (c[2 * r + 1:, :] - c[:-2 * r - 1, :]) / (2 * r + 1)
        else:
            out = (c[:, 2 * r + 1:] - c[:, :-2 * r - 1]) / (2 * r + 1)
    return out


def blur(a, sigma):
    """Three box blurs ~ a Gaussian."""
    r = max(1, int(round(sigma * 0.9)))
    for _ in range(3):
        a = box_blur(a, r)
    return a


def value_noise(h, w, cell, rng, octaves=4, wrap_y=False):
    """Smooth fractal value noise in 0..1, (h, w). wrap_y: tiles vertically."""
    out = np.zeros((h, w), np.float32)
    amp, total = 1.0, 0.0
    for o in range(octaves):
        c = max(2.0, cell / (2 ** o))
        gh = max(1, int(round(h / c))) if wrap_y else int(h / c) + 3
        cy = h / gh if wrap_y else c
        gw = int(w / c) + 3
        g = rng.random((gh + (0 if wrap_y else 1), gw)).astype(np.float32)
        ys = np.arange(h) / cy
        xs = np.arange(w) / c
        y0 = ys.astype(int)
        x0 = xs.astype(int)
        y1 = (y0 + 1) % gh if wrap_y else y0 + 1
        y0 = y0 % gh if wrap_y else y0
        fy = smoothstep(0, 1, ys - np.floor(ys))[:, None]
        fx = smoothstep(0, 1, xs - x0)[None, :]
        a = g[y0][:, x0]
        b = g[y0][:, x0 + 1]
        cc = g[y1][:, x0]
        d = g[y1][:, x0 + 1]
        out += amp * ((a * (1 - fx) + b * fx) * (1 - fy) + (cc * (1 - fx) + d * fx) * fy)
        total += amp
        amp *= 0.5
    return out / total


# ------------------------------------------------------------------ spray paint (strokes, no fonts)

# A tiny single-stroke hand: glyph -> strokes of (x, y) points, x-height 0.5,
# ascender 0.85, descender -0.32. Smoothed with Catmull-Rom, jittered by hand.
GLYPHS = {
    "a": [[(0.40, 0.40), (0.30, 0.50), (0.13, 0.48), (0.02, 0.30), (0.05, 0.07), (0.20, 0.00), (0.34, 0.07), (0.40, 0.24)],
          [(0.41, 0.50), (0.40, 0.12), (0.46, 0.0)]],
    "b": [[(0.03, 0.88), (0.02, 0.0)], [(0.02, 0.12), (0.15, 0.0), (0.32, 0.03), (0.41, 0.22), (0.34, 0.44), (0.16, 0.50), (0.03, 0.40)]],
    "c": [[(0.38, 0.42), (0.25, 0.50), (0.09, 0.45), (0.0, 0.25), (0.06, 0.05), (0.22, 0.0), (0.39, 0.08)]],
    "d": [[(0.40, 0.40), (0.30, 0.50), (0.13, 0.48), (0.02, 0.30), (0.05, 0.07), (0.20, 0.00), (0.34, 0.07), (0.40, 0.24)],
          [(0.42, 0.88), (0.40, 0.10), (0.46, 0.0)]],
    "e": [[(0.03, 0.25), (0.38, 0.29), (0.35, 0.43), (0.20, 0.50), (0.05, 0.42), (0.0, 0.22), (0.08, 0.05), (0.25, 0.0), (0.40, 0.09)]],
    "g": [[(0.40, 0.40), (0.30, 0.50), (0.13, 0.48), (0.02, 0.30), (0.05, 0.10), (0.20, 0.03), (0.34, 0.09), (0.40, 0.25)],
          [(0.41, 0.50), (0.40, -0.18), (0.30, -0.31), (0.13, -0.30), (0.03, -0.20)]],
    "h": [[(0.03, 0.88), (0.02, 0.0)], [(0.02, 0.28), (0.12, 0.44), (0.26, 0.50), (0.36, 0.42), (0.38, 0.22), (0.39, 0.0)]],
    "i": [[(0.08, 0.50), (0.07, 0.0)], [(0.09, 0.71), (0.10, 0.72)]],
    "k": [[(0.03, 0.88), (0.02, 0.0)], [(0.34, 0.50), (0.04, 0.20)], [(0.13, 0.28), (0.39, 0.0)]],
    "l": [[(0.08, 0.88), (0.07, 0.07), (0.14, 0.0)]],
    "L": [[(0.06, 0.90), (0.04, 0.02), (0.52, 0.0)]],
    "m": [[(0.02, 0.50), (0.02, 0.0)], [(0.02, 0.34), (0.12, 0.48), (0.22, 0.45), (0.25, 0.30), (0.25, 0.0)],
          [(0.25, 0.34), (0.36, 0.48), (0.46, 0.45), (0.49, 0.30), (0.49, 0.0)]],
    "n": [[(0.02, 0.50), (0.02, 0.0)], [(0.02, 0.32), (0.12, 0.46), (0.25, 0.50), (0.36, 0.42), (0.38, 0.22), (0.39, 0.0)]],
    "o": [[(0.21, 0.50), (0.06, 0.43), (0.0, 0.22), (0.07, 0.04), (0.22, 0.0), (0.36, 0.08), (0.41, 0.28), (0.34, 0.45), (0.19, 0.50), (0.12, 0.46)]],
    "p": [[(0.02, 0.50), (0.02, -0.32)], [(0.02, 0.38), (0.15, 0.49), (0.32, 0.47), (0.41, 0.28), (0.33, 0.06), (0.18, 0.0), (0.03, 0.08)]],
    "r": [[(0.02, 0.50), (0.02, 0.0)], [(0.02, 0.30), (0.10, 0.44), (0.22, 0.50), (0.33, 0.47)]],
    "s": [[(0.35, 0.45), (0.22, 0.50), (0.08, 0.46), (0.05, 0.36), (0.15, 0.28), (0.30, 0.22), (0.37, 0.12), (0.30, 0.02), (0.15, 0.0), (0.01, 0.06)]],
    "t": [[(0.13, 0.76), (0.12, 0.08), (0.18, 0.0), (0.30, 0.03)], [(0.0, 0.48), (0.29, 0.50)]],
    "u": [[(0.02, 0.50), (0.02, 0.16), (0.10, 0.02), (0.22, 0.0), (0.34, 0.08), (0.38, 0.22)], [(0.39, 0.50), (0.38, 0.08), (0.43, 0.0)]],
    "w": [[(0.0, 0.50), (0.12, 0.0), (0.25, 0.36), (0.38, 0.0), (0.51, 0.50)]],
    "y": [[(0.0, 0.50), (0.19, 0.06)], [(0.41, 0.50), (0.19, 0.04), (0.10, -0.25), (0.0, -0.32)]],
    "?": [[(0.05, 0.64), (0.12, 0.78), (0.25, 0.83), (0.37, 0.75), (0.38, 0.60), (0.28, 0.48), (0.20, 0.38), (0.20, 0.22)], [(0.20, 0.05), (0.21, 0.04)]],
    "+": [[(0.0, 0.30), (0.40, 0.31)], [(0.20, 0.10), (0.21, 0.52)]],
    "!": [[(0.10, 0.85), (0.08, 0.22)], [(0.08, 0.05), (0.09, 0.04)]],
    "v": [[(0.0, 0.50), (0.19, 0.0), (0.40, 0.50)]],
    "f": [[(0.36, 0.80), (0.27, 0.87), (0.16, 0.83), (0.12, 0.68), (0.11, 0.0)], [(0.0, 0.48), (0.30, 0.50)]],
}


def _catmull(pts, step):
    """Dense Catmull-Rom samples through pts, about `step` apart."""
    if len(pts) == 2:
        a, b = np.array(pts[0]), np.array(pts[1])
        n = max(2, int(np.linalg.norm(b - a) / step))
        return [tuple(a + (b - a) * t) for t in np.linspace(0, 1, n)]
    p = [pts[0]] + list(pts) + [pts[-1]]
    out = []
    for i in range(1, len(p) - 2):
        p0, p1, p2, p3 = (np.array(q, dtype=float) for q in p[i - 1:i + 3])
        n = max(2, int(np.linalg.norm(p2 - p1) / step))
        for t in np.linspace(0, 1, n, endpoint=False):
            t2, t3 = t * t, t * t * t
            out.append(tuple(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 +
                                    (-p0 + 3 * p1 - 3 * p2 + p3) * t3)))
    out.append(tuple(p[-2]))
    return out


def layout_text(text, rng, slant=0.2, gap=0.09, size=1.0, wobble=0.035):
    """Strokes (lists of (x, y)) for a phrase in the stroke hand, and its width."""
    strokes, x = [], 0.0
    for ch in text:
        if ch == " ":
            x += 0.32 * size
            continue
        g = GLYPHS[ch]
        s = size * rng.uniform(0.9, 1.12)
        dy = rng.uniform(-wobble, wobble) * size
        rot = rng.uniform(-0.06, 0.06)
        w = max(px for st in g for px, _ in st)
        for st in g:
            pts = []
            for px, py in st:
                qx, qy = px * s, py * s
                qx, qy = qx * math.cos(rot) - qy * math.sin(rot), qx * math.sin(rot) + qy * math.cos(rot)
                qx += slant * qy + rng.normal(0, 0.012) * size
                qy += dy + rng.normal(0, 0.012) * size
                pts.append((x + qx, qy))
            strokes.append(pts)
        x += w * s + gap * size
    return strokes, x


class Spray:
    """Spray-paint raster: soft cores, overspray speckle, drips. RGBA sRGB."""

    def __init__(self, w, h, seed=1):
        self.w, self.h = w, h
        self.rgb = np.zeros((h, w, 3), np.float32)
        self.a = np.zeros((h, w), np.float32)
        self.rng = np.random.default_rng(seed)

    def _layer(self):
        return np.zeros((self.h, self.w), np.float32)

    @staticmethod
    def _disc(buf, cx, cy, r, soft=1.2):
        h, w = buf.shape
        x0, x1 = int(max(0, cx - r - 3)), int(min(w, cx + r + 4))
        y0, y1 = int(max(0, cy - r - 3)), int(min(h, cy + r + 4))
        if x0 >= x1 or y0 >= y1:
            return
        yy, xx = np.ogrid[y0:y1, x0:x1]
        d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
        np.maximum(buf[y0:y1, x0:x1], np.clip((r - d) / soft + 0.5, 0, 1), out=buf[y0:y1, x0:x1])

    def strokes(self, strokes, to_px, width, colour, drips=0.25, overspray=1.0, pressure=0.18):
        """Paint strokes (unit coords, mapped by to_px(x, y) -> (px, py))."""
        core, mist = self._layer(), self._layer()
        rng = self.rng
        pts_all = []
        for st in strokes:
            dense = _catmull([to_px(*p) for p in st], max(1.0, width * 0.22))
            n = len(dense)
            ph = rng.uniform(0, 6.28)
            for k, (px, py) in enumerate(dense):
                t = k / max(1, n - 1)
                taper = 0.75 + 0.25 * min(1.0, 6 * t, 6 * (1 - t))
                r = width * 0.5 * taper * (1 + pressure * math.sin(ph + k * 0.21))
                self._disc(core, px, py, r)
                pts_all.append((px, py, r))
            # paint pools at the stroke's end: a slightly bigger blob
            ex, ey = dense[-1]
            self._disc(core, ex, ey, width * 0.62)
        for px, py, r in pts_all[::3]:
            self._disc(mist, px, py, r * 2.6, soft=r * 1.6)
        # drips from low points and stroke ends
        if drips > 0 and pts_all:
            idx = rng.choice(len(pts_all), size=max(1, int(len(pts_all) * drips * 0.02)), replace=False)
            for i in idx:
                px, py, r = pts_all[i]
                length = r * rng.uniform(2.5, 14.0)
                wdt = r * rng.uniform(0.28, 0.5)
                steps = int(length / 1.5)
                drift = rng.normal(0, 0.03)
                for s in range(steps):
                    q = s / max(1, steps)
                    self._disc(core, px + drift * s, py - s * 1.5, wdt * (1 - 0.35 * q))
                self._disc(core, px + drift * steps, py - steps * 1.5, wdt * 1.35)
        speck = rng.random((self.h, self.w)).astype(np.float32)
        mist_a = np.clip(mist * 0.28 + (speck < mist * 0.35) * 0.55, 0, 1) * overspray
        a = np.maximum(core, mist_a)
        c = np.array(colour, np.float32)
        # "over" composite
        self.rgb = self.rgb * (1 - a[..., None]) + c[None, None, :] * a[..., None]
        self.a = self.a + a * (1 - self.a)

    def arrow_down(self, cx, cy, size, colour, width):
        """A spray-painted downvote arrow outline."""
        s = size
        pts = [(-0.25, 0.5), (0.25, 0.5), (0.25, 0.0), (0.55, 0.0), (0.0, -0.55), (-0.55, 0.0), (-0.25, 0.0), (-0.25, 0.5)]
        self.strokes([[(cx + x * s, cy + y * s) for x, y in pts]], lambda x, y: (x, y), width, colour, drips=0.4)

    def rgba(self):
        out = np.zeros((self.h, self.w, 4), np.float32)
        a = np.clip(self.a, 1e-4, 1)
        out[..., :3] = to_srgb(self.rgb / a[..., None])
        out[..., 3] = self.a
        return out  # row 0 is the bottom (Blender), y grows upward


def graffiti_image(name, lines, w=1024, h=512, seed=3, pad=0.08):
    """Render phrases into one RGBA image. lines: dicts with text, colour
    (linear), outline (colour or None), size (relative line height), x/y
    (0..1 anchor of the line's left/baseline), slant, width (stroke px)."""
    rng = np.random.default_rng(seed)
    sp = Spray(w, h, seed)
    for ln in lines:
        strokes, tw = layout_text(ln["text"], rng, slant=ln.get("slant", 0.2), size=1.0)
        px_per = ln["size"] * h  # one unit = size * image height
        ox, oy = ln["x"] * w, ln["y"] * h

        def to_px(x, y, px_per=px_per, ox=ox, oy=oy):
            return ox + x * px_per, oy + y * px_per

        width = ln.get("width", px_per * 0.11)
        if ln.get("outline") is not None:
            sp.strokes(strokes, to_px, width * 2.0, ln["outline"], drips=0.12, overspray=0.35)
        sp.strokes(strokes, to_px, width, ln["colour"], drips=ln.get("drips", 0.3))
        if ln.get("arrow"):
            ax, ay, asz = ln["arrow"]
            sp.arrow_down(ax * w, ay * h, asz * h, ln["colour"], width * 0.8)
    arr = sp.rgba()
    img = np_image(name, arr)
    os.makedirs(TEX, exist_ok=True)
    save_np_png(arr, os.path.join(TEX, name + ".png"))
    return img


def build_graffiti():
    red, white, green, pink, yellow = hexlin("#d9262b"), hexlin("#e9ece6"), hexlin("#86ff3a"), hexlin("#ff3d8b"), hexlin("#ffcf1f")
    black = hexlin("#0b0b0b")
    G = {}
    G["ratio"] = graffiti_image("gf_ratio", [
        dict(text="ratio", colour=white, outline=red, size=0.62, x=0.06, y=0.30, slant=0.25),
    ], 1024, 512, seed=11)
    G["L"] = graffiti_image("gf_L", [
        dict(text="L", colour=red, outline=None, size=0.9, x=0.18, y=0.08, slant=0.15, width=46),
    ], 512, 512, seed=12)
    G["whoasked"] = graffiti_image("gf_whoasked", [
        dict(text="who asked", colour=green, outline=None, size=0.52, x=0.03, y=0.34, slant=0.22),
    ], 1024, 384, seed=13)
    G["thisyou"] = graffiti_image("gf_thisyou", [
        dict(text="this you?", colour=white, outline=None, size=0.5, x=0.04, y=0.42, slant=0.18, arrow=(0.86, 0.22, 0.28)),
    ], 1024, 384, seed=14)
    G["touchgrass"] = graffiti_image("gf_touchgrass", [
        dict(text="touch grass", colour=pink, outline=black, size=0.5, x=0.03, y=0.32, slant=0.2),
    ], 1024, 320, seed=15)
    G["cope"] = graffiti_image("gf_cope", [
        dict(text="cope", colour=yellow, outline=None, size=0.62, x=0.08, y=0.3, slant=0.2),
        dict(text="+ L", colour=red, outline=None, size=0.42, x=0.55, y=0.05, slant=0.2),
    ], 1024, 512, seed=16)
    G["logoff"] = graffiti_image("gf_logoff", [
        dict(text="log off", colour=white, outline=None, size=0.55, x=0.05, y=0.3, slant=0.22, drips=0.5),
    ], 1024, 384, seed=17)
    G["arrow"] = graffiti_image("gf_arrow", [
        dict(text="", colour=red, size=0.5, x=0.5, y=0.5, arrow=(0.5, 0.55, 0.62)),
    ], 256, 256, seed=18)
    return G


# ------------------------------------------------------------------ other generated textures


def deck_mask_image():
    """Deck top masks over x -4.8..4.8, y -2.2..2.2 (object XY):
    R steel (bezels, seam channels, kerb edge), G grate bars, B grate area,
    A yellow kerb paint."""
    W, H = 2048, 1024
    xs = (np.arange(W) + 0.5) / W * 9.6 - 4.8
    ys = (np.arange(H) + 0.5) / H * 4.4 - 2.2
    X, Y = np.meshgrid(xs, ys)
    ax, ay = np.abs(X), np.abs(Y)
    rng = np.random.default_rng(5)
    steel = np.zeros_like(X)
    bez = 0.06
    hl, sw = SCREEN_L / 2, SCREEN_W / 2
    for cx in (-LANE, 0.0, LANE):
        dx = np.abs(X - cx)
        ring = (dx < sw + bez) & (ay < hl + bez) & ~((dx < sw) & (ay < hl))
        steel = np.maximum(steel, ring)
    for sx in (1.1, 3.3):  # seam channels
        steel = np.maximum(steel, (np.abs(ax - sx) < 0.055) & (ay < 2.2))
    steel = np.maximum(steel, (ax > 4.25) & (ax < 4.37))  # kerb steel edge
    joint = (ay > hl + bez) & (ax < 3.62)
    gutter = (ax > 3.64) & (ax < 4.27)
    bars = np.zeros_like(X)
    # joint grate: bars along Y every 0.1 m in x, a frame at the grate edges
    jb = (np.mod(X + 0.05, 0.1) < 0.036) | (ay > 2.185) | (ay < hl + bez + 0.02)
    bars = np.where(joint, jb, bars)
    # gutter grate: bars across every 0.11 m, frame rails at both edges
    gb = (np.mod(Y + 0.055, 0.11) < 0.055) | (ax < 3.68) | (ax > 4.23)
    bars = np.where(gutter, gb, bars)
    # seam channels cut through the joint grates
    for sx in (1.1, 3.3):
        ch = np.abs(ax - sx) < 0.055
        bars = np.where(joint & ch, 1.0, bars)
    area = np.maximum((joint & ~((np.abs(ax - 1.1) < 0.055) | (np.abs(ax - 3.3) < 0.055))) * 0.5, gutter * 1.0).astype(np.float32)
    # worn yellow line on the kerb top
    n = value_noise(H, W, 40, rng, wrap_y=True)
    paint = ((ax > 4.43) & (ax < 4.53)) * smoothstep(0.35, 0.5, n)
    out = np.zeros((H, W, 4), np.float32)
    out[..., 0] = steel
    out[..., 1] = bars
    out[..., 2] = area
    out[..., 3] = paint
    return np_image("deck_mask", out, data=True)


def crack_image(seed=7, w=512, h=1024, impact=(0.3, 0.25)):
    """Cracked phone glass: R crack lines, G shattered core, B glow mask."""
    rng = np.random.default_rng(seed)
    cr = np.zeros((h, w), np.float32)
    ix, iy = impact[0] * w, impact[1] * h

    def line(x0, y0, x1, y1, width):
        n = int(max(abs(x1 - x0), abs(y1 - y0)) / 0.7) + 1
        for t in np.linspace(0, 1, n):
            x, y = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
            xi, yi = int(x), int(y)
            r = int(math.ceil(width))
            if 0 <= xi < w and 0 <= yi < h:
                cr[max(0, yi - r + 1):yi + r, max(0, xi - r + 1):xi + r] = 1.0

    radials = []
    n_rad = 14
    for k in range(n_rad):
        ang = 2 * math.pi * k / n_rad + rng.normal(0, 0.15)
        x, y = ix, iy
        pts = [(x, y)]
        for _ in range(60):
            ang += rng.normal(0, 0.12)
            step = rng.uniform(14, 30)
            nx, ny = x + math.cos(ang) * step, y + math.sin(ang) * step
            line(x, y, nx, ny, 1.2)
            x, y = nx, ny
            pts.append((x, y))
            if not (0 <= x < w and 0 <= y < h):
                break
            if rng.random() < 0.06:  # branch
                bang = ang + rng.choice([-1, 1]) * rng.uniform(0.4, 0.9)
                bx, by = x, y
                for _ in range(int(rng.integers(3, 10))):
                    bang += rng.normal(0, 0.15)
                    nbx, nby = bx + math.cos(bang) * 16, by + math.sin(bang) * 16
                    line(bx, by, nbx, nby, 0.8)
                    bx, by = nbx, nby
        radials.append(pts)
    for ring in (22, 48, 90, 150):  # concentric links between neighbouring radials
        for k in range(n_rad):
            a, b = radials[k], radials[(k + 1) % n_rad]
            ia = min(len(a) - 1, int(ring / 20))
            ib = min(len(b) - 1, int(ring / 20))
            if rng.random() < 0.75:
                line(a[ia][0], a[ia][1], b[ib][0], b[ib][1], 0.9)
    yy, xx = np.mgrid[0:h, 0:w]
    d = np.sqrt((xx - ix) ** 2 + (yy - iy) ** 2)
    core = np.clip(1 - d / 38, 0, 1) * (rng.random((h, w)) < 0.55)
    cr = np.maximum(blur(cr, 0.6) * 1.4, 0)
    glow = 0.55 + 0.45 * value_noise(h, w, 80, rng)
    out = np.zeros((h, w, 4), np.float32)
    out[..., 0] = np.clip(cr, 0, 1)
    out[..., 1] = core
    out[..., 2] = glow
    out[..., 3] = 1
    return np_image(f"crack_{seed}", out, data=True)


def feed_image():
    """Stand-in for the renderer's sewer feed (dark comment threads), only
    for the game-view preview."""
    W, H = 256, 540
    rng = np.random.default_rng(9)
    img = np.zeros((H, W, 3), np.float32)
    img[:] = mat.rgb("#060d08")
    pal = ["#ff5a4a", "#ffd23f", "#4fd1ff", "#b388ff", "#6bff8f", "#ff7ac8"]
    img[8:30, 12:150] = mat.rgb("#b8f5c6")
    y = 50
    while y < H - 50:
        c = mat.rgb(pal[int(rng.integers(len(pal)))])
        yy, xx = np.ogrid[0:H, 0:W]
        img[((xx - 26) ** 2 + (yy - y - 14) ** 2) < 144] = c
        img[y + 4:y + 12, 46:46 + int(rng.integers(40, 90))] = mat.rgb("#7fa88a")
        img[y + 20:y + 34, 46:46 + int(rng.integers(60, 190))] = mat.rgb("#e8ffe9")
        img[y + 44:y + 52, 46:80] = mat.rgb("#ff5a4a")
        y += 74
    out = np.ones((H, W, 4), np.float32)
    out[..., :3] = to_srgb(img)
    return np_image("feed_preview", out[::-1])


# ------------------------------------------------------------------ node helper (material layering)


class N:
    """Layer procedural detail on top of a Principled material (lib.mat)."""

    def __init__(self, m, period=None):
        self.m, self.nt, self.p = m, m.node_tree, mat.principled(m)
        self._obj = self._xyz = self._geo = None
        self._emit = None
        # Repeated modules (deck rows, tunnel rows) need noise that tiles
        # along Y: `period` maps y onto a circle into 4D noise.
        self.period = period if period is not None else m.get("period")

    def n(self, kind, **props):
        node = self.nt.nodes.new(kind)
        for k, v in props.items():
            setattr(node, k, v)
        return node

    def link(self, a, b):
        self.nt.links.new(a, b)

    def put(self, v, sock):
        if isinstance(v, bpy.types.NodeSocket):
            self.link(v, sock)
        elif sock.type == "RGBA":
            sock.default_value = mat.rgba(v) if (isinstance(v, str) or len(v) == 3) else tuple(v)
        elif sock.type == "VECTOR":
            sock.default_value = tuple(v)
        else:
            sock.default_value = float(v)

    def obj(self):
        if self._obj is None:
            self._obj = self.n("ShaderNodeTexCoord").outputs["Object"]
        return self._obj

    def xyz(self):
        if self._xyz is None:
            s = self.n("ShaderNodeSeparateXYZ")
            self.link(self.obj(), s.inputs[0])
            self._xyz = (s.outputs[0], s.outputs[1], s.outputs[2])
        return self._xyz

    def nrm(self):
        if self._geo is None:
            g = self.n("ShaderNodeNewGeometry")
            s = self.n("ShaderNodeSeparateXYZ")
            self.link(g.outputs["Normal"], s.inputs[0])
            self._geo = (s.outputs[0], s.outputs[1], s.outputs[2])
        return self._geo

    def math(self, op, a, b=None, c=None, clamp=False):
        node = self.n("ShaderNodeMath", operation=op, use_clamp=clamp)
        for i, v in enumerate((a, b, c)):
            if v is not None:
                self.put(v, node.inputs[i])
        return node.outputs[0]

    def mul(self, a, b, clamp=False):
        return self.math("MULTIPLY", a, b, clamp=clamp)

    def add(self, a, b, clamp=False):
        return self.math("ADD", a, b, clamp=clamp)

    def sub(self, a, b, clamp=False):
        return self.math("SUBTRACT", a, b, clamp=clamp)

    def smooth(self, v, lo, hi, a=0.0, b=1.0):
        node = self.n("ShaderNodeMapRange", interpolation_type="SMOOTHSTEP", clamp=True)
        self.put(v, node.inputs["Value"])
        node.inputs["From Min"].default_value = lo
        node.inputs["From Max"].default_value = hi
        node.inputs["To Min"].default_value = a
        node.inputs["To Max"].default_value = b
        return node.outputs["Result"]

    def lin(self, v, lo, hi, a=0.0, b=1.0):
        node = self.n("ShaderNodeMapRange", interpolation_type="LINEAR", clamp=True)
        self.put(v, node.inputs["Value"])
        node.inputs["From Min"].default_value = lo
        node.inputs["From Max"].default_value = hi
        node.inputs["To Min"].default_value = a
        node.inputs["To Max"].default_value = b
        return node.outputs["Result"]

    def vec(self, x, y, z=0.0):
        c = self.n("ShaderNodeCombineXYZ")
        for i, v in enumerate((x, y, z)):
            self.put(v, c.inputs[i])
        return c.outputs[0]

    def mapped(self, vec=None, scale=(1, 1, 1), offset=(0, 0, 0)):
        mp = self.n("ShaderNodeMapping")
        self.link(vec if vec is not None else self.obj(), mp.inputs["Vector"])
        mp.inputs["Scale"].default_value = scale
        mp.inputs["Location"].default_value = offset
        return mp.outputs["Vector"]

    def noise(self, scale=1.0, stretch=(1, 1, 1), detail=3.0, rough=0.55, dist=0.0, offset=(0, 0, 0), vec=None):
        if self.period:
            sx, sy, sz = stretch
            ox, oy, oz = offset
            s = self.n("ShaderNodeSeparateXYZ")
            self.link(vec if vec is not None else self.obj(), s.inputs[0])
            th = self.mul(s.outputs[1], 2 * math.pi / self.period)
            R = self.period / (2 * math.pi) * sy
            v = self.vec(self.add(self.mul(s.outputs[0], sx), ox), self.add(self.mul(self.math("COSINE", th), R), oy),
                         self.add(self.mul(s.outputs[2], sz), oz))
            t = self.n("ShaderNodeTexNoise", noise_dimensions="4D")
            self.link(v, t.inputs["Vector"])
            self.link(self.mul(self.math("SINE", th), R), t.inputs["W"])
        else:
            v = self.mapped(vec, stretch, offset)
            t = self.n("ShaderNodeTexNoise", noise_dimensions="3D")
            self.link(v, t.inputs["Vector"])
        t.inputs["Scale"].default_value = scale
        t.inputs["Detail"].default_value = detail
        t.inputs["Roughness"].default_value = rough
        t.inputs["Distortion"].default_value = dist
        return t.outputs["Fac"]

    def voronoi(self, scale=1.0, stretch=(1, 1, 1), feature="F1", vec=None, out="Distance"):
        v = self.mapped(vec, stretch)
        t = self.n("ShaderNodeTexVoronoi", voronoi_dimensions="3D", feature=feature)
        self.link(v, t.inputs["Vector"])
        t.inputs["Scale"].default_value = scale
        return t.outputs[out]

    def mixc(self, a, b, fac):
        node = self.n("ShaderNodeMix", data_type="RGBA", blend_type="MIX", clamp_factor=True)
        self.put(fac, node.inputs[0])
        for sock, v in ((node.inputs[6], a), (node.inputs[7], b)):
            if isinstance(v, bpy.types.NodeSocket):
                self.link(v, sock)
            else:
                sock.default_value = mat.rgba(v) if (isinstance(v, str) or len(v) == 3) else tuple(v)
        return node.outputs[2]

    def mulc(self, a, b, fac=1.0):
        node = self.n("ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY", clamp_factor=True)
        self.put(fac, node.inputs[0])
        for sock, v in ((node.inputs[6], a), (node.inputs[7], b)):
            if isinstance(v, bpy.types.NodeSocket):
                self.link(v, sock)
            else:
                sock.default_value = mat.rgba(v) if (isinstance(v, str) or len(v) == 3) else tuple(v)
        return node.outputs[2]

    def mixf(self, a, b, fac):
        node = self.n("ShaderNodeMix", data_type="FLOAT", clamp_factor=True)
        self.put(fac, node.inputs[0])
        self.put(a, node.inputs[2])
        self.put(b, node.inputs[3])
        return node.outputs[0]

    def src(self, name):
        sock = self.p.inputs[name]
        if sock.is_linked:
            return sock.links[0].from_socket
        v = sock.default_value
        return tuple(v) if hasattr(v, "__len__") else v

    def set(self, name, v):
        sock = self.p.inputs[name]
        for l in list(sock.links):
            self.nt.links.remove(l)
        self.put(v, sock)

    def image(self, img, vec, ext="REPEAT"):
        t = self.n("ShaderNodeTexImage", extension=ext, interpolation="Linear")
        t.image = img
        self.link(vec, t.inputs["Vector"])
        return t

    def emit(self, colour, strength):
        """Add colour * strength (sockets or values) to the emission."""
        e = self.n("ShaderNodeVectorMath", operation="SCALE")
        self.put(colour if isinstance(colour, bpy.types.NodeSocket) else tuple(mat.rgb(colour)), e.inputs[0])
        self.put(strength, e.inputs["Scale"])
        out = e.outputs[0]
        if self._emit is not None:
            s = self.n("ShaderNodeVectorMath", operation="ADD")
            self.link(self._emit, s.inputs[0])
            self.link(out, s.inputs[1])
            out = s.outputs[0]
        self._emit = out
        self.link(out, self.p.inputs["Emission Color"])
        self.p.inputs["Emission Strength"].default_value = 1.0


def grime(m, splash=1.3, depth=-1.5, streaks=0.7, algae=0.6, salts=0.25, waterline=None, streak_scale=1.0,
          wet_top=None, period=None):
    """Sewer wear in object space: vertical drip streaks, a wet/algae splash
    zone near the channel, darker and slimier below `depth`, salt blooms,
    an optional old flood line at z=waterline."""
    k = N(m, period)
    x, y, z = k.xyz()
    col, rough = k.src("Base Color"), k.src("Roughness")
    s = k.noise(scale=1.3 * streak_scale, stretch=(6, 6, 0.22), detail=5, rough=0.6, offset=(3.1, 1.7, 0))
    streak = k.mul(k.smooth(s, 0.5, 0.75), streaks)
    col = k.mixc(col, "#14140c", k.mul(streak, 0.75))
    rough = k.mixf(rough, 0.16, k.mul(streak, 0.8))
    if salts > 0:
        sn = k.noise(scale=0.7, stretch=(1, 1, 1.6), detail=4, offset=(9, 2, 5))
        salt = k.mul(k.smooth(sn, 0.58, 0.72), salts)
        col = k.mixc(col, "#9a9c8e", salt)
    splash_m = k.smooth(z, splash, splash - 1.2)
    an = k.noise(scale=2.2, detail=6, rough=0.65, offset=(0.3, 4, 1))
    alg = k.mul(splash_m, k.smooth(an, 0.35, 0.6, 0.35, 1.0))
    col = k.mixc(col, "#1e2a0c", k.mul(alg, algae))
    col = k.mixc(col, "#2f4410", k.mul(k.mul(alg, k.smooth(an, 0.55, 0.7)), algae * 0.8))
    rough = k.mixf(rough, 0.12, k.mul(splash_m, 0.7))
    deep = k.smooth(z, depth, depth - 6.0)
    col = k.mixc(col, "#070a05", k.mul(deep, 0.8))
    if waterline is not None:
        band = k.mul(k.smooth(z, waterline - 0.25, waterline), k.smooth(z, waterline + 0.06, waterline))
        col = k.mixc(col, "#3a3316", k.mul(band, 0.7))
    if wet_top is not None:  # puddle gloss on upward faces
        _, _, nz = k.nrm()
        up = k.smooth(nz, 0.7, 0.95)
        pud = k.smooth(k.noise(scale=0.45, detail=3, offset=(2, 8, 0)), 0.52, 0.58)
        wet = k.mul(up, k.mul(pud, wet_top))
        col = k.mulc(col, "#5a5a5a", wet)
        rough = k.mixf(rough, 0.04, wet)
    k.set("Base Color", col)
    k.set("Roughness", rough)
    return k


def graffiti(k, img, y_left, y_right, z0, z1, rough=0.42, emit=0.0, wear=0.3, facing=-0.3):
    """Project a spray image onto faces facing -X, u from y_left to
    y_right, v from z0 to z1 (object space)."""
    x, y, z = k.xyz()
    u = k.math("DIVIDE", k.sub(y_left, y), y_left - y_right)
    v = k.math("DIVIDE", k.sub(z, z0), z1 - z0)
    t = k.image(img, k.vec(u, v), ext="CLIP")
    nx, _, _ = k.nrm()
    face = k.smooth(nx, facing + 0.2, facing - 0.2)
    wn = k.noise(scale=3.0, detail=5, offset=(7, 3, 1))
    worn = k.smooth(wn, 0.3 * wear, 0.3 * wear + 0.25)
    a = k.mul(k.mul(t.outputs["Alpha"], face), worn)
    k.set("Base Color", k.mixc(k.src("Base Color"), t.outputs["Color"], a))
    k.set("Roughness", k.mixf(k.src("Roughness"), rough, a))
    if emit:
        k.emit(t.outputs["Color"], k.mul(a, emit))
    return k


def halo(k, pos, radius, colour, strength):
    """Light spill of a fitting at `pos` (object space), baked as emission.
    In a periodic material the neighbouring modules' fittings add theirs."""
    shifts = (0.0, -k.period, k.period) if k.period else (0.0,)
    lit = k.mulc(k.src("Base Color"), colour, 1.0)  # spill = albedo x lamp colour
    for dy in shifts:
        d = k.n("ShaderNodeVectorMath", operation="DISTANCE")
        k.link(k.obj(), d.inputs[0])
        d.inputs[1].default_value = (pos[0], pos[1] + dy, pos[2])
        f = k.lin(d.outputs["Value"], 0.0, radius, 1.0, 0.0)
        k.emit(lit, k.mul(k.math("POWER", f, 2.0), strength * 2.6))
    return k


# ------------------------------------------------------------------ materials

MATS = {}
PERIOD = ROW  # deck and tunnel rows repeat every 4.4 m: their textures tile at it


def build_materials():
    M = MATS
    # Box scales on repeated modules divide 4.4 m so rows join seamlessly.
    M["concrete"] = mat.pbr("Concrete", "Concrete044D", mapping="BOX", box_scale=2.2, wet=0.45, value=0.7,
                            saturation=0.55, normal_strength=0.0, bump=0.35, bump_distance=0.02)
    grime(M["concrete"], splash=0.5, depth=-2.0, streaks=0.6, algae=0.5, salts=0.2, wet_top=0.9)
    M["concrete_row"] = mat.pbr("ConcreteRow", "Concrete044D", mapping="BOX", box_scale=2.2, wet=0.45, value=0.62,
                                saturation=0.5, normal_strength=0.0, bump=0.35, bump_distance=0.02)
    grime(M["concrete_row"], splash=0.4, depth=-1.0, streaks=0.7, algae=0.5, salts=0.2, period=PERIOD)
    M["concrete_rib"] = mat.pbr("ConcreteRib", "Concrete044D", mapping="BOX", box_scale=1.1, wet=0.3, value=0.6,
                                saturation=0.5, normal_strength=0.0, bump=0.45, bump_distance=0.02)
    grime(M["concrete_rib"], splash=1.4, depth=-1.0, streaks=0.9, algae=0.5, salts=0.35, period=PERIOD)
    M["steel"] = mat.pbr("Steel", "Metal027", mapping="BOX", box_scale=1.1, value=0.7, roughness_scale=0.9)
    rust_over(M["steel"], 0.45)
    M["steel_row"] = mat.pbr("SteelRow", "Metal027", mapping="BOX", box_scale=1.1, value=0.7, roughness_scale=0.9)
    rust_over(M["steel_row"], 0.45, period=PERIOD)
    M["rust"] = mat.pbr("Rust", "PaintedMetal006", mapping="BOX", box_scale=0.55, value=0.5, saturation=0.6)
    k = N(M["rust"])
    k.set("Base Color", k.mixc(k.src("Base Color"), "#3b1c0c", 0.75))
    k.set("Roughness", 0.75)
    k.set("Metallic", 0.35)
    M["pipe"] = pipe_paint("PipePaint", tiling=(1 / 1.1, 1 / 1.1))
    M["pipe_row"] = pipe_paint("PipePaintRow", tiling=(1 / 1.1, 1 / 1.1), period=PERIOD)
    M["cage"] = mat.pbr("Cage", "Metal027", mapping="BOX", box_scale=0.55, value=0.45)
    rust_over(M["cage"], 0.3)
    M["dark"] = mat.flat("Hollow", "#040504", rough=0.9)
    M["bed"] = mat.flat("ScreenBed", "#070808", rough=0.8)
    M["plastic_blk"] = mat.pbr("PhoneBody", "Plastic010", mapping="BOX", box_scale=0.6, tint="#1b1d21",
                               roughness_scale=0.8)
    grime(M["plastic_blk"], splash=0.3, depth=-1.0, streaks=0.5, algae=0.8, salts=0.0)
    M["phone_frame"] = mat.pbr("PhoneFrame", "Metal009", mapping="BOX", box_scale=0.6, value=0.55)
    M["downvote"] = mat.pbr("Downvote", "Plastic010", mapping="BOX", box_scale=0.8, tint="#9a2a22",
                            roughness_scale=0.6, saturation=0.8)
    grime(M["downvote"], splash=0.9, depth=-0.5, streaks=0.5, algae=1.0, salts=0.0)
    M["cable"] = mat.pbr("Cable", "Plastic010", mapping="BOX", box_scale=0.5, tint="#d6d6d0", roughness_scale=0.7)
    grime(M["cable"], splash=0.2, depth=-1.0, streaks=0.3, algae=0.9, salts=0.0)
    M["hazard"] = hazard_paint()
    M["warn"] = mat.flat("WarnStrip", "#ff2a1a", rough=0.4, emission="#ff3322", strength=5.0)
    M["beacon"] = mat.flat("Beacon", "#ffb020", rough=0.3, emission="#ffaa22", strength=4.0)
    M["gauge"] = mat.flat("Gauge", "#c8c4b0", rough=0.3)
    M["valve"] = mat.pbr("ValveRed", "PaintedMetal006", mapping="BOX", box_scale=0.4, tint="#8a1a12", value=0.9,
                         saturation=0.2)
    rust_over(M["valve"], 0.35)
    M["deck"] = deck_material()
    M["rail_pipe"] = rail_material()
    # kept out of the atlas: the runtime seam + two extra materials
    M["seam"] = mat.flat("Seam", "#5aff5a", rough=0.4, emission=LOOK["seam"], strength=1.0)
    M["sludge"] = mat.flat("Sludge", "#0c2807", rough=0.05, metal=0.0, emission="#3cff2e", strength=0.25)
    M["light"] = mat.flat("SewerLight", "#e6fff0", rough=0.3, emission="#c8ffd6", strength=7.0)
    return M


KEEP = ("Seam", "Sludge", "SewerLight")


def pipe_paint(name, tiling, period=None):
    m = mat.pbr(name, "PaintedMetal006", tiling=tiling, value=0.42, saturation=0.5, roughness_scale=1.0, uv_map="UVMap")
    m["period"] = period or 0
    grime(m, splash=0.4, depth=-2.0, streaks=0.8, algae=0.3, salts=0.0, streak_scale=1.4, period=period)
    return m


def rust_over(m, amount, period=None):
    k = N(m, period)
    r = k.noise(scale=1.6, detail=6, rough=0.7, offset=(5, 5, 5))
    s = k.noise(scale=1.0, stretch=(5, 5, 0.3), detail=4, offset=(1, 9, 2))
    f = k.mul(k.add(k.smooth(r, 0.55, 0.7), k.mul(k.smooth(s, 0.6, 0.75), 0.6), clamp=True), amount)
    k.set("Base Color", k.mixc(k.src("Base Color"), "#3e1d0b", f))
    k.set("Roughness", k.mixf(k.src("Roughness"), 0.85, f))
    k.set("Metallic", k.mixf(k.src("Metallic"), 0.25, f))


def hazard_paint():
    m = mat.pbr("Hazard", "PaintedMetal006", mapping="BOX", box_scale=0.5, value=0.6)
    k = N(m)
    x, y, z = k.xyz()
    st = k.math("FRACT", k.math("DIVIDE", k.add(x, z), 0.55))
    band = k.smooth(st, 0.47, 0.53)
    stripe = k.mixc("#c9a012", "#101010", band)
    wn = k.noise(scale=2.5, detail=6, offset=(2, 2, 2))
    chip = k.smooth(wn, 0.62, 0.7)
    k.set("Base Color", k.mixc(stripe, k.src("Base Color"), chip))
    k.set("Roughness", k.mixf(0.55, 0.8, chip))
    k.set("Metallic", k.mixf(0.0, 0.4, chip))
    return m


def brick_material(name, graffitis=(), halos=(), value=0.5, splash=0.8, waterline=None, box=(3.2, 3.2, 1.6),
                   depth=-2.0, streaks=0.85):
    m = mat.pbr(name, "Bricks097", mapping="BOX", box_scale=box, wet=0.45, value=value, saturation=0.62,
                normal_strength=0.0, bump=0.8, bump_distance=0.03, roughness_scale=0.9)
    k = grime(m, splash=splash, depth=depth, streaks=streaks, algae=0.7, salts=0.35, waterline=waterline)
    for g in graffitis:
        graffiti(k, *g)
    for h in halos:
        halo(k, *h)
    return m


def tunnel_brick():
    """UV-mapped brick for the tube: courses along Y (u, metres), stacked
    round the arch (v, metres of arc). One brick tile = 2.2 x 1.1 m, so the
    pattern repeats exactly every row."""
    m = mat.pbr("TunnelBrick", "Bricks097", tiling=(1 / 2.2, 1 / 1.1), wet=0.5, value=0.56, saturation=0.62, uv_map="UVMap",
                normal_strength=1.5, roughness_scale=0.9)
    k = N(m, PERIOD)
    uvn = k.n("ShaderNodeUVMap", uv_map="UVMap").outputs["UV"]
    sep = k.n("ShaderNodeSeparateXYZ")
    k.link(uvn, sep.inputs[0])
    u, v = sep.outputs[0], sep.outputs[1]  # u = y metres, v = arc metres
    x, y, z = k.xyz()
    col, rough = k.src("Base Color"), k.src("Roughness")
    # drip streaks running round the arch and down the walls (periodic in u)
    s = k.noise(scale=1.0, vec=k.vec(v, u, 0.0), stretch=(0.18, 3.5, 1.0), detail=5, rough=0.6)
    streak = k.smooth(s, 0.5, 0.74)
    col = k.mixc(col, "#10110a", k.mul(streak, 0.7))
    rough = k.mixf(rough, 0.14, k.mul(streak, 0.85))
    sn = k.noise(scale=0.6, detail=4, offset=(9, 2, 5))
    col = k.mixc(col, "#8e917f", k.mul(k.smooth(sn, 0.6, 0.72), 0.35))
    splash = k.smooth(z, 1.9, 0.2)
    an = k.noise(scale=2.0, detail=6, rough=0.65, offset=(0.3, 4, 1))
    alg = k.mul(splash, k.smooth(an, 0.3, 0.6, 0.4, 1.0))
    col = k.mixc(col, "#1c290b", k.mul(alg, 0.8))
    col = k.mixc(col, "#34500f", k.mul(k.mul(alg, k.smooth(an, 0.56, 0.7)), 0.7))
    band = k.mul(k.smooth(z, 2.35, 2.6), k.smooth(z, 2.72, 2.6))  # old flood line
    col = k.mixc(col, "#3b3417", k.mul(band, 0.75))
    col = k.mixc(col, "#060805", k.smooth(z, -0.5, -2.5))
    rough = k.mixf(rough, 0.1, k.mul(splash, 0.7))
    k.set("Base Color", col)
    k.set("Roughness", rough)
    return m, k


# ------------------------------------------------------------------ geometry builder


class Geo:
    """bmesh builder: faces with per-loop UVs and materials; one object.
    Two UV layers: "UVMap" (what materials sample, metres) and "Unwrap"
    (render-active: the islands the atlas packs; defaults to UVMap, faces
    without one get a planar projection)."""

    def __init__(self):
        self.bm = bmesh.new()
        self.uv = self.bm.loops.layers.uv.new("UVMap")
        self.uw = self.bm.loops.layers.uv.new("Unwrap")
        self.mats = []

    def mi(self, m):
        if m not in self.mats:
            self.mats.append(m)
        return self.mats.index(m)

    def face(self, pts, m, uvs=None, uws=None):
        vs = [self.bm.verts.new(Vector(p)) for p in pts]
        f = self.bm.faces.new(vs)
        f.material_index = self.mi(m)
        if uvs is not None:
            for loop, t in zip(f.loops, uvs):
                loop[self.uv].uv = t
        w = uws if uws is not None else uvs
        if w is not None:
            for loop, t in zip(f.loops, w):
                loop[self.uw].uv = t
        return f

    def face_out(self, pts, m, want, uvs=None, uws=None):
        """face() oriented so its normal points along `want`."""
        f = self.face(pts, m, uvs, uws)
        f.normal_update()
        if f.normal.dot(Vector(want)) < 0:
            f.normal_flip()
        return f

    def grid(self, rows, m, uvs=None, close=False, flip=False):
        """Quads between consecutive point rows (rows[j][i]); uvs alike.
        Normal = (row direction) x (next row) as in sweep()."""
        for j in range(len(rows) - 1):
            a, b = rows[j], rows[j + 1]
            n = len(a)
            for i in range(n if close else n - 1):
                i2 = (i + 1) % n
                q = [a[i], a[i2], b[i2], b[i]]
                t = None if uvs is None else [uvs[j][i], uvs[j][i2 if not (close and i2 == 0) else n], uvs[j + 1][i2 if not (close and i2 == 0) else n], uvs[j + 1][i]]
                if flip:
                    q, t = q[::-1], (t[::-1] if t else None)
                self.face(q, m, t)

    def sweep(self, prof, ys, m, u_len=1.0, v_len=1.0, close=False, flip=False, v0=0.0, uw_off=None):
        """Extrude an XZ profile along Y through stations ys. u = y/u_len,
        v = arc/v_len. Profile order sets the side: normal = (-dz, 0, dx)."""
        pts = list(prof) + ([prof[0]] if close else [])
        arc = [0.0]
        for a, b in zip(pts, pts[1:]):
            arc.append(arc[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
        rows = [[(p[0], y, p[1]) for p in pts] for y in ys]
        uvs = [[(y / u_len, (v0 + s) / v_len) for s in arc] for y in ys]
        if uw_off is None:
            self.grid(rows, m, uvs, close=False, flip=flip)
        else:  # own atlas island (the unwrap is offset, the texturing UVs stay continuous)
            start = len(self.bm.faces)
            self.grid(rows, m, uvs, close=False, flip=flip)
            self.bm.faces.ensure_lookup_table()
            for f in list(self.bm.faces)[start:]:
                for l in f.loops:
                    l[self.uw].uv = l[self.uw].uv + Vector(uw_off)

    def tube(self, path, r, sides, m, caps=(False, False), u_len=1.0, arc=None, radii=None, up=(0, 0, 1),
             phase=0.0, v_len=None, flip=False, hole=None):
        """Tube along a polyline (parallel-transport frames). arc=(a0, a1)
        radians for a partial tube. u along the path (metres/u_len), v round."""
        P = [Vector(p) for p in path]
        n = len(P)
        T = []
        for i in range(n):
            if i == 0:
                t = P[1] - P[0]
            elif i == n - 1:
                t = P[-1] - P[-2]
            else:
                t = (P[i + 1] - P[i]).normalized() + (P[i] - P[i - 1]).normalized()
            T.append(t.normalized())
        ref = Vector(up)
        if abs(ref.dot(T[0])) > 0.9:
            ref = Vector((1, 0, 0)) if abs(T[0].x) < 0.9 else Vector((0, 1, 0))
        Nv = (ref - T[0] * ref.dot(T[0])).normalized()
        frames = []
        for i in range(n):
            if i > 0:
                Nv = (Nv - T[i] * Nv.dot(T[i])).normalized()
            B = T[i].cross(Nv)
            frames.append((Nv.copy(), B))
        full = arc is None
        a0, a1 = (0.0, 2 * math.pi) if full else arc
        k = sides if full else sides + 1
        angs = [a0 + (a1 - a0) * j / sides + phase for j in range(k)]
        dist = [0.0]
        for i in range(1, n):
            dist.append(dist[-1] + (P[i] - P[i - 1]).length)
        rows, uvs = [], []
        vl = v_len or 1.0  # metres round the tube
        for i in range(n):
            rr = radii[i] if radii else r
            Nf, B = frames[i]
            rows.append([P[i] + rr * (math.cos(a) * Nf + math.sin(a) * B) for a in angs])
            uvs.append([(dist[i] / u_len, (a - a0) * r / vl) for a in angs] + ([(dist[i] / u_len, (a1 - a0) * r / vl)] if full else []))
        # rows along the ring, next row along the path: (ring dir) x (path) = outward
        self.grid(rows, m, uvs, close=full, flip=flip)
        if full and hole:  # annulus caps (flanges round a pipe): no hidden disc
            for end, ring in ((0, rows[0]), (1, rows[-1])):
                if not caps[end]:
                    continue
                Nf, B = frames[0 if end == 0 else -1]
                inner = [P[0 if end == 0 else -1] + hole * (math.cos(a) * Nf + math.sin(a) * B) for a in angs]
                for j in range(len(ring)):
                    j2 = (j + 1) % len(ring)
                    q = [ring[j], ring[j2], inner[j2], inner[j]]
                    uvq = [(math.cos(angs[j]) * 0.5 + 0.5, math.sin(angs[j]) * 0.5 + 0.5),
                           (math.cos(angs[j2]) * 0.5 + 0.5, math.sin(angs[j2]) * 0.5 + 0.5),
                           (math.cos(angs[j2]) * 0.3 + 0.5, math.sin(angs[j2]) * 0.3 + 0.5),
                           (math.cos(angs[j]) * 0.3 + 0.5, math.sin(angs[j]) * 0.3 + 0.5)]
                    f = self.face(q if end == 1 else q[::-1], m, uvq if end == 1 else uvq[::-1])
        elif full:
            if caps[0]:
                self.face(rows[0][::-1], m, [(0.5 + 0.5 * math.cos(a), 0.5 + 0.5 * math.sin(a)) for a in angs[::-1]])
            if caps[1]:
                self.face(rows[-1], m, [(0.5 + 0.5 * math.cos(a), 0.5 + 0.5 * math.sin(a)) for a in angs])
        return rows

    def box(self, lo, hi, m, skip=(), ys=None, uv_size=1.0):
        """Axis-aligned box from lo to hi, cut along Y at ys (stations),
        faces named +x -x +y -y +z -z (skip some)."""
        x0, y0, z0 = lo
        x1, y1, z1 = hi
        ys = ys or [y0, y1]
        s = uv_size
        for a, b in zip(ys, ys[1:]):
            if "+z" not in skip:
                self.face([(x0, a, z1), (x1, a, z1), (x1, b, z1), (x0, b, z1)], m, [(x0 / s, a / s), (x1 / s, a / s), (x1 / s, b / s), (x0 / s, b / s)])
            if "-z" not in skip:
                self.face([(x0, b, z0), (x1, b, z0), (x1, a, z0), (x0, a, z0)], m, [(x0 / s, b / s), (x1 / s, b / s), (x1 / s, a / s), (x0 / s, a / s)])
            if "+x" not in skip:
                self.face([(x1, a, z0), (x1, b, z0), (x1, b, z1), (x1, a, z1)], m, [(a / s, z0 / s), (b / s, z0 / s), (b / s, z1 / s), (a / s, z1 / s)])
            if "-x" not in skip:
                self.face([(x0, b, z0), (x0, a, z0), (x0, a, z1), (x0, b, z1)], m, [(-b / s, z0 / s), (-a / s, z0 / s), (-a / s, z1 / s), (-b / s, z1 / s)])
        if "-y" not in skip:
            self.face([(x1, y0, z0), (x0, y0, z0), (x0, y0, z1), (x1, y0, z1)], m, [(-x1 / s, z0 / s), (-x0 / s, z0 / s), (-x0 / s, z1 / s), (-x1 / s, z1 / s)])
        if "+y" not in skip:
            self.face([(x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)], m, [(x0 / s, z0 / s), (x1 / s, z0 / s), (x1 / s, z1 / s), (x0 / s, z1 / s)])

    def transform(self, mtx, start_vert=0):
        for v in list(self.bm.verts)[start_vert:]:
            v.co = mtx @ v.co

    def nverts(self):
        return len(self.bm.verts)

    def fix_unwrap(self):
        """Faces with a degenerate unwrap get a planar one (their own island)."""
        uw = self.uw
        for f in self.bm.faces:
            pts = [l[uw].uv for l in f.loops]
            a = 0.0
            for i in range(len(pts)):
                a += pts[i].x * pts[(i + 1) % len(pts)].y - pts[(i + 1) % len(pts)].x * pts[i].y
            if abs(a) / 2 > 1e-7 * max(f.calc_area(), 1e-6) and abs(a) > 1e-9:
                continue
            f.normal_update()
            n = f.normal
            t = (f.loops[1].vert.co - f.loops[0].vert.co)
            t = (t - n * t.dot(n)).normalized() if t.length > 1e-9 else n.orthogonal().normalized()
            b = n.cross(t)
            c = f.loops[0].vert.co
            for l in f.loops:
                d = l.vert.co - c
                l[uw].uv = (d.dot(t), d.dot(b))

    def obj(self, name, smooth_angle=None, merge=True):
        self.fix_unwrap()
        if merge:
            bmesh.ops.remove_doubles(self.bm, verts=self.bm.verts, dist=1e-5)
        me = bpy.data.meshes.new(name)
        self.bm.to_mesh(me)
        self.bm.free()
        for m in self.mats:
            me.materials.append(m)
        me.uv_layers["Unwrap"].active_render = True
        me.uv_layers.active = me.uv_layers["Unwrap"]
        o = lib.link(bpy.data.objects.new(name, me))
        if smooth_angle is not None:
            mesh.smooth(o, smooth_angle)
        return o


def part(name, build, smooth=None, merge=True):
    g = Geo()
    build(g)
    return g.obj(name, smooth, merge)


def bolt(g, center, normal, r, m, h=None, sides=6):
    """A hex bolt head on a surface (centre, outward normal)."""
    c, nv = Vector(center), Vector(normal).normalized()
    h = h or r * 0.7
    g.tube([c - nv * 0.002, c + nv * h], r, sides, m, caps=(False, True), phase=0.3, up=(0.3, 0.5, 0.8))


def rot(axis, deg):
    return Matrix.Rotation(math.radians(deg), 4, axis)


def xform(o, mtx):
    o.data.transform(mtx)
    o.data.update()
    return o


def finish(objs, name, max_y=None):
    """Join parts into one node object (transform baked, origin at 0)."""
    objs = [o for o in objs if o is not None]
    for o in objs:
        mesh.apply_transform(o)
    node = mesh.join(objs, name=name)
    mesh.apply_transform(node)
    return node


def cut_y(o, max_len, extra=()):
    lo, hi = mesh.bounds(o)
    if hi.y - lo.y > max_len:
        mesh.subdivide_along(o, "Y", positions=stations(lo.y, hi.y, max_len, extra)[1:-1])
    return o


# ------------------------------------------------------------------ deck + seam


def build_deck():
    """One 4.4 m row: wet concrete channel framing the three lane screens,
    joint and gutter grates, raised kerbs, a concrete keel below."""
    M = MATS
    ys = stations(-SCREEN_L / 2, SCREEN_L / 2, 0.5)
    ys_all = [-ROW / 2] + ys + [ROW / 2]
    hs = SCREEN_W / 2
    edges = [(-LANE - hs, -LANE + hs), (-hs, hs), (LANE - hs, LANE + hs)]
    bed = -0.03
    left = [(-4.8, 0.30), (-4.29, 0.30), (-4.25, -0.05), (-3.66, -0.05), (-3.62, 0.0)]
    right = [(-x, z) for x, z in reversed(left)]
    mid = []
    for a, b in edges:
        mid += [(a, 0.0), (a, bed), (b, bed), (b, 0.0)]
    prof = left + mid + right
    prof_end = left + [(v, 0.0) for e in edges for v in e] + right

    def arcs(pr):
        out = [0.0]
        for (xa, za), (xb, zb) in zip(pr, pr[1:]):
            out.append(out[-1] + math.hypot(xb - xa, zb - za))
        return out
    top, beds = Geo(), Geo()
    ar = arcs(prof)
    for ya, yb in zip(ys, ys[1:]):
        for i, ((xa, za), (xb, zb)) in enumerate(zip(prof, prof[1:])):
            q = [(xa, ya, za), (xb, ya, zb), (xb, yb, zb), (xa, yb, za)]
            t = [(ar[i], ya), (ar[i + 1], ya), (ar[i + 1], yb), (ar[i], yb)]
            if abs(za - bed) < 1e-6 and abs(zb - bed) < 1e-6:
                beds.face(q, M["bed"], t)
            else:
                top.face(q, M["deck"], t)
    ae = arcs(prof_end)
    for ya, yb in ((-ROW / 2, ys[0]), (ys[-1], ROW / 2)):
        for i, ((xa, za), (xb, zb)) in enumerate(zip(prof_end, prof_end[1:])):
            top.face([(xa, ya, za), (xb, ya, zb), (xb, yb, zb), (xa, yb, za)], M["deck"],
                     [(ae[i], ya), (ae[i + 1], ya), (ae[i + 1], yb), (ae[i], yb)],
                     [(ae[i] + 50, ya), (ae[i + 1] + 50, ya), (ae[i + 1] + 50, yb), (ae[i] + 50, yb)])
    for a, b in edges:  # bed end walls under the screens' ends
        top.face([(a, ys[0], 0.0), (b, ys[0], 0.0), (b, ys[0], bed), (a, ys[0], bed)], M["deck"])
        top.face([(b, ys[-1], 0.0), (a, ys[-1], 0.0), (a, ys[-1], bed), (b, ys[-1], bed)], M["deck"])
    o_top = top.obj("deck_top", smooth_angle=30)
    o_top["atlas_weight"] = 3.0
    o_beds = beds.obj("deck_beds", smooth_angle=30)
    o_beds["atlas_weight"] = 0.02

    g = Geo()
    under = [(4.8, 0.30), (4.8, -0.55), (3.5, -1.25), (-3.5, -1.25), (-4.8, -0.55), (-4.8, 0.30)]
    g.sweep(under, ys_all, M["concrete_row"])
    cap = [(4.8, 0.30), (4.29, 0.30), (4.25, -0.05), (3.66, -0.05), (3.62, 0.0), (-3.62, 0.0), (-3.66, -0.05),
           (-4.25, -0.05), (-4.29, 0.30), (-4.8, 0.30), (-4.8, -0.55), (-3.5, -1.25), (3.5, -1.25), (4.8, -0.55)]
    g.face([(x, -ROW / 2, z) for x, z in cap], M["concrete_row"])
    g.face([(x, ROW / 2, z) for x, z in cap], M["concrete_row"])
    o_under = g.obj("deck_under", smooth_angle=30)
    fix_normals_outward(o_under, (0, 0, -0.3))
    o_under["atlas_weight"] = 0.35

    g = Geo()
    for cx in (-LANE, 0.0, LANE):
        for sx in (-1, 1):
            for sy in (-1, 1):
                bolt(g, (cx + sx * (hs + 0.03), sy * (SCREEN_L / 2 + 0.03), 0.0), (0, 0, 1), 0.022, M["rust"], h=0.012)
    for sx in (-1, 1):
        for y in (-1.65, -0.55, 0.55, 1.65):
            bolt(g, (sx * 4.31, y, 0.30), (0, 0, 1), 0.03, M["rust"], h=0.018)
    o_bolts = g.obj("deck_bolts", smooth_angle=35)
    o_bolts["atlas_weight"] = 1.5
    return [o_top, o_beds, o_under, o_bolts]


def fix_normals_outward(o, inside, axis=None):
    """Flip faces whose normal points toward `inside` (a point; with axis
    "x"/"y"/"z" the nearest point on that line through it)."""
    c = Vector(inside)
    for p in o.data.polygons:
        ref = c.copy()
        if axis:
            i = "xyz".index(axis)
            ref[i] = p.center[i]
        if (p.center - ref).dot(p.normal) < 0:
            p.flip()
    o.data.update()


def build_seam():
    g = Geo()
    ys = [-ROW / 2] + stations(-SCREEN_L / 2, SCREEN_L / 2, 0.5) + [ROW / 2]
    w, h = 0.03, 0.016
    for sx in (-3.3, -1.1, 1.1, 3.3):
        g.sweep([(sx - w, 0.0), (sx - w, h), (sx + w, h), (sx + w, 0.0)], ys, MATS["seam"])
    return g.obj("deck_seam", smooth_angle=30)


def deck_material():
    """Procedural deck surface (baked): wet concrete with puddles, steel
    bezels and seam channels, joint and gutter grates glowing from below,
    worn kerb paint. Everything tiles every 4.4 m."""
    m = mat.pbr("Deck", "Concrete044D", mapping="BOX", box_scale=2.2, wet=0.5, value=0.62, saturation=0.5,
                normal_strength=0.0, bump=0.3, bump_distance=0.015)
    k = N(m, PERIOD)
    x, y, z = k.xyz()
    u = k.math("DIVIDE", k.add(x, 4.8), 9.6)
    v = k.math("DIVIDE", k.add(y, 2.2), 4.4)
    t = k.image(DECK_MASK, k.vec(u, v), ext="EXTEND")
    sep = k.n("ShaderNodeSeparateColor")
    k.link(t.outputs["Color"], sep.inputs[0])
    steel, bars, area = sep.outputs[0], sep.outputs[1], sep.outputs[2]
    paint = t.outputs["Alpha"]
    _, _, nz = k.nrm()
    up = k.smooth(nz, 0.3, 0.6)
    col, rough = k.src("Base Color"), k.src("Roughness")
    asph = mat.find_maps("Asphalt025C")
    ar = k.image(mat.image(asph["roughness"], True), k.mapped(None, (1 / 2.2, 1 / 2.2, 1 / 2.2)))
    ar.projection = "BOX"
    pud = k.mul(k.smooth(ar.outputs["Color"], 0.52, 0.42), up)
    col = k.mulc(col, "#4a4a48", pud)
    rough = k.mixf(rough, 0.03, pud)
    gn = k.noise(scale=1.4, stretch=(1, 3, 1), detail=5, offset=(4, 1, 0))
    col = k.mixc(col, "#171a0f", k.mul(k.smooth(gn, 0.55, 0.7), 0.7))
    # kerb foot and gutter edges collect slime
    ax = k.math("ABSOLUTE", x)
    foot = k.mul(k.smooth(ax, 3.9, 4.24), k.smooth(ax, 4.33, 4.27))
    col = k.mixc(col, "#1d2a0b", k.mul(foot, 0.7))
    sn = k.noise(scale=18.0, detail=4, offset=(1, 2, 3))
    steel_col = k.mixc("#15171a", "#2d2f31", k.smooth(sn, 0.45, 0.7))
    rn = k.noise(scale=3.0, detail=6, offset=(8, 8, 8))
    steel_col = k.mixc(steel_col, "#3a1a0a", k.mul(k.smooth(rn, 0.6, 0.72), 0.8))
    col = k.mixc(col, steel_col, steel)
    rough = k.mixf(rough, k.mixf(0.38, 0.8, k.smooth(rn, 0.6, 0.72)), steel)
    metal = k.mixf(0.0, 0.7, steel)
    garea = k.mul(k.smooth(area, 0.2, 0.4), up)
    gutter = k.smooth(area, 0.75, 0.9)
    bar_col = k.mixc("#2a2522", "#4a2410", k.smooth(rn, 0.45, 0.65))
    hole = k.mul(garea, k.sub(1.0, bars, clamp=True))
    col = k.mixc(col, bar_col, k.mul(garea, bars))
    col = k.mixc(col, "#020402", hole)
    rough = k.mixf(rough, 0.7, k.mul(garea, bars))
    metal = k.mixf(metal, 0.6, k.mul(garea, bars))
    gl = k.noise(scale=0.6, detail=2, offset=(3, 3, 3))
    k.emit("#4dff3a", k.mul(k.mul(hole, gutter), k.lin(gl, 0.3, 0.7, 0.04, 0.22)))
    col = k.mixc(col, "#a88a1c", k.mul(paint, up))
    rough = k.mixf(rough, 0.5, k.mul(paint, up))
    k.set("Base Color", col)
    k.set("Roughness", rough)
    k.set("Metallic", metal)
    return m


# ------------------------------------------------------------------ tunnel (hero)

T_WALL = 6.3      # inner wall x
T_SPRING = 3.0    # arch springline z
T_CROWN = 8.9     # inner crown z
T_FLOOR = -3.2    # wall foot z
T_INVERT = -4.4   # invert bottom z
T_THICK = 0.75


def tunnel_profile(offset=0.0, arch_n=18, inv_n=6):
    """Egg-shaped sewer section, counter-clockwise seen from behind (normals
    inward): right wall foot up, over the crown, down the left wall, round
    the invert. `offset` grows it outward."""
    w = T_WALL + offset
    pts = [(w, T_FLOOR), (w, 0.0), (w, T_SPRING)]
    b = T_CROWN - T_SPRING + offset
    for i in range(1, arch_n):
        t = math.pi * i / arch_n
        pts.append((w * math.cos(t), T_SPRING + b * math.sin(t)))
    pts += [(-w, T_SPRING), (-w, 0.0), (-w, T_FLOOR)]
    for i in range(1, inv_n):
        t = math.pi * i / inv_n
        pts.append((-w * math.cos(t), T_FLOOR - (T_FLOOR - T_INVERT + offset) * math.sin(t)))
    return pts


def arch_x(z, offset=0.0):
    """Inner wall x at height z (on the arch above the springline)."""
    w = T_WALL + offset
    if z <= T_SPRING:
        return w
    b = T_CROWN - T_SPRING + offset
    return w * math.cos(math.asin(min(1.0, (z - T_SPRING) / b)))


def build_tunnel():
    M = MATS
    ys = stations(-ROW / 2, ROW / 2, 0.5)
    tb, tk = tunnel_brick()
    M["tunnel_brick"] = tb
    inner = tunnel_profile(0.0, arch_n=14, inv_n=4)
    outer = tunnel_profile(T_THICK, arch_n=7, inv_n=3)
    parts = []

    # inner brick, split at z -1 (in the dark below the deck): the part you
    # see gets the texels, the invert almost none
    i0 = inner.index((T_WALL, 0.0))
    i1 = inner.index((-T_WALL, 0.0))
    upper = [(T_WALL, -1.0)] + inner[i0:i1 + 1] + [(-T_WALL, -1.0)]
    lower = [(-T_WALL, -1.0)] + inner[i1 + 1:] + [inner[0], (T_WALL, -1.0)]
    L_up = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(upper, upper[1:]))
    g = Geo()
    # three atlas islands (right wall, arch, left wall): one 26 m strip would cap the atlas scale
    j0 = upper.index((T_WALL, T_SPRING))
    j1 = upper.index((-T_WALL, T_SPRING))
    arcl = [0.0]
    for a_, b_ in zip(upper, upper[1:]):
        arcl.append(arcl[-1] + math.hypot(b_[0] - a_[0], b_[1] - a_[1]))
    mid = (j0 + j1) // 2
    for k0, k1, off in ((0, j0, (0, 0)), (j0, mid, (100, 0)), (mid, j1, (200, 0)), (j1, len(upper) - 1, (300, 0))):
        g.sweep(upper[k0:k1 + 1], ys, tb, v0=arcl[k0], uw_off=off)
    o = g.obj("t_inner", smooth_angle=50)
    o["atlas_weight"] = 2.0
    parts.append(o)
    g = Geo()
    g.sweep(lower, ys, tb, v0=L_up)
    o = g.obj("t_invert", smooth_angle=50)
    o["atlas_weight"] = 0.06
    parts.append(o)

    g = Geo()
    g.sweep(outer[::-1], ys, M["concrete_row"], close=True)
    for y, flip in ((-ROW / 2, True), (ROW / 2, False)):
        _strip(g, inner + [inner[0]], outer + [outer[0]], y, M["concrete_rib"], flip=flip)
    o = g.obj("t_outer", smooth_angle=50)
    o["atlas_weight"] = 0.1
    parts.append(o)

    # concrete rib at the module start (the first row's is the tunnel mouth)
    rib_in = [(x, z) for x, z in tunnel_profile(-0.3, arch_n=14, inv_n=5) if z > -1.6]
    ring = [(x, z) for x, z in inner if z > -1.6]
    g = Geo()
    y0, y1 = -ROW / 2, -ROW / 2 + 0.5
    g.sweep(rib_in, [y0, y1], M["concrete_rib"])
    _strip(g, ring, rib_in, y0, M["concrete_rib"], flip=False)
    _strip(g, ring, rib_in, y1, M["concrete_rib"], flip=True)
    o = g.obj("t_rib", smooth_angle=40)
    o["atlas_weight"] = 1.4
    parts.append(o)

    # pipes along the walls (outside the 11 m clearance), only their
    # visible half, flanged at the joint, strapped at mid-module
    g = Geo()
    pipes = ((5.86, 1.3, 0.38, 10), (-5.98, 0.95, 0.24, 7), (-5.98, 1.68, 0.17, 6))
    for (x, z, r, n) in pipes:
        sx = 1 if x > 0 else -1
        a0 = math.pi / 2 + sx * math.pi / 2 * 0.0
        # frame: N = up, B = +X; the wall side is B*sx: keep angles away from it
        c = math.pi / 2 * sx  # angle pointing at the wall
        g.tube([(x, y, z) for y in ys], r, n, M["pipe_row"], arc=(c + math.radians(70), c + math.radians(290)), v_len=1.0)
        fl = r * 1.3
        g.tube([(x, -ROW / 2, z), (x, -ROW / 2 + 0.13, z)], fl, 10, M["rust"], caps=(True, False), hole=r)
        g.box((min(x, sx * T_WALL), -0.46, z - r - 0.07), (max(x, sx * T_WALL), -0.34, z - r + 0.02), M["steel_row"])
    for i in range(4):
        a = 2 * math.pi * (i + 0.5) / 4
        bolt(g, (5.86 + 0.38 * 1.12 * math.cos(a), -ROW / 2 + 0.13, 1.3 + 0.38 * 1.12 * math.sin(a)), (0, 1, 0), 0.03,
             M["rust"], sides=5)
    o = g.obj("t_pipes", smooth_angle=40)
    o["atlas_weight"] = 1.2
    parts.append(o)

    # a cable along the left arch
    g = Geo()
    zc = 5.4
    xc = -arch_x(zc) + 0.1
    g.tube([(xc, y, zc) for y in ys], 0.05, 4, M["pipe_row"], v_len=1.0)
    o = g.obj("t_cables", smooth_angle=50)
    o["atlas_weight"] = 0.8
    parts.append(o)

    # caged fluorescent lights, staggered: right wall y +1.1, left y -1.1
    for sx, yc in ((1, 1.1), (-1, -1.1)):
        zl = 4.3
        xl = sx * (arch_x(zl) - 0.01)
        fit, tube = cage_light((xl, yc, zl), facing=-sx, length=1.3, name=f"t_light{sx}",
                               mats=(M["steel_row"], M["cage"]), seg=0.5, hoops=0.6, wire_sides=3, wires=(-0.08, 0.08))
        fit["atlas_weight"] = 1.5
        parts += [fit, tube]
        halo(tk, (xl, yc, zl), 3.4, "#c8ffd6", 0.5)

    g = Geo()
    rng = random.Random(4)
    for i in range(4):
        t = rng.uniform(0.22, 0.78) * math.pi
        x = (T_WALL - 0.3) * math.cos(t)
        z = T_SPRING + (T_CROWN - T_SPRING - 0.3) * math.sin(t)
        y = -ROW / 2 + rng.uniform(0.1, 0.45)
        L = rng.uniform(0.15, 0.4)
        g.tube([(x, y, z + 0.03), (x, y, z - L)], 0.04, 3, M["concrete_rib"], radii=[0.05, 0.006])
    o = g.obj("t_drips", smooth_angle=60)
    parts.append(o)

    g = Geo()
    g.face([(-T_WALL, -ROW / 2, -2.7), (T_WALL, -ROW / 2, -2.7), (T_WALL, ROW / 2, -2.7), (-T_WALL, ROW / 2, -2.7)],
           M["sludge"])
    o = g.obj("t_sludge")
    mesh.subdivide_along(o, "Y", positions=ys[1:-1])
    parts.append(o)
    return parts


def _strip(g, a, b, y, m, flip=False):
    """Triangles joining polylines a and b (XZ) at plane y (by arc length)."""
    def arclen(p):
        d = [0.0]
        for u, v in zip(p, p[1:]):
            d.append(d[-1] + math.hypot(v[0] - u[0], v[1] - u[1]))
        return [x / d[-1] for x in d]
    ta, tb = arclen(a), arclen(b)
    La = sum(math.hypot(v[0] - u[0], v[1] - u[1]) for u, v in zip(a, a[1:]))
    wd = sum(math.hypot(a[0][0] - b[0][0], a[0][1] - b[0][1]) for _ in (0,)) or 0.3
    ua = lambda k: (ta[k] * La, 0.0)  # noqa: E731
    ub = lambda k: (tb[k] * La, wd)  # noqa: E731
    i = j = 0
    while i < len(a) - 1 or j < len(b) - 1:
        if j >= len(b) - 1 or (i < len(a) - 1 and ta[i + 1] <= tb[j + 1]):
            tri = [(a[i][0], y, a[i][1]), (a[i + 1][0], y, a[i + 1][1]), (b[j][0], y, b[j][1])]
            w = [ua(i), ua(i + 1), ub(j)]
            i += 1
        else:
            tri = [(a[i][0], y, a[i][1]), (b[j + 1][0], y, b[j + 1][1]), (b[j][0], y, b[j][1])]
            w = [ua(i), ub(j + 1), ub(j)]
            j += 1
        if flip:
            tri, w = tri[::-1], w[::-1]
        g.face(tri, m, None, w)


def cage_light(pos, facing=-1, length=1.3, name="light", mats=None, mtx=None, seg=1.0, hoops=0.42, wire_sides=4,
               wires=(-0.11, 0.0, 0.11)):
    """Caged fluorescent bulkhead on a wall plane x = pos.x facing `facing`
    (+/-1 along X): steel housing, wire cage (atlas) and a SewerLight tube
    (kept). mtx: extra transform applied about pos (e.g. to hang it under an
    arm). Returns (fitting, tube)."""
    M = MATS
    steel, cage = mats or (M["steel"], M["cage"])
    x, y, z = pos
    f = facing
    L = length / 2
    g = Geo()
    back = "+x" if f < 0 else "-x"
    g.box((min(x, x + f * 0.05), y - L - 0.08, z - 0.16), (max(x, x + f * 0.05), y + L + 0.08, z + 0.16), steel,
          skip=(back,), ys=stations(y - L - 0.08, y + L + 0.08, seg))
    g.box((min(x + f * 0.05, x + f * 0.1), y - L, z - 0.12), (max(x + f * 0.05, x + f * 0.1), y + L, z + 0.12), steel,
          ys=stations(y - L, y + L, seg), skip=(back,))
    for a in wires:
        px = x + f * (0.1 + 0.085 * math.cos(a / 0.11 * 1.2) + 0.005)
        g.tube([(px, yy, z + a) for yy in stations(y - L + 0.02, y + L - 0.02, seg)], 0.009, wire_sides, cage)
    for yy in stations(y - L + 0.05, y + L - 0.05, hoops):
        path = [(x + f * 0.1, yy, z - 0.13)] + [(x + f * (0.1 + 0.095 * math.sin(t)), yy, z - 0.13 * math.cos(t))
                                               for t in np.linspace(0.4, math.pi - 0.4, 3)] + [(x + f * 0.1, yy, z + 0.13)]
        g.tube(path, 0.011, wire_sides, cage)
    fit = g.obj(name + "_fit", smooth_angle=40)
    g = Geo()
    g.tube([(x + f * 0.15, yy, z) for yy in stations(y - L + 0.06, y + L - 0.06, seg)], 0.034, 6, M["light"], caps=(True, True))
    tube = g.obj(name + "_tube", smooth_angle=70)
    if mtx is not None:
        full = Matrix.Translation(Vector(pos)) @ mtx @ Matrix.Translation(-Vector(pos))
        xform(fit, full)
        xform(tube, full)
    return fit, tube


# ------------------------------------------------------------------ rail + overhang

def build_rail():
    """1 m of steel pipe rail on a bracket (y 0..1, top at z 1.1)."""
    M = MATS
    g = Geo()
    R, zc = 0.1, 1.0
    g.tube([(0, 0, zc), (0, 0.5, zc), (0, 1.0, zc)], R, 10, M["rail_pipe"], v_len=2 * math.pi * R)
    g.box((-0.03, 0.47, 0.0), (0.03, 0.53, zc - R - 0.01), M["steel"], skip=("-z", "+z"))
    g.tube([(0, 0.455, zc), (0, 0.545, zc)], R + 0.02, 10, M["steel"], arc=(math.pi * 0.55, math.pi * 1.45))
    g.box((-0.1, 0.42, 0.0), (0.1, 0.58, 0.025), M["steel"], skip=("-z",))
    o = g.obj("rail_sewer", smooth_angle=40)
    o["atlas_weight"] = 2.0
    return [o]


def rail_material():
    """Chipped green pipe paint, the top ground to bare steel by grinds.
    Tiles every metre (the module)."""
    m = mat.pbr("RailPipe", "PaintedMetal006", tiling=(1.0, 1.0), value=0.5, saturation=0.6, uv_map="UVMap")
    k = N(m, 1.0)
    _, _, nz = k.nrm()
    worn = k.smooth(nz, 0.55, 0.85)
    wn = k.noise(scale=6, stretch=(1, 0.3, 1), detail=4)
    worn = k.mul(worn, k.smooth(wn, 0.2, 0.45))
    k.set("Base Color", k.mixc(k.src("Base Color"), "#9aa0a2", worn))
    k.set("Roughness", k.mixf(k.src("Roughness"), 0.18, worn))
    k.set("Metallic", k.mixf(k.src("Metallic"), 1.0, worn))
    return m


def build_overhang():
    """A fallen giant pipe across all three lanes: solid between z 1.05 and
    3.2 (you roll under it), resting on broken piers outside x +-3.6."""
    M = MATS
    R = 1.075
    zc = 1.05 + R
    parts = []
    g = Geo()
    xs = [-5.9, -4.6, -3.7, -3.5, -1.2, 0.0, 1.2, 3.5, 3.7, 4.6, 5.9]
    g.tube([(x, 0.0, zc) for x in xs], R, 24, M["pipe"], phase=-math.pi / 2, v_len=1.0)
    for sx in (-1, 1):
        g.tube([(sx * 5.3, 0, zc), (sx * 5.9, 0, zc)], R - 0.1, 24, M["dark"], flip=True)
    o = g.obj("oh_pipe", smooth_angle=40)
    o["atlas_weight"] = 1.0
    parts.append(o)
    g = Geo()  # jagged broken lips
    for sx in (-1, 1):
        rng = random.Random(11 if sx > 0 else 12)
        n = 24
        angs = [2 * math.pi * i / n for i in range(n)]
        jag = [rng.uniform(-0.08, 0.3) for _ in range(n)]
        ro = [(sx * (5.9 + j), R * math.sin(a), zc + R * math.cos(a)) for a, j in zip(angs, jag)]
        ri = [(sx * (5.9 + j * 0.7), (R - 0.1) * math.sin(a), zc + (R - 0.1) * math.cos(a)) for a, j in zip(angs, jag)]
        for i in range(n):
            k2 = (i + 1) % n
            g.face([ro[i], ro[k2], ri[k2], ri[i]], M["rust"], None,
                   [(q[1], q[2]) for q in (ro[i], ro[k2], ri[k2], ri[i])])
        # the jagged bit of the outer skin beyond x=5.9
        for i in range(n):
            k2 = (i + 1) % n
            g.face([(sx * 5.9, R * math.sin(angs[i]), zc + R * math.cos(angs[i])),
                    (sx * 5.9, R * math.sin(angs[k2]), zc + R * math.cos(angs[k2])), ro[k2], ro[i]], M["pipe"])
    o = g.obj("oh_lips", smooth_angle=35, merge=False)
    for p in o.data.polygons:  # lips face out along the pipe (+-x), skin faces out radially
        c = p.center
        radial = Vector((0, c.y, c.z - zc))
        want = radial if p.material_index == o.data.materials.find("PipePaint") else Vector((1 if c.x > 0 else -1, 0, 0))
        if p.normal.dot(want) < 0:
            p.flip()
    o["atlas_weight"] = 1.0
    parts.append(o)
    g = Geo()
    for x in (-3.6, 3.6):
        g.tube([(x - 0.1, 0, zc), (x + 0.1, 0, zc)], R + 0.12, 24, M["rust"], caps=(True, True), hole=R)
    for x in (-3.6, 3.6):
        for i in range(10):
            a = 2 * math.pi * (i + 0.5) / 10
            bolt(g, (x, (R + 0.07) * math.sin(a), zc + (R + 0.07) * math.cos(a)), (0, math.sin(a), math.cos(a)), 0.04, M["rust"], h=0.05)
    o = g.obj("oh_flange", smooth_angle=40)
    o["atlas_weight"] = 1.2
    parts.append(o)
    g = Geo()
    g.tube([(-1.25, 0, zc), (-0.4, 0, zc), (0.4, 0, zc), (1.25, 0, zc)], R + 0.008, 24, M["hazard"], phase=-math.pi / 2, v_len=1.0)
    o = g.obj("oh_hazard", smooth_angle=40)
    o["atlas_weight"] = 1.2
    parts.append(o)
    # warning strip on the lower front of the pipe: the line you roll under
    g = Geo()
    phis = [math.radians(a) for a in (20, 30, 40)]
    pts = [(-R - 0.012) * math.sin(p) for p in phis], [zc - (R + 0.012) * math.cos(p) for p in phis]
    for i in range(len(phis) - 1):
        ya, za, yb, zb = pts[0][i], pts[1][i], pts[0][i + 1], pts[1][i + 1]
        g.face([(-3.45, ya, za), (3.45, ya, za), (3.45, yb, zb), (-3.45, yb, zb)], M["warn"])
    o = g.obj("oh_warn")
    fix_normals_outward(o, (0, 0, zc), axis="x")
    parts.append(o)
    g = Geo()
    for sx in (-1, 1):
        x0, x1 = sorted((sx * 3.85, sx * 5.4))
        g.box((x0, -0.75, -0.2), (x1, 0.75, 0.62), M["concrete"], skip=("-z",))
        g.box((x0 + 0.12, -0.6, 0.62), (x1 - 0.1, 0.55, 1.12), M["concrete"], skip=("-z",))
        g.box((x0 + 0.25, -0.5, 1.02), (x1 - 0.3, 0.45, 1.08), M["steel"], skip=("-z",))
    o = g.obj("oh_piers", smooth_angle=30)
    o["atlas_weight"] = 1.0
    parts.append(o)
    g = Geo()
    for sx in (-1, 1):
        g.tube([(sx * 4.6, -0.95, 1.12), (sx * 4.6, -0.95, 1.42)], 0.1, 8, M["beacon"], caps=(False, True))
    o = g.obj("oh_beacon", smooth_angle=60)
    parts.append(o)
    g = Geo()
    for sx in (-1, 1):
        xe = sx * 5.95
        g.tube([(xe, 0.15, zc - R + 0.18), (xe + sx * 0.28, 0.15, zc - R - 0.12), (xe + sx * 0.4, 0.15, 0.5),
                (xe + sx * 0.45, 0.15, -0.3)], 0.2, 6, M["sludge"], radii=[0.32, 0.24, 0.15, 0.11])
    parts.append(g.obj("oh_ooze", smooth_angle=60))
    return parts


# ------------------------------------------------------------------ scenery helpers

DEEP = -24.0   # scenery reaches down here (drops never show a base)
SPLIT = -3.0   # below this faces take little atlas space (seen only in drops)


def weight(o, w):
    o["atlas_weight"] = w
    return o


def brick_wall(bm_, y0, y1, top, parts, thick=1.1, pil=(0.28, 0.75), hi=1.2, lo=0.05, cap=True):
    """A brick wall chunk facing -X with its face at x=0 (right-side piece):
    pilasters at both ends, a concrete coping, the face split at SPLIT so
    the deep part is cheap in the atlas."""
    M = MATS
    ys = stations(y0, y1, 1.0)
    for zlo, ztop, w in ((0.0, top, hi), (SPLIT, 0.0, hi * 0.4), (DEEP, SPLIT, lo)):
        g = Geo()
        g.box((0.0, y0, zlo), (thick, y1, ztop), bm_, skip=("+x", "-z", "+z"), ys=ys)
        py = [(y0, y0 + pil[1]), (y1 - pil[1], y1)]
        for a, b in py:
            g.box((-pil[0], a, zlo), (0.0, b, ztop + (0.25 if ztop == top else 0.0)), bm_, skip=("+x", "-z", "+z"))
        parts.append(weight(g.obj(f"wall_{zlo:.0f}", smooth_angle=30), w))
    g = Geo()
    if cap:
        g.box((-0.14, y0 - 0.08, top), (thick + 0.06, y1 + 0.08, top + 0.32), M["concrete"], skip=("-z", "+x"),
              ys=stations(y0 - 0.08, y1 + 0.08, 1.0))
        for a, b in [(y0, y0 + pil[1]), (y1 - pil[1], y1)]:
            g.box((-pil[0] - 0.06, a - 0.06, top + 0.25), (0.1, b + 0.06, top + 0.52), M["concrete"], skip=("-z", "+x"))
    parts.append(weight(g.obj("wall_cap", smooth_angle=30), hi))


def pipe_run(g, pts, r, m, sides=12, phase=math.pi / 2, max_len=1.0, caps=(False, False), arc=None):
    """Tube through `pts` with extra points so no segment is over max_len."""
    path = [Vector(pts[0])]
    for a, b in zip(pts, pts[1:]):
        a, b = Vector(a), Vector(b)
        n = max(1, math.ceil((b - a).length / max_len - 1e-6))
        path += [a.lerp(b, k / n) for k in range(1, n + 1)]
    return g.tube(path, r, sides, m, phase=0.0 if arc else phase, v_len=1.0, caps=caps, arc=arc)


FRONT = (math.pi / 2 + math.radians(58), math.pi / 2 + math.radians(302))  # a Y pipe minus its +X back


def elbow_run(x, y0, y1, z, rb, wall_x=0.4, steps=6):
    """Path of a pipe that comes out of a wall (at +X), runs along Y at x
    from y0 to y1, and goes back in: quarter bends of radius rb."""
    pts = [(x + rb + wall_x, y0 - rb, z)]
    for t in np.linspace(math.pi / 2, 0, steps):
        pts.append((x + rb - rb * math.cos(t), y0 - rb * math.sin(t), z))
    for y in stations(y0, y1, 1.0)[1:-1]:
        pts.append((x, y, z))
    for t in np.linspace(0, math.pi / 2, steps):
        pts.append((x + rb - rb * math.cos(t), y1 + rb * math.sin(t), z))
    pts.append((x + rb + wall_x, y1 + rb, z))
    return pts


def flange(g, center, axis, r, m, length=0.12, bolts=0, bolt_r=0.03, bolt_m=None, face=-1):
    c, ax = Vector(center), Vector(axis).normalized()
    g.tube([c - ax * length / 2, c + ax * length / 2], r, 14, m, caps=(True, True), hole=r * 0.8)
    if bolts:
        ref = Vector((0, 0, 1)) if abs(ax.z) < 0.9 else Vector((1, 0, 0))
        n1 = (ref - ax * ref.dot(ax)).normalized()
        n2 = ax.cross(n1)
        for i in range(bolts):
            a = 2 * math.pi * (i + 0.5) / bolts
            p = c + ax * (face * length / 2) + (n1 * math.cos(a) + n2 * math.sin(a)) * (r * 0.84)
            bolt(g, p, ax * face, bolt_r, bolt_m or m)


def handwheel(g, center, axis, r, m, spokes=4):
    c, ax = Vector(center), Vector(axis).normalized()
    ref = Vector((0, 0, 1)) if abs(ax.z) < 0.9 else Vector((1, 0, 0))
    n1 = (ref - ax * ref.dot(ax)).normalized()
    n2 = ax.cross(n1)
    ring = [c + (n1 * math.cos(t) + n2 * math.sin(t)) * r for t in np.linspace(0, 2 * math.pi, 15)]
    g.tube(ring, r * 0.09, 6, m)
    for i in range(spokes):
        a = 2 * math.pi * i / spokes
        g.tube([c, c + (n1 * math.cos(a) + n2 * math.sin(a)) * r], r * 0.05, 4, m)
    g.tube([c - ax * 0.05, c + ax * 0.08], r * 0.16, 8, m, caps=(True, True))


def rounded_rect(w, h, r, n=4):
    """Outline (CCW) of a rounded rectangle centred at 0."""
    pts = []
    for cx, cy, a0 in ((w / 2 - r, h / 2 - r, 0), (-w / 2 + r, h / 2 - r, 90), (-w / 2 + r, -h / 2 + r, 180),
                       (w / 2 - r, -h / 2 + r, 270)):
        for i in range(n + 1):
            a = math.radians(a0 + 90 * i / n)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def prism(g, outline, z0, z1, m_side, m_top, m_bot=None, inset=0.0, top_uv=None, mtx=None, m_bezel=None):
    """Extrude a CCW outline from z0 to z1 (local), optional bevel inset on
    the top (a chamfer ring). top_uv(x, y) -> uv for the top face. mtx
    places it."""
    start = g.nverts()
    n = len(outline)
    zt = z1 - (inset if inset else 0.0)
    for i in range(n):
        a, b = outline[i], outline[(i + 1) % n]
        g.face([(a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], zt), (a[0], a[1], zt)], m_side)
    if inset:
        cx = sum(p[0] for p in outline) / n
        cy = sum(p[1] for p in outline) / n
        inner = []
        for p in outline:
            d = Vector((p[0] - cx, p[1] - cy))
            k = max(0.0, 1 - inset / max(d.length, 1e-6))
            inner.append((cx + d.x * k, cy + d.y * k))
        for i in range(n):
            a, b = outline[i], outline[(i + 1) % n]
            ia, ib = inner[i], inner[(i + 1) % n]
            g.face([(a[0], a[1], zt), (b[0], b[1], zt), (ib[0], ib[1], z1), (ia[0], ia[1], z1)], m_bezel or m_side)
        top = inner
    else:
        top = outline
    g.face([(p[0], p[1], z1) for p in top], m_top, [top_uv(*p) for p in top] if top_uv else None)
    if m_bot is not None:
        g.face([(p[0], p[1], z0) for p in outline[::-1]], m_bot)
    if mtx is not None:
        g.transform(mtx, start)


def phone(g, mtx, screen_m, w=1.25, h=2.6, t=0.11, gs=None):
    """A giant discarded phone lying in local XY (screen up +Z), placed by
    mtx. gs: a separate Geo for the screen (its own atlas weight)."""
    M = MATS
    out = rounded_rect(w, h, 0.17, 3)
    scr = rounded_rect(w - 0.1, h - 0.1, 0.12, 3)
    start = g.nverts()
    n = len(out)
    per = [0.0]
    for i in range(n):
        a, b = out[i], out[(i + 1) % n]
        per.append(per[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    for i in range(n):  # frame sides: one strip
        a, b = out[i], out[(i + 1) % n]
        g.face([(a[0], a[1], -t / 2), (b[0], b[1], -t / 2), (b[0], b[1], t / 2), (a[0], a[1], t / 2)], M["phone_frame"],
               None, [(per[i], 0), (per[i + 1], 0), (per[i + 1], t), (per[i], t)])
    for i in range(n):  # front bezel ring + screen: one planar island
        a, b, ia, ib = out[i], out[(i + 1) % n], scr[i], scr[(i + 1) % n]
        g.face([(a[0], a[1], t / 2), (b[0], b[1], t / 2), (ib[0], ib[1], t / 2 + 0.004), (ia[0], ia[1], t / 2 + 0.004)],
               M["plastic_blk"], None, [a, b, ib, ia])
    if gs is not None:
        s0 = gs.nverts()
        gs.face([(p[0], p[1], t / 2 + 0.004) for p in scr], screen_m, [((p[0] + w / 2) / w, (p[1] + h / 2) / h) for p in scr],
                [p for p in scr])
        gs.transform(mtx, s0)
    else:
        g.face([(p[0], p[1], t / 2 + 0.004) for p in scr], screen_m, [((p[0] + w / 2) / w, (p[1] + h / 2) / h) for p in scr],
               [p for p in scr])
    g.face([(p[0], p[1], -t / 2) for p in out[::-1]], M["plastic_blk"], None, [(-p[0], p[1]) for p in out[::-1]])
    # camera bump on the back
    bump = rounded_rect(0.42, 0.42, 0.1, 2)
    bump = [(x - w / 2 + 0.32, y + h / 2 - 0.32) for x, y in bump]
    for i in range(len(bump)):
        a, b = bump[i], bump[(i + 1) % len(bump)]
        g.face([(b[0], b[1], -t / 2), (a[0], a[1], -t / 2), (a[0], a[1], -t / 2 - 0.04), (b[0], b[1], -t / 2 - 0.04)],
               M["phone_frame"])
    g.face([(p[0], p[1], -t / 2 - 0.04) for p in bump[::-1]], M["plastic_blk"])
    g.transform(mtx, start)


def screen_material(name, seed, lit, impact=(0.3, 0.25)):
    img = crack_image(seed, impact=impact)
    m = mat.flat(name, "#050607", rough=0.07)
    k = N(m)
    uv = k.n("ShaderNodeUVMap", uv_map="UVMap").outputs["UV"]
    t = k.image(img, uv, ext="EXTEND")
    sep = k.n("ShaderNodeSeparateColor")
    k.link(t.outputs["Color"], sep.inputs[0])
    crack, core, glow = sep.outputs[0], sep.outputs[1], sep.outputs[2]
    col = k.mixc("#050607", "#5f6668", crack)
    col = k.mixc(col, "#8d9596", core)
    k.set("Base Color", col)
    k.set("Roughness", k.mixf(0.06, 0.5, k.add(crack, core, clamp=True)))
    if lit:
        e = k.add(k.mul(glow, 0.35), k.mul(crack, 1.2))
        e = k.mul(e, k.sub(1.0, k.mul(core, 0.6)))
        k.emit("#9dffb8", k.mul(e, lit))
    return m


ARROW = [(-0.28, 0.72), (-0.28, 0.0), (-0.64, 0.0), (0.0, -0.66), (0.64, 0.0), (0.28, 0.0), (0.28, 0.72)]


def downvote(g, mtx, m, t=0.34):
    """A chunky extruded downvote arrow (points -Y), chamfered, placed by mtx."""
    out = ARROW[::-1]  # CCW
    start = g.nverts()
    n = len(out)
    c = 0.06
    inner = []
    for i in range(n):  # offset inward along the averaged edge normals
        p0, p1, p2 = Vector(out[i - 1]), Vector(out[i]), Vector(out[(i + 1) % n])
        e1, e2 = (p1 - p0).normalized(), (p2 - p1).normalized()
        n1, n2 = Vector((-e1.y, e1.x)), Vector((-e2.y, e2.x))
        bis = (n1 + n2).normalized()
        k = c / max(0.35, bis.dot(n1))
        inner.append(tuple(p1 + bis * k))
    zs = (-t / 2, -t / 2 + c, t / 2 - c, t / 2)
    per = [0.0]
    for i in range(n):
        a, b = out[i], out[(i + 1) % n]
        per.append(per[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    v1, v2 = c * 1.41, c * 1.41 + (zs[2] - zs[1])
    v3 = v2 + c * 1.41
    for i in range(n):
        a, b, ia, ib = out[i], out[(i + 1) % n], inner[i], inner[(i + 1) % n]
        u0, u1 = per[i], per[i + 1]
        g.face([(a[0], a[1], zs[1]), (b[0], b[1], zs[1]), (b[0], b[1], zs[2]), (a[0], a[1], zs[2])], m, None,
               [(u0, v1), (u1, v1), (u1, v2), (u0, v2)])
        g.face([(a[0], a[1], zs[2]), (b[0], b[1], zs[2]), (ib[0], ib[1], zs[3]), (ia[0], ia[1], zs[3])], m, None,
               [(u0, v2), (u1, v2), (u1, v3), (u0, v3)])
        g.face([(b[0], b[1], zs[1]), (a[0], a[1], zs[1]), (ia[0], ia[1], zs[0]), (ib[0], ib[1], zs[0])], m, None,
               [(u1, v1), (u0, v1), (u0, 0.0), (u1, 0.0)])
    g.face([(p[0], p[1], zs[3]) for p in inner], m, None, [p for p in inner])
    g.face([(p[0], p[1], zs[0]) for p in inner[::-1]], m, None, [(-p[0], p[1]) for p in inner[::-1]])
    g.transform(mtx, start)


def place(x, y, z, rz=0.0, rx=0.0, ry=0.0, s=1.0):
    return (Matrix.Translation((x, y, z)) @ Matrix.Rotation(math.radians(rz), 4, "Z") @
            Matrix.Rotation(math.radians(ry), 4, "Y") @ Matrix.Rotation(math.radians(rx), 4, "X") @ Matrix.Scale(s, 4))


def concrete_block(x0, x1, y0, y1, top, parts, m=None, hi=0.6, lo=0.03, skip_back=True, name="block", top_face=True):
    """A concrete mass from `top` down to DEEP (front face at x0 facing -X)."""
    m = m or MATS["concrete"]
    ys = stations(y0, y1, 1.0)
    for zlo, zhi, w, tp in ((SPLIT, top, hi, True), (DEEP, SPLIT, lo, False)):
        if zhi <= zlo:
            continue
        g = Geo()
        skip = ["-z"] + (["+x"] if skip_back else []) + ([] if (tp and top_face) else ["+z"])
        g.box((x0, y0, zlo), (x1, y1, zhi), m, skip=tuple(skip), ys=ys)
        parts.append(weight(g.obj(f"{name}_{'hi' if tp else 'lo'}", smooth_angle=30), w))


def block_front(g, y0, y1, top, seed=1):
    """Details on a concrete front face (x=0): a dark culvert mouth with a
    steel grille, a drain pipe along it, rust-stained bolted plates."""
    M = MATS
    rng = random.Random(seed)
    yc = rng.uniform(y0 + 1.6, y1 - 1.6)
    zc = top - rng.uniform(1.6, 2.4)
    w, h = 1.3, 1.1
    g.face_out([(-0.01, yc + w / 2, zc - h / 2), (-0.01, yc - w / 2, zc - h / 2), (-0.01, yc - w / 2, zc + h / 2),
                (-0.01, yc + w / 2, zc + h / 2)], M["dark"], (-1, 0, 0))
    for k in range(5):
        yy = yc - w / 2 + w * (k + 0.5) / 5
        g.box((-0.06, yy - 0.025, zc - h / 2), (0.0, yy + 0.025, zc + h / 2), M["steel"], skip=("+x", "-z", "+z"))
    g.box((-0.08, yc - w / 2 - 0.08, zc - h / 2 - 0.08), (0.0, yc + w / 2 + 0.08, zc - h / 2), M["concrete"], skip=("+x",))
    zp = top - 0.55
    pipe_run(g, [(-0.2, y0, zp), (-0.2, y1, zp)], 0.16, M["pipe"], sides=8)
    for yb in stations(y0 + 0.6, y1 - 0.6, 2.4):
        g.box((-0.06, yb - 0.05, zp - 0.2), (0.0, yb + 0.05, zp + 0.2), M["steel"], skip=("+x",))


# ------------------------------------------------------------------ scenery pieces


def side_wall_pipes(G):
    """Brick wall with a flanged pipe run, valve, gauge, conduit, a caged
    light and 'ratio' sprayed over it."""
    M = MATS
    y0, y1, top = -4.4, 4.4, 7.4
    lamp = (0.0, 2.9, 5.5)
    brick = brick_material("BrickPipes", graffitis=[
        (G["ratio"], 2.1, -3.7, 3.85, 6.95),
        (G["L"], -1.4, -3.0, 0.2, 1.8, 0.42, 0.25),
        (G["arrow"], 3.4, 2.6, 0.35, 1.15),
    ], halos=[((lamp[0] - 0.2, lamp[1], lamp[2]), 2.6, "#b8ffcc", 0.28)], waterline=1.55)
    parts = []
    brick_wall(brick, y0, y1, top, parts)
    g = Geo()
    zc, xp, r1 = 2.3, -0.62, 0.32
    g.tube(elbow_run(xp, -3.3, 3.3, zc, 0.55), r1, 12, M["pipe"], phase=math.pi / 2, v_len=1.0)
    for yf in (-1.2, 1.5):
        flange(g, (xp, yf, zc), (0, 1, 0), r1 * 1.3, M["rust"], bolts=6, bolt_r=0.035)
    pipe_run(g, [(-0.3, y0 - 0.2, 3.3), (-0.3, y1 + 0.2, 3.3)], 0.17, M["pipe"], sides=10)
    for yb in (-2.4, 0.3, 2.6):  # shelf brackets under the big pipe
        g.box((xp - 0.2, yb - 0.05, zc - r1 - 0.07), (0.0, yb + 0.05, zc - r1 - 0.01), M["steel"])
        g.box((-0.05, yb - 0.08, zc - r1 - 0.5), (0.0, yb + 0.08, zc - r1 - 0.01), M["steel"], skip=("+x",))
        g.box((-0.33, yb - 0.04, 3.3 - 0.17 - 0.05), (0.0, yb + 0.04, 3.3 - 0.17), M["steel"])
    # gate valve + handwheel on top of the big pipe
    yv = 0.9
    g.tube([(xp, yv, zc + r1 - 0.02), (xp, yv, zc + r1 + 0.28)], 0.09, 8, M["steel"], caps=(False, True))
    g.box((xp - 0.16, yv - 0.1, zc + r1 + 0.1), (xp + 0.16, yv + 0.1, zc + r1 + 0.3), M["steel"])
    g.tube([(xp, yv, zc + r1 + 0.3), (xp, yv, zc + r1 + 0.62)], 0.03, 6, M["steel"])
    handwheel(g, (xp, yv, zc + r1 + 0.62), (0, 0, 1), 0.3, M["valve"])
    # pressure gauge
    yg = -2.0
    g.tube([(xp - 0.1, yg, zc + r1 - 0.05), (xp - 0.1, yg, zc + r1 + 0.18)], 0.025, 6, M["steel"])
    g.tube([(xp - 0.1, yg + 0.04, zc + r1 + 0.3), (xp - 0.1, yg - 0.04, zc + r1 + 0.3)], 0.13, 12, M["steel"], caps=(True, True))
    g.tube([(xp - 0.1, yg - 0.041, zc + r1 + 0.3), (xp - 0.1, yg - 0.043, zc + r1 + 0.3)], 0.11, 12, M["gauge"], caps=(False, True))
    # downpipe in front of the far pilaster, conduit to the lamp
    g.tube([(-0.42, y1 - 0.38, top + 0.3), (-0.42, y1 - 0.38, DEEP)], 0.11, 8, M["pipe"], v_len=1.0)
    g.tube([(-0.42, y1 - 0.38, top + 0.3), (-0.42, y1 - 0.38, top + 0.5), (0.3, y1 - 0.38, top + 0.5)], 0.11, 8, M["pipe"])
    pipe_run(g, [(-0.04, y0, 4.55), (-0.04, lamp[1] - 0.9, 4.55)], 0.035, M["steel"], sides=6)
    g.tube([(-0.04, lamp[1] - 0.9, 4.55), (-0.04, lamp[1] - 0.72, 4.8), (-0.04, lamp[1] - 0.72, lamp[2] - 0.2)], 0.035, 6, M["steel"])
    g.box((-0.14, -1.1, 4.3), (0.0, -0.7, 4.8), M["steel"], skip=("+x",))
    parts.append(weight(g.obj("wp_pipes", smooth_angle=40), 1.1))
    fit, tube = cage_light(lamp, -1, 1.1, "wp_light")
    parts += [weight(fit, 1.4), tube]
    return parts, dict(slot="wall", every=11.0, chance=0.7, side="both")


def side_wall_ladder(G):
    """Brick wall with an outfall pouring glowing sludge into the abyss, an
    iron ladder, a caged light; 'who asked' and 'this you?' sprayed on."""
    M = MATS
    y0, y1, top = -3.3, 3.3, 8.6
    yo, zo, ro, ri = -1.9, 1.15, 1.08, 0.86
    lamp = (0.0, -0.1, 4.55)
    brick = brick_material("BrickLadder", graffitis=[
        (G["whoasked"], 3.0, -2.6, 5.25, 7.35),
        (G["thisyou"], 1.25, -2.75, 2.45, 3.95),
    ], halos=[((lamp[0] - 0.2, lamp[1], lamp[2]), 2.6, "#b8ffcc", 0.28), ((-0.3, yo, zo - 1.2), 2.0, "#3cff2e", 0.25)],
        waterline=1.7)
    parts = []
    brick_wall(brick, y0, y1, top, parts)
    g = Geo()
    # culvert ring sticking out of the wall
    angs = np.linspace(0, 2 * math.pi, 17)[:-1]
    g.tube([(0.3, yo, zo), (-0.32, yo, zo)], ro, 16, M["concrete"], phase=0.0, v_len=1.0)
    ring_o = [(-0.32, yo + ro * math.cos(a), zo + ro * math.sin(a)) for a in angs]
    ring_i = [(-0.32, yo + ri * math.cos(a), zo + ri * math.sin(a)) for a in angs]
    for i in range(16):
        j = (i + 1) % 16
        g.face([ring_o[i], ring_o[j], ring_i[j], ring_i[i]], M["concrete"], None,
               [(q[1], q[2]) for q in (ring_o[i], ring_o[j], ring_i[j], ring_i[i])])
    o = g.obj("wl_culvert", smooth_angle=35)
    fix_normals_outward(o, (0.6, yo, zo), axis="x")
    for p in o.data.polygons:  # the lip faces -X
        if abs(p.center.x + 0.32) < 0.01 and p.normal.x > 0:
            p.flip()
    parts.append(weight(o, 1.1))
    g = Geo()
    g.tube([(-0.32, yo, zo), (0.9, yo, zo)], ri, 16, M["dark"], flip=True)
    g.face([(0.9, yo + ri * math.cos(a), zo + ri * math.sin(a)) for a in angs], M["dark"])
    o = g.obj("wl_hole", smooth_angle=35)
    for p in o.data.polygons:
        if p.center.x > 0.85 and p.normal.x > 0:
            p.flip()
    parts.append(weight(o, 0.1))
    # sludge: the stream inside the culvert, over the lip, down the wall
    g = Geo()
    zs = zo - ri + 0.1
    g.face([(0.9, yo - 0.45, zs), (0.9, yo + 0.45, zs), (-0.33, yo + 0.5, zs), (-0.33, yo - 0.5, zs)], M["sludge"])
    fall = [(-0.33, zs), (-0.5, zs - 0.12), (-0.55, zs - 0.5), (-0.4, zs - 1.3), (-0.22, zs - 2.4), (-0.1, zs - 4.0),
            (-0.07, -8.0), (-0.06, DEEP)]
    rows = []
    for i, (x, z) in enumerate(fall):
        hw = 0.5 - 0.18 * min(1.0, i / 4)
        rows.append([(x, yo + hw, z), (x, yo - hw, z)])
    for a, b in zip(rows, rows[1:]):
        g.face([a[0], a[1], b[1], b[0]], M["sludge"])
    o = g.obj("wl_sludge", smooth_angle=60)
    for p in o.data.polygons:
        if p.normal.x > 0.2 or (abs(p.normal.z) > 0.9 and p.normal.z < 0):
            p.flip()
    parts.append(o)
    # iron ladder (stiles off the wall on brackets, rungs every 0.3 m)
    g = Geo()
    yl, zl0, zl1 = 1.55, -5.0, top + 1.0
    for sy in (-1, 1):
        yy = yl + sy * 0.26
        g.box((-0.2, yy - 0.035, zl0), (-0.15, yy + 0.035, zl1), M["steel"], skip=("-z",))
        for zb in np.arange(zl0 + 0.4, zl1 - 0.2, 2.0):
            g.box((-0.15, yy - 0.025, zb), (0.0, yy + 0.025, zb + 0.06), M["steel"], skip=("+x",))
    for zr in np.arange(zl0 + 0.3, zl1 - 0.1, 0.3):
        g.tube([(-0.175, yl - 0.25, zr), (-0.175, yl + 0.25, zr)], 0.018, 4, M["steel"])
    # top hoop over the coping
    g.tube([(-0.175, yl - 0.26, zl1), (-0.3, yl - 0.26, zl1 + 0.35), (0.3, yl - 0.26, zl1 + 0.45), (0.8, yl - 0.26, top + 0.3)], 0.03, 4, M["steel"])
    g.tube([(-0.175, yl + 0.26, zl1), (-0.3, yl + 0.26, zl1 + 0.35), (0.3, yl + 0.26, zl1 + 0.45), (0.8, yl + 0.26, top + 0.3)], 0.03, 4, M["steel"])
    parts.append(weight(g.obj("wl_ladder", smooth_angle=40), 1.0))
    fit, tube = cage_light(lamp, -1, 1.2, "wl_light")
    parts += [weight(fit, 1.4), tube]
    return parts, dict(slot="wall", every=17.0, chance=0.45, side="both")


def side_lamp(G):
    """A concrete column with a caged fluorescent light hung off an arm."""
    M = MATS
    lampz = 5.55
    conc = mat.pbr("ConcreteLamp", "Concrete044D", mapping="BOX", box_scale=1.8, wet=0.45, value=0.65,
                   saturation=0.5, normal_strength=0.0, bump=0.4, bump_distance=0.02)
    k = grime(conc, splash=0.6, depth=-2.0, streaks=0.9, algae=0.6, salts=0.3)
    halo(k, (-0.2, 0.0, lampz), 2.6, "#b8ffcc", 0.35)
    graffiti(k, G["arrow"], 0.36, -0.36, 2.4, 3.1)
    parts = []
    for zlo, zhi, w in ((SPLIT, 6.3, 1.2), (DEEP, SPLIT, 0.05)):
        g = Geo()
        g.box((0.0, -0.36, zlo), (0.72, 0.36, zhi), conc, skip=("-z", "+x") + (() if zhi == 6.3 else ("+z",)))
        parts.append(weight(g.obj("lamp_col", smooth_angle=30), w))
    g = Geo()
    g.box((-0.04, -0.4, 6.3), (0.76, 0.4, 6.36), M["steel"], skip=("-z",))
    g.box((-1.25, -0.06, 6.0), (0.0, 0.06, 6.14), M["steel"], skip=("+x",))
    g.tube([(-0.02, 0.0, 5.4), (-0.9, 0.0, 6.0)], 0.035, 6, M["steel"])
    g.tube([(-1.05, 0.0, 6.0), (-1.05, 0.0, lampz + 0.2)], 0.012, 4, M["cage"])
    g.box((-0.12, -0.18, 1.1), (0.0, 0.18, 1.55), M["steel"], skip=("+x",))
    pipe_run(g, [(-0.05, 0.22, 1.55), (-0.05, 0.22, 6.0)], 0.03, M["steel"], sides=6)
    g.tube([(-0.05, 0.22, 1.1), (-0.05, 0.22, DEEP)], 0.03, 6, M["steel"], v_len=1.0)
    parts.append(weight(g.obj("lamp_arm", smooth_angle=40), 1.2))
    hang = Matrix.Rotation(math.radians(-90), 4, "Y")
    fit, tube = cage_light((-1.05, 0.0, lampz + 0.05), 1, 1.6, "lamp_light", mtx=hang)
    parts += [weight(fit, 1.4), tube]
    return parts, dict(slot="wall", every=14.0, chance=0.55, side="both")


def side_pipes(G):
    """A pipe rack out in the dark: three big flanged pipes on steel frames
    rising from the depths, a riser, a red valve, a sludge leak."""
    M = MATS
    y0, y1 = -6.6, 6.6
    pipe_big = pipe_paint("PipeRack", tiling=(1 / 1.1, 1 / 1.1))
    k = N(pipe_big)
    graffiti(k, G["cope"], 2.6, -2.6, 0.45, 2.9, 0.45, 0.0, 0.25)
    parts = []
    P1, P2, P3 = (1.2, 1.4, 0.9), (3.4, 1.0, 0.6), (1.5, 3.45, 0.42)
    g = Geo()
    pipe_run(g, [(P1[0], y0, P1[1]), (P1[0], y1, P1[1])], P1[2], pipe_big, sides=12, arc=FRONT)
    pipe_run(g, [(P2[0], y0, P2[1]), (P2[0], y1, P2[1])], P2[2], M["pipe"], sides=9, arc=FRONT)
    for yy in (y0, y1):  # blind flanges on the ends
        g.tube([(P1[0], yy - 0.08, P1[1]), (P1[0], yy + 0.08, P1[1])], P1[2] * 1.16, 14, M["rust"], caps=(True, True))
        g.tube([(P2[0], yy - 0.07, P2[1]), (P2[0], yy + 0.07, P2[1])], P2[2] * 1.2, 12, M["rust"], caps=(True, True))
    flange(g, (P3[0], y0, P3[1]), (0, 1, 0), P3[2] * 1.25, M["rust"], length=0.12)
    riser = [(P3[0], y0, P3[1])] + [(P3[0], y, P3[1]) for y in stations(y0, 5.6, 1.0)[1:]]
    riser += [(P3[0], 5.6 + 0.8 * math.sin(t), P3[1] + 0.8 * (1 - math.cos(t))) for t in np.linspace(0.2, math.pi / 2, 5)]
    riser += [(P3[0], 6.4, z) for z in (5.5, 8.0, 11.0)]
    g.tube(riser, P3[2], 10, M["pipe"], phase=math.pi / 2, v_len=1.0)
    for yf in (-2.2, 2.2):
        flange(g, (P1[0], yf, P1[1]), (0, 1, 0), P1[2] * 1.16, M["rust"], length=0.2, bolts=8, bolt_r=0.05)
        flange(g, (P2[0], yf, P2[1]), (0, 1, 0), P2[2] * 1.2, M["rust"], length=0.16)
    flange(g, (P3[0], -0.5, P3[1]), (0, 1, 0), P3[2] * 1.25, M["rust"], length=0.14)
    yv = 3.6
    g.tube([(P2[0], yv, P2[1] + P2[2] - 0.05), (P2[0], yv, P2[1] + P2[2] + 0.35)], 0.12, 8, M["steel"], caps=(False, True))
    g.box((P2[0] - 0.22, yv - 0.14, P2[1] + P2[2] + 0.15), (P2[0] + 0.22, yv + 0.14, P2[1] + P2[2] + 0.42), M["valve"])
    handwheel(g, (P2[0], yv, P2[1] + P2[2] + 0.72), (0, 0, 1), 0.42, M["valve"])
    parts.append(weight(g.obj("pr_pipes", smooth_angle=40), 0.6))
    # frames: H columns to the depths, beams and saddles
    for zlo, zhi, w in ((SPLIT, 4.3, 0.6), (DEEP, SPLIT, 0.03)):
        g = Geo()
        for yf in (-4.4, 0.0, 4.4):
            for xc in (0.22, 4.28):
                g.box((xc - 0.22, yf - 0.22, zlo), (xc + 0.22, yf + 0.22, zhi), M["steel"], skip=("-z",) + (() if zhi == 4.3 else ("+z",)))
        if zlo < SPLIT:  # X bracing between the column pairs, down into the dark
            for yf in (-4.4, 0.0, 4.4):
                for zb in (-4.0, -9.0, -14.0):
                    g.tube([(0.22, yf, zb), (4.28, yf, zb - 4.6)], 0.07, 4, M["steel"])
                    g.tube([(0.22, yf, zb - 4.6), (4.28, yf, zb)], 0.07, 4, M["steel"])
                    g.box((0.0, yf - 0.1, zb), (4.5, yf + 0.1, zb + 0.18), M["steel"])
        parts.append(weight(g.obj("pr_cols", smooth_angle=30), w))
    g = Geo()
    for yf in (-4.4, 0.0, 4.4):
        g.box((0.0, yf - 0.14, 0.3), (4.5, yf + 0.14, 0.45), M["steel"])
        g.box((0.0, yf - 0.12, 2.86), (4.5, yf + 0.12, 3.0), M["steel"])
        g.box((P1[0] - 0.5, yf - 0.12, 0.45), (P1[0] + 0.5, yf + 0.12, P1[1] - P1[2] + 0.1), M["steel"], skip=("-z",))
        g.box((P2[0] - 0.35, yf - 0.1, 0.4), (P2[0] + 0.35, yf + 0.1, P2[1] - P2[2] + 0.06), M["steel"], skip=("-z",))
    parts.append(weight(g.obj("pr_beams", smooth_angle=30), 0.6))
    g = Geo()
    g.tube([(P1[0] - 0.1, 2.35, P1[1] - P1[2] * 0.9), (P1[0] - 0.12, 2.4, P1[1] - P1[2] - 0.6), (P1[0] - 0.13, 2.42, -6.0),
            (P1[0] - 0.13, 2.42, DEEP)], 0.05, 5, M["sludge"], radii=[0.09, 0.05, 0.035, 0.03])
    parts.append(g.obj("pr_leak", smooth_angle=60))
    return parts, dict(slot="mid", every=18.0, chance=0.55, side="both")


def side_sludge(G):
    """An open sludge channel: concrete lip and railing, glossy toxic
    liquid, a graffitied brick back wall with an outfall pouring in, a
    phone and a downvote floating."""
    M = MATS
    y0, y1 = -6.6, 6.6
    ys = stations(y0, y1, 1.0)
    brick = brick_material("BrickChannel", graffitis=[(G["touchgrass"], 4.2, -3.4, 0.05, 2.35)], splash=-0.4,
                           halos=[((3.2, -3.6, 0.2), 2.6, "#3cff2e", 0.3)], waterline=-0.6)
    parts = []
    concrete_block(0.0, 0.5, y0, y1, -0.45, parts, hi=0.6, name="sl_lip")
    g = Geo()
    zs = -1.15
    g.box((0.5, y0, zs - 0.3), (3.4, y1, zs), M["sludge"], skip=("-z", "-x", "+x", "-y", "+y"), ys=ys)
    parts.append(g.obj("sl_surface"))
    for zlo, ztop, w in ((SPLIT, 2.7, 1.0), (DEEP, SPLIT, 0.03)):
        g = Geo()
        g.box((3.4, y0, zlo), (3.95, y1, ztop), brick, skip=("-z", "+x", "+z"), ys=ys)
        parts.append(weight(g.obj("sl_back", smooth_angle=30), w))
    g = Geo()
    g.box((3.3, y0 - 0.05, 2.7), (4.05, y1 + 0.05, 2.95), M["concrete"], skip=("-z", "+x"), ys=stations(y0 - 0.05, y1 + 0.05, 1.0))
    g.box((0.5, y0, zs - 0.02), (0.5, y1, -0.45), M["concrete"], skip=("-z", "+z", "-y", "+y", "-x"), ys=ys)
    parts.append(weight(g.obj("sl_cap", smooth_angle=30), 0.8))
    for zlo, zhi, w in ((SPLIT, zs, 0.5), (DEEP, SPLIT, 0.02)):
        g = Geo()
        for yy, want in ((y0, -1), (y1, 1)):  # close the channel body's ends
            g.face_out([(0.5, yy, zlo), (3.4, yy, zlo), (3.4, yy, zhi), (0.5, yy, zhi)], M["concrete"], (0, want, 0))
        parts.append(weight(g.obj("sl_ends", smooth_angle=30), w))
    g = Geo()
    block_front(g, y0, y1, -0.45)
    parts.append(weight(g.obj("sl_front", smooth_angle=40), 0.6))
    # outfall through the back wall and its pour
    g = Geo()
    yo, zo = -4.2, 1.0
    g.tube([(4.3, yo, zo), (2.75, yo, zo)], 0.46, 12, M["pipe"], phase=0.0, v_len=1.0)
    flange(g, (3.1, yo, zo), (1, 0, 0), 0.58, M["rust"], length=0.12)
    parts.append(weight(g.obj("sl_outfall", smooth_angle=40), 0.9))
    g = Geo()
    g.tube([(2.75, yo, zo), (2.75, yo, zo - 0.0001)], 0.4, 12, M["dark"], caps=(False, True))
    parts.append(weight(g.obj("sl_hole"), 0.05))
    g = Geo()
    pour = [(2.78, yo, zo - 0.22), (2.45, yo, zo - 0.4), (2.2, yo, zo - 1.0), (2.05, yo, zs + 0.05)]
    g.tube(pour, 0.25, 8, M["sludge"], radii=[0.26, 0.24, 0.26, 0.4])
    parts.append(g.obj("sl_pour", smooth_angle=60))
    # railing on the lip
    g = Geo()
    for yp in (-6.0, -3.0, 0.0, 3.0, 6.0):
        g.tube([(0.25, yp, -0.45), (0.25, yp, 0.55)], 0.035, 6, M["steel"])
    pipe_run(g, [(0.25, y0, 0.55), (0.25, y1, 0.55)], 0.04, M["steel"], sides=6)
    pipe_run(g, [(0.25, y0, 0.05), (0.25, y1, 0.05)], 0.03, M["steel"], sides=6)
    parts.append(weight(g.obj("sl_rail", smooth_angle=40), 0.9))
    g, gs = Geo(), Geo()
    phone(g, place(1.6, 1.6, zs + 0.02, rz=28, rx=3), screen_material("ScreenSludge", 21, lit=0.8, impact=(0.6, 0.7)),
          w=1.1, h=2.3, t=0.1, gs=gs)
    parts.append(weight(gs.obj("sl_screen", smooth_angle=35), 4.0))
    downvote(g, place(2.6, 4.2, zs + 0.03, rz=-40, rx=8), M["downvote"], t=0.28)
    parts.append(weight(g.obj("sl_float", smooth_angle=35), 0.8))
    return parts, dict(slot="mid", every=22.0, chance=0.5, side="both")


def side_phones(G):
    """A concrete landing with a glowing floor grate and giant discarded
    phones, cracked, one still on."""
    M = MATS
    y0, y1, top = -4.2, 4.2, -0.3
    plat = mat.pbr("Platform", "Concrete044D", mapping="BOX", box_scale=2.0, wet=0.5, value=0.62, saturation=0.5,
                   normal_strength=0.0, bump=0.35, bump_distance=0.02)
    k = grime(plat, splash=-0.6, depth=-2.0, streaks=0.7, algae=0.5, salts=0.25, wet_top=1.0)
    x, y, z = k.xyz()
    gx = k.mul(k.smooth(x, 2.0, 2.05), k.smooth(x, 4.45, 4.4))
    gy = k.mul(k.smooth(y, -1.25, -1.2), k.smooth(y, 1.25, 1.2))
    _, _, nz = k.nrm()
    area = k.mul(k.mul(gx, gy), k.smooth(nz, 0.5, 0.8))
    bar = k.smooth(k.math("FRACT", k.math("DIVIDE", y, 0.16)), 0.62, 0.66)
    frame = k.sub(1.0, k.mul(k.mul(k.smooth(x, 2.1, 2.12), k.smooth(x, 4.35, 4.33)),
                             k.mul(k.smooth(y, -1.15, -1.13), k.smooth(y, 1.15, 1.13))), clamp=True)
    metal = k.add(k.sub(1.0, bar, clamp=True), frame, clamp=True)
    hole = k.mul(area, k.sub(1.0, metal, clamp=True))
    k.set("Base Color", k.mixc(k.mixc(k.src("Base Color"), "#2a211c", k.mul(area, metal)), "#010301", hole))
    k.set("Roughness", k.mixf(k.src("Roughness"), 0.6, area))
    k.set("Metallic", k.mixf(0.0, 0.6, k.mul(area, metal)))
    k.emit("#4dff3a", k.mul(hole, 2.2))
    halo(k, (3.2, 0.0, top + 0.3), 3.0, "#3cff2e", 0.25)
    parts = []
    concrete_block(0.0, 6.5, y0, y1, top, parts, m=plat, hi=0.5, name="ph_plat")
    g = Geo()
    block_front(g, y0, y1, top, seed=3)
    parts.append(weight(g.obj("ph_front", smooth_angle=40), 0.6))
    g, gs = Geo(), Geo()
    phone(g, place(1.3, -2.5, top + 0.06, rz=24), screen_material("ScreenA", 31, lit=1.0, impact=(0.35, 0.3)), gs=gs)
    phone(g, place(4.9, 1.9, top + 1.25, rz=90, rx=-80, ry=4), screen_material("ScreenB", 32, lit=0.0, impact=(0.7, 0.55)), gs=gs)
    phone(g, place(3.9, 1.7, top + 0.9, rz=75, rx=-38), screen_material("ScreenC", 33, lit=0.45, impact=(0.5, 0.8)), gs=gs)
    phone(g, place(3.2, -1.9, top + 0.07, rz=-12, rx=180), screen_material("ScreenD", 34, lit=0.0), gs=gs)
    parts.append(weight(g.obj("ph_phones", smooth_angle=35), 0.9))
    parts.append(weight(gs.obj("ph_screens", smooth_angle=35), 4.0))
    # a white charging cable snaking across the landing
    g = Geo()
    rng = random.Random(8)
    pts = [(0.7, 3.4, top + 0.05)]
    for i in range(14):
        px, py, pz = pts[-1]
        pts.append((px + 0.35 + rng.uniform(-0.1, 0.1), py - 0.45 + rng.uniform(-0.3, 0.3), top + 0.05))
    g.tube(pts, 0.05, 6, M["cable"])
    g.box((pts[-1][0] - 0.1, pts[-1][1] - 0.2, top), (pts[-1][0] + 0.1, pts[-1][1] + 0.05, top + 0.1), M["phone_frame"])
    parts.append(weight(g.obj("ph_cable", smooth_angle=50), 0.5))
    return parts, dict(slot="mid", every=30.0, chance=0.4, side="both")


def side_downvotes(G):
    """A giant pile of downvote arrows rotting in a sludge pool on a pier."""
    M = MATS
    y0, y1, top = -3.9, 3.9, -1.0
    parts = []
    concrete_block(0.0, 6.6, y0, y1, top, parts, hi=0.5, name="dv_pier", top_face=False)
    g = Geo()
    block_front(g, y0, y1, top, seed=5)
    parts.append(weight(g.obj("dv_front", smooth_angle=40), 0.6))
    g = Geo()
    g.box((0.0, y0, top), (6.6, y1, top + 0.06), M["sludge"], skip=("-z", "+x"), ys=stations(y0, y1, 1.0))
    parts.append(g.obj("dv_pool"))
    g = Geo()
    rng = random.Random(21)
    cx, cy = 3.4, 0.0
    for i in range(12):  # the heap: arrows lying every which way
        a = rng.uniform(0, 2 * math.pi)
        r = math.sqrt(rng.uniform(0, 1))
        px, py = cx + math.cos(a) * r * 2.5, cy + math.sin(a) * r * 2.9
        h = (1 - r) * 1.6 + rng.uniform(-0.15, 0.2)
        s = rng.uniform(1.15, 1.6)
        downvote(g, place(px, py, top + 0.2 + max(0.0, h), rz=rng.uniform(0, 360), rx=rng.uniform(-30, 30),
                          ry=rng.uniform(-25, 25), s=s), M["downvote"])
    for i in range(7):  # arrows planted tip-down in it, facing the track: they read as downvotes
        a = rng.uniform(0, 2 * math.pi)
        r = math.sqrt(rng.uniform(0.1, 0.8))
        px, py = cx + math.cos(a) * r * 2.3, cy + math.sin(a) * r * 2.6
        s = rng.uniform(1.1, 1.5)
        downvote(g, place(px, py, top + 0.9 + (1 - r) * 1.2, rz=-90 + rng.uniform(-45, 45), rx=90 + rng.uniform(-12, 12),
                          ry=rng.uniform(-22, 22), s=s), M["downvote"])
    downvote(g, place(cx - 0.2, 0.3, top + 3.9, rz=-90, rx=90, ry=12, s=2.1), M["downvote"], t=0.4)  # the monument
    parts.append(weight(g.obj("dv_pile", smooth_angle=35), 0.5))
    return parts, dict(slot="mid", every=36.0, chance=0.35, side="both")


def side_pillar(G):
    """A colossal brick pillar of the vault, arch springers into the dark,
    a riser pipe, caged lights, a giant 'L'."""
    M = MATS
    X, Yh, top = 5.6, 2.8, 46.0
    lamps = [(0.0, -1.7, 9.0), (0.0, -0.5, 19.5)]
    brick = brick_material("BrickPillar", graffitis=[(G["L"], 1.3, -2.6, 2.2, 6.1), (G["logoff"], 1.4, -2.7, 10.4, 12.0)],
                           halos=[((-0.2, l[1], l[2]), 4.0, "#b8ffcc", 0.55) for l in lamps], splash=0.4,
                           box=(4.4, 4.4, 2.2))
    parts = []
    for zlo, zhi, w in ((SPLIT, 14.0, 0.28), (14.0, top, 0.07), (DEEP, SPLIT, 0.015)):
        g = Geo()
        g.box((0.0, -Yh, zlo), (X, Yh, zhi), brick, skip=("-z", "+x", "+z"), ys=stations(-Yh, Yh, 1.0))
        parts.append(weight(g.obj("pl_body", smooth_angle=30), w))
    g = Geo()
    g.box((-0.35, -Yh - 0.35, -1.6), (X, Yh + 0.35, 0.3), M["concrete"], skip=("-z", "+x", "+z"), ys=stations(-Yh - 0.35, Yh + 0.35, 1.0))
    g.box((-0.25, -Yh - 0.25, 14.0), (X, Yh + 0.25, 14.9), M["concrete"], skip=("+x", "+z", "-z"), ys=stations(-Yh - 0.25, Yh + 0.25, 1.0))
    parts.append(weight(g.obj("pl_bands", smooth_angle=30), 0.28))
    g = Geo()
    g.box((-0.25, -Yh - 0.25, 28.0), (X, Yh + 0.25, 28.9), M["concrete"], skip=("+x", "+z", "-z"), ys=stations(-Yh - 0.25, Yh + 0.25, 1.0))
    g.box((-0.6, -Yh - 0.6, top), (X, Yh + 0.6, top + 2.0), M["concrete"], skip=("-z", "+x", "+z"), ys=stations(-Yh - 0.6, Yh + 0.6, 1.0))
    parts.append(weight(g.obj("pl_bands_hi", smooth_angle=30), 0.07))
    g = Geo()
    xr, yr = -0.8, 2.05
    g.tube([(xr, yr, SPLIT), (xr, yr, 0.0)] + [(xr, yr, z) for z in (8.0, 16.0)], 0.7, 10, M["pipe"], phase=0.0, v_len=1.0)
    for zf in (1.5, 9.5):
        flange(g, (xr, yr, zf), (0, 0, 1), 0.84, M["rust"], length=0.2)
    parts.append(weight(g.obj("pl_pipe", smooth_angle=40), 0.28))
    g = Geo()
    g.tube([(xr, yr, DEEP), (xr, yr, SPLIT)], 0.7, 10, M["pipe"], phase=0.0, v_len=1.0)
    g.tube([(xr, yr, 16.0)] + [(xr, yr, z) for z in (24.0, 32.0, 38.0)] +
           [(xr + 0.8 * (1 - math.cos(t)), yr, 38.0 + 0.8 * math.sin(t)) for t in np.linspace(0.3, math.pi / 2, 4)] +
           [(1.0, yr, 38.8)], 0.7, 10, M["pipe"], phase=0.0, v_len=1.0)
    for zf in (17.5, 25.5, 33.5):
        flange(g, (xr, yr, zf), (0, 0, 1), 0.84, M["rust"], length=0.2)
    parts.append(weight(g.obj("pl_pipe_far", smooth_angle=40), 0.05))
    for i, l in enumerate(lamps):
        fit, tube = cage_light(l, -1, 1.4, f"pl_light{i}")
        parts += [weight(fit, 0.5), tube]
    return parts, dict(slot="far", every=26.0, chance=0.8, side="both")


def side_bigpipe(G):
    """A colossal trunk main on concrete saddles, flanged, leaking green."""
    M = MATS
    y0, y1 = -13.2, 13.2
    R, xc, zc = 2.0, 2.5, 3.6
    big = pipe_paint("PipeTrunk", tiling=(1 / 2.2, 1 / 2.2))
    k = N(big)
    graffiti(k, G["whoasked"], 6.5, -3.0, zc - 1.4, zc + 1.6, 0.45, 0.0, 0.3)
    parts = []
    g = Geo()
    pipe_run(g, [(xc, y0, zc), (xc, y1, zc)], R, big, sides=14, arc=FRONT)
    for yy in (y0 + 0.2, y1 - 0.2):
        g.tube([(xc, yy - 0.2, zc), (xc, yy + 0.2, zc)], R + 0.25, 16, M["rust"], caps=(True, True))
    for yf in (-8.8, 0.0, 8.8):
        flange(g, (xc, yf, zc), (0, 1, 0), R + 0.25, M["rust"], length=0.4, bolts=12, bolt_r=0.09)
    parts.append(weight(g.obj("bp_pipe", smooth_angle=40), 0.25))
    for zlo, zhi, w in ((SPLIT, zc - R + 0.5, 0.3), (DEEP, SPLIT, 0.02)):
        g = Geo()
        for ys_ in (-11.0, -4.4, 4.4, 11.0):
            g.box((xc - 1.7, ys_ - 0.7, zlo), (xc + 1.7, ys_ + 0.7, zhi), M["concrete"], skip=("-z", "+x", "+z"))
        parts.append(weight(g.obj("bp_saddles", smooth_angle=30), w * 0.6))
    g = Geo()
    g.tube([(xc - 0.3, 0.1, zc - R + 0.05), (xc - 0.35, 0.15, zc - R - 1.0), (xc - 0.4, 0.2, -8.0), (xc - 0.4, 0.2, DEEP)],
           0.1, 6, M["sludge"], radii=[0.22, 0.1, 0.08, 0.06])
    parts.append(g.obj("bp_leak", smooth_angle=60))
    return parts, dict(slot="far", every=48.0, chance=0.5, side="both")


PIECES = [("side_wall_pipes", side_wall_pipes), ("side_wall_ladder", side_wall_ladder), ("side_lamp", side_lamp),
          ("side_pipes", side_pipes), ("side_sludge", side_sludge), ("side_phones", side_phones),
          ("side_downvotes", side_downvotes), ("side_pillar", side_pillar), ("side_bigpipe", side_bigpipe)]
SLOTS = {"wall": (4.6, 7.0), "mid": (8.0, 20.0), "far": (20.0, 60.0)}


def build_all(G):
    """{node name: (parts, extras)}; parts are baked separately (their own
    atlas weights) and joined into the node afterwards."""
    want = (lambda n: not ONLY or n in ONLY)
    nodes = {}
    if want("deck"):
        nodes["deck"] = (build_deck(), {})
    if want("deck_seam"):
        nodes["deck_seam"] = ([build_seam()], {})
    if want("tunnel"):
        nodes["tunnel"] = (build_tunnel(), {})
    if want("overhang"):
        nodes["overhang"] = (build_overhang(), {})
    if want("rail_sewer"):
        nodes["rail_sewer"] = (build_rail(), {})
    for name, fn in PIECES:
        if want(name):
            nodes[name] = fn(G)
    return nodes


def max_edge_dy(o):
    me = o.data
    return max((abs(me.vertices[e.vertices[0]].co.y - me.vertices[e.vertices[1]].co.y) for e in me.edges), default=0.0)


def join_node(name, parts):
    for p in parts:
        p.location = (0, 0, 0)
    o = mesh.join(list(parts), name=name)
    mesh.apply_transform(o)
    for key in list(o.keys()):
        del o[key]
    return o


def texel_density(o):
    """Atlas pixels per metre over the atlas faces of `o` (UV area vs 3D)."""
    me = o.data
    uv = me.uv_layers.active
    a3 = auv = 0.0
    for p in me.polygons:
        mname = me.materials[p.material_index].name if p.material_index < len(me.materials) else ""
        if mname in KEEP:
            continue
        a3 += p.area
        pts = [uv.data[li].uv for li in p.loop_indices]
        s = 0.0
        for i in range(len(pts)):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % len(pts)]
            s += x0 * y1 - x1 * y0
        auv += abs(s) / 2
    return math.sqrt(auv * SIZE * SIZE / a3) if a3 > 0 else 0.0


def scenery_estimate(nodes_final, extras):
    total = 0.0
    rows = []
    for name, ex in extras.items():
        if not name.startswith("side_"):
            continue
        t = mesh.tri_count(nodes_final[name])
        sides = 2 if ex["side"] == "both" else 1
        n = 200.0 / ex["every"] * sides * ex["chance"]
        total += n * t
        rows.append((name, t, round(n, 1), int(n * t)))
    return total, rows


def clip_copy(o, zmin):
    """A copy of `o` cut at z = zmin (for previews framed on the visible part)."""
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=(0, 0, zmin), plane_no=(0, 0, 1),
                           clear_inner=True)
    me = bpy.data.meshes.new(o.name + "_clip")
    bm.to_mesh(me)
    bm.free()
    for m in o.data.materials:
        me.materials.append(m)
    c = lib.link(bpy.data.objects.new(o.name.replace("side_", "") + "_clip", me))
    return c


def uv_owner_map(built, path, layer="UVMap", res=768):
    """Rasterise every atlas face's UVs, coloured by node: shows used vs
    wasted atlas space (review only)."""
    img = np.zeros((res, res, 3), np.float32)
    rng = np.random.default_rng(2)
    used = 0
    for name, (parts, _) in built.items():
        if name == "deck_seam":
            continue
        col = rng.uniform(0.25, 1.0, 3)
        for o in parts:
            me = o.data
            uv = me.uv_layers[layer]
            me.calc_loop_triangles()
            for t in me.loop_triangles:
                if me.materials[t.material_index].name in KEEP:
                    continue
                p = np.array([uv.data[li].uv[:] for li in t.loops]) * res
                x0, y0 = np.floor(p.min(0)).astype(int)
                x1, y1 = np.ceil(p.max(0)).astype(int)
                x0, y0 = max(x0, 0), max(y0, 0)
                x1, y1 = min(x1, res - 1), min(y1, res - 1)
                if x1 < x0 or y1 < y0:
                    continue
                yy, xx = np.mgrid[y0:y1 + 1, x0:x1 + 1] + 0.5
                (ax, ay), (bx, by), (cx, cy) = p
                d = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
                if abs(d) < 1e-12:
                    continue
                l1 = ((by - cy) * (xx - cx) + (cx - bx) * (yy - cy)) / d
                l2 = ((cy - ay) * (xx - cx) + (ax - cx) * (yy - cy)) / d
                inside = (l1 >= 0) & (l2 >= 0) & (l1 + l2 <= 1)
                img[y0:y1 + 1, x0:x1 + 1][inside] = col
    used = float((img.sum(-1) > 0).mean())
    out = np.ones((res, res, 4), np.float32)
    out[..., :3] = img
    save_np_png(out, path)
    log(f"uv map: {path} ({used * 100:.0f}% of the atlas covered)")


# ------------------------------------------------------------------ game view (in-game look, fog, bloom, ACES)

def _aces(c, exposure):
    c = c * exposure / 0.6
    A = np.array([[0.59719, 0.35458, 0.04823], [0.07600, 0.90834, 0.01566], [0.02840, 0.13383, 0.83777]])
    B = np.array([[1.60475, -0.53108, -0.07367], [-0.10208, 1.10813, -0.00605], [-0.00327, -0.07276, 1.07602]])
    v = c @ A.T
    a = v * (v + 0.0245786) - 0.000090537
    b = v * (0.983729 * v + 0.4329510) + 0.238081
    return np.clip((a / b) @ B.T, 0, 1)


def _load_exr(path):
    img = bpy.data.images.load(path, check_existing=False)
    a = np.empty(img.size[0] * img.size[1] * 4, np.float32)
    img.pixels.foreach_get(a)
    out = a.reshape(img.size[1], img.size[0], 4)
    bpy.data.images.remove(img)
    return out


def _bloom(c, strength=0.6, threshold=0.82):
    lum = c[..., 0] * 0.2126 + c[..., 1] * 0.7152 + c[..., 2] * 0.0722
    bright = c * smoothstep(threshold, threshold + 0.01, lum)[..., None]
    h, w = lum.shape
    acc = np.zeros_like(c)
    for sig, wgt in ((w / 180, 1.0), (w / 90, 0.8), (w / 45, 0.6), (w / 22, 0.4), (w / 11, 0.2)):
        acc += np.stack([blur(bright[..., i], sig) for i in range(3)], -1) * wgt
    return c + acc * strength / 3.0


def world_game(sky_img):
    """World like the game: the camera sees the panorama; lighting sees the
    hemisphere light (as radiance a + b*z) plus env * panorama."""
    w = bpy.data.worlds.new("_game_world")
    nt = w.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    lp = nt.nodes.new("ShaderNodeLightPath")
    mix = nt.nodes.new("ShaderNodeMixShader")
    bg_cam = nt.nodes.new("ShaderNodeBackground")
    bg_lit = nt.nodes.new("ShaderNodeBackground")
    I = LOOK["hemi"]
    s, gcol = np.array(mat.rgb(LOOK["hemi_sky"])), np.array(mat.rgb(LOOK["hemi_ground"]))
    a_ = I * (s + gcol) / (2 * math.pi)
    b_ = 3 * I * (s - gcol) / (4 * math.pi)
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Generated"], sep.inputs[0])
    hemi = nt.nodes.new("ShaderNodeMix")
    hemi.data_type = "RGBA"
    hemi.clamp_factor = False
    mr = nt.nodes.new("ShaderNodeMapRange")
    mr.inputs["From Min"].default_value = -1
    mr.inputs["From Max"].default_value = 1
    mr.clamp = True
    nt.links.new(sep.outputs[2], mr.inputs["Value"])
    nt.links.new(mr.outputs[0], hemi.inputs[0])
    hemi.inputs[6].default_value = (*np.maximum(a_ - b_, 0), 1)
    hemi.inputs[7].default_value = (*(a_ + b_), 1)
    if sky_img is not None:
        env = nt.nodes.new("ShaderNodeTexEnvironment")
        env.image = sky_img
        mp = nt.nodes.new("ShaderNodeMapping")
        mp.inputs["Rotation"].default_value = (0, 0, math.radians(-90))
        nt.links.new(tc.outputs["Generated"], mp.inputs["Vector"])
        nt.links.new(mp.outputs[0], env.inputs["Vector"])
        pano = env.outputs["Color"]
        add = nt.nodes.new("ShaderNodeMix")
        add.data_type = "RGBA"
        add.blend_type = "ADD"
        add.inputs[0].default_value = LOOK["env"]
        nt.links.new(hemi.outputs[2], add.inputs[6])
        nt.links.new(pano, add.inputs[7])
        nt.links.new(add.outputs[2], bg_lit.inputs["Color"])
        nt.links.new(pano, bg_cam.inputs["Color"])
    else:
        nt.links.new(hemi.outputs[2], bg_lit.inputs["Color"])
        bg_cam.inputs["Color"].default_value = mat.rgba(LOOK["sky"])
    nt.links.new(lp.outputs["Is Camera Ray"], mix.inputs[0])
    nt.links.new(bg_lit.outputs[0], mix.inputs[1])
    nt.links.new(bg_cam.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])
    return w


def game_view(nodes, extras, path, size=(540, 1170), fov=70.0, seed=3, tunnel=(16, 27), camera=None, look=None,
              runner=True, exposure_mul=1.0):
    """Render the kit like the game: 150 m of deck with scenery placed from
    the extras (the renderer's rules), a tunnel, an overhang, a rail, the
    lane screens, fog, bloom and ACES. Blender +Y = forward."""
    sc = bpy.context.scene
    col = lib.collection("_game")
    added = []

    def dup(name, x, y, z=0.0, rz=0.0, s=1.0, sy=1.0):
        src = nodes.get(name)
        if src is None:
            return None
        o = bpy.data.objects.new(name + "_g", src.data)
        col.objects.link(o)
        o.location = (x, y, z)
        o.rotation_euler = (0, 0, rz)
        o.scale = (s, s * sy, s)
        added.append(o)
        return o

    hidden = {o: o.hide_render for o in sc.objects}
    for o in sc.objects:
        o.hide_render = True
    t0, t1 = tunnel
    ty0, ty1 = t0 * ROW, (t1 + 1) * ROW
    for i in range(-3, 37):
        yc = 2.2 + ROW * i
        dup("deck", 0, yc)
        dup("deck_seam", 0, yc)
        if t0 <= i <= t1:
            dup("tunnel", 0, yc)
    dup("overhang", 0, 30.8)
    dup("overhang", 0, ty0 + 30.8)
    for yy in range(46, 70):
        dup("rail_sewer", LANE, yy)
    rng = random.Random(seed)
    for name, ex in extras.items():
        if not name.startswith("side_"):
            continue
        every, chance = ex["every"], ex["chance"]
        lo, hi = SLOTS[ex["slot"]]
        jitter = ex["slot"] != "wall"
        sides = {"both": (-1, 1), "left": (-1,), "right": (1,)}[ex["side"]]
        for i in range(math.floor(-20 / every), math.ceil(210 / every) + 1):
            s0 = i * every
            if ty0 - 2 <= s0 <= ty1 + 2:
                continue
            for side in sides:
                if rng.random() >= chance:
                    continue
                s_ = s0 + (rng.random() - 0.5) * every * 0.6
                x = side * (lo + (hi - lo) * rng.random())
                yaw = (0 if side > 0 else math.pi) + ((rng.random() - 0.5) * 0.5 if jitter else 0)
                k = 0.85 + 0.35 * rng.random() if jitter else 1.0
                dup(name, x, s_, 0, yaw, k)
    # lane screens (the renderer's feed tiles), a stand-in runner
    feed = feed_image()
    fm = mat.flat("_feed", "#000000", rough=0.5)
    k = N(fm)
    info = k.n("ShaderNodeObjectInfo")
    uvn = k.n("ShaderNodeUVMap", uv_map="UVMap")
    sepu = k.n("ShaderNodeSeparateXYZ")
    k.link(uvn.outputs["UV"], sepu.inputs[0])
    t = k.image(feed, k.vec(sepu.outputs[0], k.math("FRACT", k.add(sepu.outputs[1], info.outputs["Random"]))))
    k.emit(k.mulc(t.outputs["Color"], (0.55, 0.55, 0.6), 1.0), 1.0)
    g = Geo()
    g.face([(-SCREEN_W / 2, -SCREEN_L / 2, 0), (SCREEN_W / 2, -SCREEN_L / 2, 0), (SCREEN_W / 2, SCREEN_L / 2, 0),
            (-SCREEN_W / 2, SCREEN_L / 2, 0)], fm, [(0, 0), (1, 0), (1, 1), (0, 1)])
    scr = g.obj("_screen")
    scr.hide_render = True
    for i in range(-3, 37):
        for lane in (-1, 0, 1):
            o = bpy.data.objects.new("_scr", scr.data)
            col.objects.link(o)
            o.location = (lane * LANE, 2.2 + ROW * i, 0.011)
            added.append(o)
    helpers = [scr]
    if runner:
        g = Geo()
        body = mat.flat("_runner", "#101014", rough=0.6)
        glow = mat.flat("_phone", "#ffffff", emission="#cfe8ff", strength=4.0)
        g.tube([(0, 0, 0.1), (0, 0, 0.9), (0, 0, 1.45)], 0.2, 12, body, caps=(True, True), radii=[0.12, 0.22, 0.2])
        g.tube([(0, 0.02, 1.52), (0, 0.02, 1.78)], 0.13, 12, body, caps=(True, True))
        g.box((-0.06, 0.3, 1.18), (0.06, 0.32, 1.38), glow)
        r = g.obj("_runnerobj", smooth_angle=60)
        helpers.append(r)
    cam_d = bpy.data.cameras.new("_gcam")
    cam_d.sensor_fit = "VERTICAL"
    cam_d.angle_y = math.radians(fov)
    cam_d.clip_start = 0.1
    cam_d.clip_end = 220
    cam = lib.link(bpy.data.objects.new("_gcam", cam_d))
    cpos = Vector(camera or (0.0, -6.4, 3.5))
    target = Vector(look or (0.0, 9.0, 1.1))
    cam.location = cpos
    cam.rotation_euler = (target - cpos).to_track_quat("-Z", "Y").to_euler()
    sun_d = bpy.data.lights.new("_gsun", "SUN")
    sun_d.energy = LOOK["sunI"]
    sun_d.color = mat.rgb(LOOK["sun"])
    sun_d.use_shadow = False
    sun = lib.link(bpy.data.objects.new("_gsun", sun_d))
    sun.rotation_euler = (Vector((0, 0, 0)) - Vector((4, -6, 10))).to_track_quat("-Z", "Y").to_euler()
    helpers += [cam, sun]
    sky_img = bpy.data.images.load(SKY_OUT, check_existing=True) if os.path.exists(SKY_OUT) else None
    wgame = world_game(sky_img)
    saved = dict(world=sc.world, camera=sc.camera, engine=sc.render.engine, x=sc.render.resolution_x,
                 y=sc.render.resolution_y, vt=sc.view_settings.view_transform, look=sc.view_settings.look)
    sc.world = wgame
    sc.camera = cam
    sc.render.engine = "BLENDER_EEVEE"
    sc.eevee.taa_render_samples = 32
    if hasattr(sc.eevee, "use_raytracing"):
        sc.eevee.use_raytracing = True
    sc.render.resolution_x, sc.render.resolution_y = size
    sc.render.resolution_percentage = 100
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    sc.render.image_settings.file_format = "OPEN_EXR"
    sc.render.image_settings.color_depth = "32"
    base = os.path.splitext(path)[0]
    sc.render.filepath = base + "_beauty.exr"
    bpy.ops.render.render(write_still=True)
    # depth pass: every surface emits its view depth; the sky stays 0 (unfogged, like the dome)
    dm = bpy.data.materials.new("_depth")
    nt = dm.node_tree
    nt.nodes.clear()
    o_ = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    cd = nt.nodes.new("ShaderNodeCameraData")
    nt.links.new(cd.outputs["View Z Depth"], em.inputs["Strength"])
    em.inputs["Color"].default_value = (1, 1, 1, 1)
    nt.links.new(em.outputs[0], o_.inputs["Surface"])
    wblack = bpy.data.worlds.new("_black")
    wblack.node_tree.nodes["Background"].inputs["Color"].default_value = (0, 0, 0, 1)
    sc.world = wblack
    vl = bpy.context.view_layer
    vl.material_override = dm
    sc.eevee.taa_render_samples = 8
    sc.render.filepath = base + "_depth.exr"
    bpy.ops.render.render(write_still=True)
    vl.material_override = None
    beauty = _load_exr(base + "_beauty.exr")[..., :3]
    depth = _load_exr(base + "_depth.exr")[..., 0]
    f = np.where(depth > 0.01, smoothstep(LOOK["fog"][0], LOOK["fog"][1], depth), 0.0)[..., None]
    fogc = np.array(mat.rgb(LOOK["sky"]), np.float32)
    c = beauty * (1 - f) + fogc * f
    c = _bloom(c)
    c = to_srgb(_aces(c, LOOK["exposure"] * exposure_mul))
    out = np.ones((c.shape[0], c.shape[1], 4), np.float32)
    out[..., :3] = c
    save_np_png(out, path)
    for p in (base + "_beauty.exr", base + "_depth.exr"):
        os.remove(p)
    # restore
    sc.world = saved["world"]
    sc.camera = saved["camera"]
    sc.render.engine = saved["engine"]
    sc.render.resolution_x, sc.render.resolution_y = saved["x"], saved["y"]
    sc.view_settings.view_transform = saved["vt"]
    sc.view_settings.look = saved["look"]
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_depth = "8"
    for o in added:
        bpy.data.objects.remove(o, do_unlink=True)
    for o in helpers:
        bpy.data.objects.remove(o, do_unlink=True)
    for o, h in hidden.items():
        o.hide_render = h
    bpy.data.worlds.remove(wgame)
    bpy.data.worlds.remove(wblack)
    log(f"game view: {path}")
    return path


# ------------------------------------------------------------------ sky: the underground vault

def build_sky():
    """Cycles equirect panorama of the vault the track runs through: brick
    groin-vault ceiling far above, colossal pillars, trunk mains, green
    lamps in mist, fading to the fog colour below the horizon."""
    lib.reset_scene()
    sc = bpy.context.scene
    bake.setup_cycles(SKY_SAMPLES)
    sc.cycles.use_denoising = True
    sc.cycles.max_bounces = 4
    sc.cycles.volume_bounces = 1
    sc.cycles.transparent_max_bounces = 2
    brick = mat.pbr("SkyBrick", "Bricks097", mapping="BOX", box_scale=(9, 9, 4.5), value=0.35, saturation=0.5,
                    normal_strength=0.0, bump=0.6, bump_distance=0.3)
    grime(brick, splash=-5, depth=-30, streaks=0.9, algae=0.4, salts=0.3, streak_scale=0.15)
    conc = mat.pbr("SkyConc", "Concrete044D", mapping="BOX", box_scale=8, value=0.4, saturation=0.4,
                   normal_strength=0.0, bump=0.5, bump_distance=0.2)
    grime(conc, splash=-5, depth=-30, streaks=0.9, algae=0.3, salts=0.2, streak_scale=0.15)
    pipe = mat.pbr("SkyPipe", "PaintedMetal006", mapping="BOX", box_scale=6, value=0.3, saturation=0.4)
    lamp = mat.flat("SkyLamp", "#d0ffd8", emission="#9dffb0", strength=30.0)
    lampw = mat.flat("SkyLampW", "#ffffff", emission="#e8fff0", strength=18.0)
    grate = mat.flat("SkyGrate", "#0a1a08", emission="#8dff7a", strength=10.0)
    sludge = mat.flat("SkySludge", "#06200a", rough=0.08, emission="#2cff3a", strength=0.4)
    fall = mat.flat("SkyFall", "#0a3a0c", emission="#3dff45", strength=6.0)
    rng = random.Random(77)
    CEIL, BAY = 62.0, 34.0
    g = Geo()
    # pillar grid (the track runs in a clear aisle |x| < 45 between them)
    pillars = []
    for ix in range(-7, 8):
        for iy in range(-6, 22):
            x, y = ix * BAY + BAY / 2, iy * BAY
            if abs(x) < 45 or math.hypot(x, y) > 700:
                continue
            pillars.append((x, y))
            h = 4.2
            g.box((x - h, y - h, -80), (x + h, y + h, CEIL - 6), brick)
            g.box((x - h - 1, y - h - 1, CEIL - 6), (x + h + 1, y + h + 1, CEIL - 3), conc)
            g.box((x - h - 0.8, y - h - 0.8, -6), (x + h + 0.8, y + h + 0.8, -3), conc)
    # barrel vaults along Y over each aisle of bays, transverse arches at pillar rows
    for ix in range(-7, 7):
        xa = ix * BAY + BAY / 2
        xb = xa + BAY
        cx = (xa + xb) / 2
        r = BAY / 2
        prof = [(cx + r * math.cos(t), CEIL + r * 0.55 * math.sin(t)) for t in np.linspace(0, math.pi, 13)]
        g.sweep(prof[::-1], [-250, 800], brick, 5, 5)
    for iy in range(-6, 22):
        y = iy * BAY
        for ix in range(-7, 7):
            xa = ix * BAY + BAY / 2
            cx, r = xa + BAY / 2, BAY / 2
            ring = [(cx + (r - 2.5) * math.cos(t), CEIL - 1 + (r - 2.5) * 0.55 * math.sin(t)) for t in np.linspace(0, math.pi, 13)]
            rows = [[(px, y - 1.8, pz) for px, pz in ring], [(px, y + 1.8, pz) for px, pz in ring]]
            g.grid(rows, brick)
            g.grid([[(px, y - 1.8, pz) for px, pz in ring[::-1]], [(px, y - 1.8, pz + 3.0) for px, pz in ring[::-1]]], brick)
    # side walls of the aisle far out
    for sx in (-1, 1):
        g.face([(sx * 260, -300, -80), (sx * 260, 900, -80), (sx * 260, 900, CEIL + 20), (sx * 260, -300, CEIL + 20)], brick)
    # colossal pipes: two trunk mains along the aisle up high, some crossing
    for sx in (-1, 1):
        g.tube([(sx * 40, -300, 44), (sx * 40, 900, 44)], 4.5, 20, pipe)
        g.tube([(sx * 30, -300, 30), (sx * 30, 900, 30)], 2.2, 16, pipe)
    for y in (140, 330, 520):
        g.tube([(-300, y, 50 + rng.uniform(-4, 4)), (300, y, 50 + rng.uniform(-4, 4))], 3.2, 18, pipe)
    # green lamps on some pillars, a few white strips, grates of light in the vault
    for (x, y) in pillars:
        if rng.random() < 0.45:
            side = -1 if x > 0 else 1
            z = rng.uniform(12, 30)
            g.box((x + side * 4.25 - 0.3, y - 0.9, z - 0.25), (x + side * 4.25 + 0.3, y + 0.9, z + 0.25), lamp)
            L = bpy.data.lights.new("_skyL", "POINT")
            L.energy = rng.uniform(2500, 9000)
            L.color = mat.rgb("#6dff82" if rng.random() < 0.7 else "#d4ffe0")
            L.shadow_soft_size = 0.8
            lo = lib.link(bpy.data.objects.new("_skyL", L))
            lo.location = (x + side * 5.4, y, z)
    for (x, y) in ((-70, 90), (95, 230), (-120, 380), (60, 520), (-40, 700)):
        zc = CEIL + 4.0
        g.face_out([(x - 3, y - 3, zc), (x + 3, y - 3, zc), (x + 3, y + 3, zc), (x - 3, y + 3, zc)], grate, (0, 0, -1))
        S = bpy.data.lights.new("_skyS", "SPOT")
        S.energy = 5.0e6
        S.color = mat.rgb("#b4ffc0")
        S.spot_size = math.radians(24)
        S.spot_blend = 0.5
        S.shadow_soft_size = 2.5
        so = lib.link(bpy.data.objects.new("_skyS", S))
        so.location = (x, y, zc - 0.5)
    for y in range(80, 700, 140):
        for sx in (-1, 1):
            if rng.random() < 0.6:
                g.box((sx * 29 - 0.2, y, 27.2), (sx * 29 + 0.2, y + 8, 27.5), lampw)
                L = bpy.data.lights.new("_skyW", "AREA")
                L.energy = 20000
                L.size = 8
                L.color = mat.rgb("#e0ffe8")
                lo = lib.link(bpy.data.objects.new("_skyW", L))
                lo.location = (sx * 29, y + 4, 27.0)
    # glowing sludge falls pouring out of the mains in the distance
    for (x, y, w) in ((-58, 430, 5.0), (46, 610, 7.0), (-18, 820, 9.0)):
        zt = 44.0 if abs(x) > 30 else 40.0
        g.face_out([(x - w / 2, y, -40), (x + w / 2, y, -40), (x + w / 2, y, zt), (x - w / 2, y, zt)], fall, (0, -1, 0))
    # the sludge river far below
    g.face([(-400, -300, -40), (400, -300, -40), (400, 900, -40), (-400, 900, -40)], sludge)
    g.obj("_vault", smooth_angle=35)
    # mist: a homogeneous world volume plus a thicker layer in the depths
    w = bpy.data.worlds.new("_skyworld")
    nt = w.node_tree
    bg = nt.nodes["Background"]
    bg.inputs["Color"].default_value = mat.rgba("#010302")
    bg.inputs["Strength"].default_value = 1.0
    vol = nt.nodes.new("ShaderNodeVolumePrincipled")
    vol.inputs["Density"].default_value = 0.0024
    vol.inputs["Color"].default_value = mat.rgba("#58705b")
    vol.inputs["Anisotropy"].default_value = 0.55
    vol.inputs["Absorption Color"].default_value = (0.0, 0.0, 0.0, 1)
    nt.links.new(vol.outputs[0], nt.nodes["World Output"].inputs["Volume"])
    sc.world = w
    mist = mat.new_material("_mist")
    mnt = mist.node_tree
    mnt.nodes.clear()
    mo = mnt.nodes.new("ShaderNodeOutputMaterial")
    mv = mnt.nodes.new("ShaderNodeVolumePrincipled")
    mv.inputs["Density"].default_value = 0.02
    mv.inputs["Color"].default_value = mat.rgba("#6f9a74")
    mnt.links.new(mv.outputs[0], mo.inputs["Volume"])
    mb = mesh.box("_mistbox", (1400, 1400, 50), (0, 250, -45))
    mb.data.materials.append(mist)
    cam_d = bpy.data.cameras.new("_skycam")
    cam_d.type = "PANO"
    cam_d.panorama_type = "EQUIRECTANGULAR"
    cam_d.clip_end = 3000
    cam = lib.link(bpy.data.objects.new("_skycam", cam_d))
    cam.location = (0, 0, 4.0)
    cam.rotation_euler = (math.radians(90), 0, 0)
    sc.camera = cam
    sc.render.resolution_x, sc.render.resolution_y = SKY_RES, SKY_RES // 2
    sc.render.resolution_percentage = 100
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    sc.render.image_settings.file_format = "OPEN_EXR"
    sc.render.image_settings.color_depth = "32"
    tmp = os.path.join(WORK, "sky_raw.exr")
    sc.render.filepath = tmp
    log(f"sky: rendering {SKY_RES}x{SKY_RES // 2} @ {SKY_SAMPLES} spp")
    bpy.ops.render.render(write_still=True)
    px = _load_exr(tmp)[..., :3] * SKY_GAIN
    h = px.shape[0]
    el = (np.arange(h) + 0.5) / h * math.pi - math.pi / 2  # rows bottom-up: -90..90 deg
    fade = smoothstep(0.03, -0.2, el)[:, None, None]
    fog = np.array(mat.rgb(LOOK["sky"]), np.float32)
    px = px * (1 - fade) + fog * fade
    out = np.ones((h, px.shape[1], 4), np.float32)
    out[..., :3] = to_srgb(px)
    img = np_image("_skyjpg", out)
    img.filepath_raw = SKY_OUT
    img.file_format = "JPEG"
    sc.render.image_settings.quality = 88
    os.makedirs(os.path.dirname(SKY_OUT), exist_ok=True)
    _save_jpeg(img, SKY_OUT, 88)
    log(f"sky: {SKY_OUT} ({os.path.getsize(SKY_OUT) // 1024} KB)")


def _save_jpeg(img, path, quality):
    sc = bpy.context.scene
    s = sc.render.image_settings
    old = (s.file_format, s.quality, s.color_mode)
    s.file_format = "JPEG"
    s.quality = quality
    s.color_mode = "RGB"
    sc.view_settings.view_transform = "Standard"
    img.colorspace_settings.name = "sRGB"
    img.save_render(path, scene=sc)
    s.file_format, s.quality, s.color_mode = old



# ------------------------------------------------------------------ atlas: lib bake, own packing

def _islands(o, layer, skip):
    """Faces of `o` grouped into UV islands of `layer` (edge-connected with
    matching UVs), skipping faces on materials in `skip`."""
    bm = bmesh.new()
    bm.from_mesh(o.data)
    uv = bm.loops.layers.uv[layer]
    mats = o.data.materials
    ok = [mats[f.material_index].name not in skip for f in bm.faces]
    parent = list(range(len(bm.faces)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    bm.faces.ensure_lookup_table()
    for f in bm.faces:
        if not ok[f.index]:
            continue
        for l in f.loops:
            o2 = l.link_loop_radial_next
            g2 = o2.face
            if g2 is f or not ok[g2.index]:
                continue
            if (l[uv].uv - o2.link_loop_next[uv].uv).length < 1e-5 and (l.link_loop_next[uv].uv - o2[uv].uv).length < 1e-5:
                a, b = find(f.index), find(g2.index)
                if a != b:
                    parent[a] = b
    groups = {}
    for f in bm.faces:
        if ok[f.index]:
            groups.setdefault(find(f.index), []).append(f.index)
    out = []
    for faces in groups.values():
        a3 = sum(bm.faces[i].calc_area() for i in faces)
        loops = [l.index for i in faces for l in bm.faces[i].loops]
        out.append((faces, loops, a3))
    bm.free()
    return out


def _skyline(rects, width):
    """Bottom-left skyline packing of (w, h) rects into a strip of `width`;
    returns positions and the used height."""
    sky = [(0.0, 0.0, width)]  # (x, y, w) segments
    pos = []
    top = 0.0
    for w, h in rects:
        best = None
        for i in range(len(sky)):
            x = sky[i][0]
            if x + w > width + 1e-9:
                break
            y, span, j = 0.0, 0.0, i
            while span < w - 1e-9 and j < len(sky):
                y = max(y, sky[j][1])
                span = sky[j][0] + sky[j][2] - x
                j += 1
            if span < w - 1e-9:
                continue
            if best is None or y + h < best[1] + best[3] - 1e-9 or (abs(y + h - best[1] - best[3]) < 1e-9 and x < best[0]):
                best = (x, y, w, h, i)
        if best is None:
            return None, float("inf")
        x, y, w, h, i = best
        pos.append((x, y))
        top = max(top, y + h)
        new = [(x, y + h, w)]
        rest = []
        for sx, sy, sw in sky:
            e = sx + sw
            if e <= x + 1e-12 or sx >= x + w - 1e-12:
                rest.append((sx, sy, sw))
            else:
                if sx < x:
                    rest.append((sx, sy, x - sx))
                if e > x + w:
                    rest.append((x + w, sy, e - x - w))
        sky = sorted(rest + new)
        merged = []
        for seg in sky:
            if merged and abs(merged[-1][1] - seg[1]) < 1e-12 and abs(merged[-1][0] + merged[-1][2] - seg[0]) < 1e-9:
                merged[-1] = (merged[-1][0], merged[-1][1], merged[-1][2] + seg[2])
            else:
                merged.append(seg)
        sky = merged
    return pos, top


def pack_atlas(objects, size, margin_px, keep):
    """Atlas layer from each object's render-active unwrap: islands scaled
    to texel density sqrt(atlas_weight), turned to lie flat, skyline-packed
    into the unit square."""
    isl = []
    for o in objects:
        me = o.data
        src = next(l for l in me.uv_layers if l.active_render)
        if "Atlas" in me.uv_layers:
            me.uv_layers.remove(me.uv_layers["Atlas"])
        src_name = src.name
        dst = me.uv_layers.new(name="Atlas")
        src = me.uv_layers[src_name]
        for i, d in enumerate(src.data):
            dst.data[i].uv = d.uv
        me.uv_layers[src_name].active_render = True
        w = o.get("atlas_weight", 1.0)
        uv = np.empty(len(me.loops) * 2, np.float64)
        dst.data.foreach_get("uv", uv)
        uv = uv.reshape(-1, 2)
        for faces, loops, a3 in _islands(o, "Atlas", keep):
            pts = uv[loops]
            # UV area (per face shoelace)
            area = 0.0
            for fi in faces:
                pl = me.polygons[fi].loop_indices
                q = uv[list(pl)]
                area += abs(np.dot(q[:, 0], np.roll(q[:, 1], -1)) - np.dot(q[:, 1], np.roll(q[:, 0], -1))) / 2
            if area < 1e-12 or a3 < 1e-9:
                k = 0.0
            else:
                k = math.sqrt(a3 * w / area)
            c = pts.mean(0)
            d = (pts - c) * k
            # orient along the principal axis, then lay the long side flat
            if len(d) > 2:
                cov = np.cov(d.T)
                ev, evec = np.linalg.eigh(cov)
                ax = evec[:, 1]
                ang = math.atan2(ax[1], ax[0])
                R = np.array([[math.cos(-ang), -math.sin(-ang)], [math.sin(-ang), math.cos(-ang)]])
                d2 = d @ R.T
                lo0, hi0 = d.min(0), d.max(0)
                lo1, hi1 = d2.min(0), d2.max(0)
                if np.prod(hi1 - lo1) < np.prod(hi0 - lo0) * 0.98:
                    d = d2
            lo, hi = d.min(0), d.max(0)
            ext = hi - lo
            if ext[1] > ext[0]:
                d = d[:, ::-1] * np.array([1.0, -1.0])
                lo, hi = d.min(0), d.max(0)
                ext = hi - lo
            isl.append(dict(o=o, loops=loops, d=d - lo, ext=ext))
    total = sum(max(i["ext"][0], 1e-6) * max(i["ext"][1], 1e-6) for i in isl)
    order = sorted(range(len(isl)), key=lambda i: -isl[i]["ext"][1])
    m = margin_px / size

    def attempt(scale):
        rects = [(isl[i]["ext"][0] * scale + 2 * m, isl[i]["ext"][1] * scale + 2 * m) for i in order]
        if max(r[0] for r in rects) > 1.0:
            return None
        pos, top = _skyline(rects, 1.0)
        return pos if top <= 1.0 else None
    lo_s, hi_s = 0.0, 1.0 / math.sqrt(total)
    while attempt(hi_s) is not None:
        lo_s, hi_s = hi_s, hi_s * 1.25
    for _ in range(14):
        mid = (lo_s + hi_s) / 2
        if attempt(mid) is not None:
            lo_s = mid
        else:
            hi_s = mid
    pos = attempt(lo_s)
    per_obj = {}
    for rank, i in enumerate(order):
        it = isl[i]
        x, y = pos[rank]
        new = it["d"] * lo_s + np.array([x + m, y + m])
        per_obj.setdefault(it["o"].name, []).append((it["loops"], new))
    for o in objects:
        me = o.data
        lay = me.uv_layers["Atlas"]
        uv = np.empty(len(me.loops) * 2, np.float64)
        lay.data.foreach_get("uv", uv)
        uv = uv.reshape(-1, 2)
        for loops, new in per_obj.get(o.name, []):
            uv[loops] = new
        lay.data.foreach_set("uv", uv.ravel())
        me.uv_layers.active = lay
    used = sum(isl[i]["ext"][0] * isl[i]["ext"][1] for i in range(len(isl))) * lo_s * lo_s
    log(f"atlas pack: {len(isl)} islands, {used * 100:.0f}% of the atlas in island boxes, scale {lo_s:.4f}")
    return lo_s


def tidy_normal(img, path, radius=1, snap=0.03):
    """3x3 box-filter the baked normal map (bake noise) and snap near-flat
    texels to flat: the UASTC normal map shrinks ~2.5x with no visible loss."""
    px = bake.pixels(img)
    n = px[..., :3] * 2 - 1
    n = np.stack([box_blur(n[..., i], radius) for i in range(3)], -1)
    n /= np.maximum(np.linalg.norm(n, axis=-1, keepdims=True), 1e-6)
    dev = np.hypot(n[..., 0], n[..., 1])
    k = np.clip((dev - snap) / snap, 0, 1)[..., None]
    flat = np.array([0.0, 0.0, 1.0], np.float32)
    n = flat + (n - flat) * k
    n /= np.maximum(np.linalg.norm(n, axis=-1, keepdims=True), 1e-6)
    px[..., :3] = n * 0.5 + 0.5
    bake.set_pixels(img, px)
    bake.save_png(img, path)


def kit_atlas(objects, size, out_dir, name, keep, ao_samples, ao_distance, margin_px=4):
    """bake.bake_kit_atlas with pack_atlas instead of Blender's packer:
    bakes albedo/normal/ORM(/emissive), one atlas material, kept materials
    keep their own UVs."""
    for o in objects:
        bake._ensure_material(o)
    pack_atlas(objects, size, margin_px, keep)
    res = bake.bake_maps(objects, size, out_dir, name, kinds=("albedo", "normal", "orm"), uv_layer="Atlas",
                         skip_materials=keep, emissive="auto", ao_samples=ao_samples, ao_distance=ao_distance,
                         ao_isolate=False, margin=max(2, margin_px // 2), samples=8)
    tidy_normal(res["normal"], res["paths"]["normal"])
    atlas = mat.atlas(name, res["albedo"], res["normal"], res["orm"], res.get("emissive"), res["emissive_strength"])
    keepset = set(keep)
    for o in objects:
        me = o.data
        old = list(me.materials)
        new = [atlas] + [mm for mm in dict.fromkeys(old) if mm is not None and mm.name in keepset]
        remap = [new.index(mm) if mm in new else 0 for mm in old]
        mi = [0] * len(me.polygons)
        me.polygons.foreach_get("material_index", mi)
        me.materials.clear()
        for mm in new:
            me.materials.append(mm)
        me.polygons.foreach_set("material_index", [remap[i] if i < len(remap) else 0 for i in mi])
        # kept faces: back to their own UVs in the atlas layer (UVMap, the texturing one)
        lay, src = me.uv_layers["Atlas"], me.uv_layers["UVMap"]
        for p in me.polygons:
            if new[p.material_index].name in keepset:
                for li in p.loop_indices:
                    lay.data[li].uv = src.data[li].uv
        me.update()
        mesh.finalize_uvs(o, "Atlas")
    res["material"] = atlas
    return res


# ------------------------------------------------------------------ main

def views_only():
    bpy.ops.wm.open_mainfile(filepath=os.path.join(WORK, "sewer_baked.blend"))
    final = {o.name: o for o in bpy.context.scene.objects if o.type == "MESH" and
             (o.name in ("deck", "deck_seam", "tunnel", "overhang", "rail_sewer") or o.name.startswith("side_"))}
    extras = {n: {k: o[k] for k in ("slot", "every", "chance", "side") if k in o} for n, o in final.items()}
    out = PREVIEW or os.path.join(WORK, "views")
    os.makedirs(out, exist_ok=True)
    game_view(final, extras, os.path.join(out, "game.png"))
    game_view(final, extras, os.path.join(out, "game_tunnel.png"), camera=(0.0, 66.0, 3.5), look=(0.0, 81.4, 1.1))
    game_view(final, extras, os.path.join(out, "game_wide.png"), size=(1280, 720), fov=55.0)


def main():
    global DECK_MASK
    os.makedirs(TEX, exist_ok=True)
    if VIEWS:
        views_only()
        return
    if SKY_ONLY or not SKIP_SKY:
        build_sky()
        if SKY_ONLY:
            return
    lib.reset_scene()
    G = build_graffiti()
    DECK_MASK = deck_mask_image()
    build_materials()
    built = build_all(G)
    extras = {n: ex for n, (_, ex) in built.items()}
    # atlas priorities by what the camera sees most (texel density ~ sqrt(weight))
    boost = {"deck": 1.5, "tunnel": 1.6, "overhang": 1.3, "rail_sewer": 1.5}
    for name, (parts, ex) in built.items():
        k_ = boost.get(name, {"wall": 1.0, "mid": 0.65, "far": 0.45}.get(ex.get("slot"), 1.0))
        for p in parts:
            p["atlas_weight"] = p.get("atlas_weight", 1.0) * k_
    for name, (parts, _) in built.items():  # bend loops: <= 0.5 m on deck/tunnel, <= 1 m elsewhere
        limit = 0.5 if name in ("deck", "deck_seam", "tunnel") else 1.0
        for p in parts:
            if max_edge_dy(p) > limit + 1e-3:
                mesh.subdivide_along(p, "Y", limit)
    for name, (parts, _) in built.items():
        dy = max(max_edge_dy(p) for p in parts)
        lo, hi = mesh.bounds(parts)
        log(f"{name}: parts {len(parts)} tris {mesh.tri_count(parts)} max edge dy {dy:.2f} "
            f"bounds x {lo.x:.1f}..{hi.x:.1f} y {lo.y:.1f}..{hi.y:.1f} z {lo.z:.1f}..{hi.z:.1f}")
    tot = 0.0
    for name, (parts, _) in built.items():  # atlas budget: area x weight per part
        if name == "deck_seam":
            continue
        rows = []
        for p in parts:
            a = sum(f.area for f in p.data.polygons
                    if p.data.materials[f.material_index].name not in KEEP)
            w = p.get("atlas_weight", 1.0)
            tot += a * w
            rows.append(f"{p.name}:{a:.0f}m2x{w}")
        log(f"atlas share {name}: " + " ".join(rows))
    log(f"atlas weighted area total {tot:.0f} m2")
    if NOBAKE:
        final = {n: join_node(n, parts) for n, (parts, _) in built.items()}
    else:
        # spread nodes apart so their AO doesn't touch, then bake one atlas
        objs = []
        for i, (name, (parts, _)) in enumerate(built.items()):
            if name == "deck_seam":
                continue
            for p in parts:
                p.location = (i * 250.0, 0, 0)
                objs.append(p)
        bpy.context.view_layer.update()
        if PACKONLY:
            pack_atlas(objs, SIZE, 2, KEEP)
            uv_owner_map(built, os.path.join(WORK, "uvmap.png"), layer="Atlas")
            return
        res = kit_atlas(objs, SIZE, TEX, "SewerKit", KEEP, AO_SAMPLES, 0.8, margin_px=2)
        log("atlas", res["paths"], "emissive strength", round(res["emissive_strength"], 2))
        final = {n: join_node(n, parts) for n, (parts, _) in built.items()}
        for n, o in final.items():
            if n != "deck_seam":
                log(f"texel density {n}: {texel_density(o):.0f} px/m")
    for n, o in final.items():
        for k_, v in extras[n].items():
            o[k_] = v
        log(f"node {n}: tris {mesh.tri_count(o)} materials {[m.name for m in o.data.materials]} extras {dict(extras[n])}")
    total, rows = scenery_estimate(final, extras)
    for r in rows:
        log(f"scenery {r[0]}: {r[1]} tris x {r[2]} placed = {r[3]}")
    log(f"visible scenery estimate: {int(total)} tris (budget 220k); unique tris {mesh.tri_count(list(final.values()))}")
    if not NOEXPORT:
        path = export.export_glb(OUT, list(final.values()))
        export.compress(path, max_texture=2048, inspect=False)
        log(f"glb: {os.path.getsize(path) // 1024} KB")
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(WORK, "sewer_baked.blend"), check_existing=False)
    if PREVIEW:
        os.makedirs(PREVIEW, exist_ok=True)
        track = [final[n] for n in ("deck", "tunnel", "overhang", "rail_sewer") if n in final]
        side = [o for n, o in final.items() if n.startswith("side_")]
        if track:
            preview.render_each(PREVIEW, track, views=((-0.7, -1.0, 0.55), (0.0, -1.0, 0.25), (0.9, 0.5, 0.4)),
                                size=(640, 640))
        if side:  # framed on what the track sees (clipped at z -4)
            clips = [clip_copy(o, -4.0) for o in side]
            for o in side:
                o.hide_render = True
            preview.render_each(PREVIEW, clips, views=((-1.0, -0.6, 0.3), (-1.0, 0.0, 0.1), (-0.3, -1.0, 0.25)),
                                size=(640, 640))
            for c in clips:
                bpy.data.objects.remove(c, do_unlink=True)
            for o in side:
                o.hide_render = False
        if "deck" in final:
            game_view(final, extras, os.path.join(PREVIEW, "game.png"))
            game_view(final, extras, os.path.join(PREVIEW, "game_tunnel.png"), camera=(0.0, 66.0, 3.5),
                      look=(0.0, 81.4, 1.1))
            game_view(final, extras, os.path.join(PREVIEW, "game_wide.png"), size=(1280, 720), fov=55.0)
            # inspection: close on the tunnel wall and a wall piece, 2.5x exposure
            game_view(final, extras, os.path.join(PREVIEW, "inspect_tunnel.png"), size=(1280, 720), fov=50.0,
                      camera=(-1.5, 88.0, 2.2), look=(6.0, 96.0, 3.4), runner=False, exposure_mul=2.5)
            game_view(final, extras, os.path.join(PREVIEW, "inspect_wall.png"), size=(1280, 720), fov=50.0,
                      camera=(0.0, 0.0, 2.5), look=(6.0, 9.0, 3.0), runner=False, exposure_mul=2.5)


main()
