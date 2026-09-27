# Feed City (biome 0): the city IS phones. Night, violet, neon, fog #07040f.
# Contract: docs/assets-v2.md "Biome kits".
#
#   blender -b -P assets/blender/kits/feed.py -- [--preview <dir>] [--only deck,side_lamp] [--no-bake]
#          [--no-sky] [--sky-only] [--no-game] [--size 2048]
#
# Writes public/assets/kits/feed.glb and public/assets/kits/feed-sky.jpg.
#
# The first half of this file is shared kit helpers (mall.py imports them;
# the build only runs as the main script):
#   G / decorate()    shader-level detail ("decals": slots, grilles, bands,
#                     screws, LEDs, window grids) in object space, baked into
#                     the atlas, so small detail costs no triangles
#   MB + phone/rbox/lathe/tube/sweep   the few mesh shapes every kit needs,
#                     with outward winding and a UVMap layer
#   bake_kit()        lib.bake_kit_atlas over split parts (each with its own
#                     texel weight), joined into the contract's nodes after
#   game_view()       the review shot: rows of deck, scenery placed exactly
#                     like src/render/biome.ts (same hash), linear fog
#   render_sky()      the Cycles equirect panorama

import math
import os
import sys

sys.dont_write_bytecode = True  # no __pycache__ in the repo
_d = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _d if os.path.isdir(os.path.join(_d, "lib")) else os.path.dirname(_d))

import bpy  # noqa: E402
import numpy as np  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402

import lib  # noqa: E402
from lib import bake, export, log, mat, mesh, preview  # noqa: E402

KITS_OUT = os.path.join(lib.PUBLIC, "kits")
TAU = math.tau


# =================================================================== shader detail

class G:
    """Tiny node-graph builder on a material's tree."""

    def __init__(self, m):
        self.m, self.nt = m, m.node_tree
        self.p = mat.principled(m)
        self._xyz = self._n = None

    def node(self, kind, **props):
        n = self.nt.nodes.new(kind)
        for k, v in props.items():
            setattr(n, k, v)
        return n

    def link(self, a, b):
        self.nt.links.new(a, b)

    def put(self, sock, v):
        if isinstance(v, bpy.types.NodeSocket):
            self.link(v, sock)
        elif sock.type == "RGBA":
            sock.default_value = mat.rgba(v) if isinstance(v, str) or len(v) == 3 else v
        else:
            sock.default_value = v

    def math(self, op, a, b=None, c=None, clamp=False):
        n = self.node("ShaderNodeMath", operation=op, use_clamp=clamp)
        for i, v in enumerate((a, b, c)):
            if v is not None:
                self.put(n.inputs[i], v)
        return n.outputs[0]

    def add(self, a, b): return self.math("ADD", a, b)
    def sub(self, a, b): return self.math("SUBTRACT", a, b)
    def mul(self, a, b): return self.math("MULTIPLY", a, b)
    def mx(self, a, b): return self.math("MAXIMUM", a, b)
    def mn(self, a, b): return self.math("MINIMUM", a, b)
    def abs(self, a): return self.math("ABSOLUTE", a)
    def sat(self, a): return self.math("ADD", a, 0.0, clamp=True)
    def mad(self, a, b, c, clamp=False): return self.math("MULTIPLY_ADD", a, b, c, clamp=clamp)

    def lerp(self, f, a, b):
        n = self.node("ShaderNodeMix", data_type="FLOAT", clamp_factor=True)
        self.put(n.inputs[0], f)
        self.put(n.inputs[2], a)
        self.put(n.inputs[3], b)
        return n.outputs[0]

    def lerpc(self, f, a, b):
        n = self.node("ShaderNodeMix", data_type="RGBA", blend_type="MIX", clamp_factor=True)
        self.put(n.inputs[0], f)
        self.put(n.inputs[6], a)
        self.put(n.inputs[7], b)
        return n.outputs[2]

    def xyz(self):
        if self._xyz is None:
            tc = self.node("ShaderNodeTexCoord")
            sep = self.node("ShaderNodeSeparateXYZ")
            self.link(tc.outputs["Object"], sep.inputs[0])
            self._xyz = tuple(sep.outputs[i] for i in range(3))
        return self._xyz

    def nrm(self):
        if self._n is None:
            geo = self.node("ShaderNodeNewGeometry")
            sep = self.node("ShaderNodeSeparateXYZ")
            self.link(geo.outputs["Normal"], sep.inputs[0])
            self._n = tuple(sep.outputs[i] for i in range(3))
        return self._n

    def noise(self, scale=1.0, detail=2.0, vec=None):
        n = self.node("ShaderNodeTexNoise")
        n.inputs["Scale"].default_value = scale
        n.inputs["Detail"].default_value = detail
        if vec is not None:
            self.link(vec, n.inputs["Vector"])
        else:
            tc = self.node("ShaderNodeTexCoord")
            self.link(tc.outputs["Object"], n.inputs["Vector"])
        return n.outputs["Fac"]

    def hash2(self, a, b):
        """White noise 0..1 from two floats (cell ids)."""
        comb = self.node("ShaderNodeCombineXYZ")
        self.put(comb.inputs[0], a)
        self.put(comb.inputs[1], b)
        wn = self.node("ShaderNodeTexWhiteNoise", noise_dimensions="3D")
        self.link(comb.outputs[0], wn.inputs["Vector"])
        return wn.outputs["Value"]


def _src(p, name):
    s = p.inputs[name]
    if s.is_linked:
        return s.links[0].from_socket
    v = s.default_value
    return tuple(v) if hasattr(v, "__len__") else v


def _fill(g, sdf, soft):
    """1 inside (sdf < 0), 0 outside, a `soft`-wide ramp."""
    return g.mad(sdf, -1.0 / soft, 0.5, clamp=True)


def _rrect_sdf(g, u, v, cu, cv, hw, hh, r):
    r = min(r, hw, hh)
    qx = g.sub(g.abs(g.sub(u, cu)), hw - r)
    qy = g.sub(g.abs(g.sub(v, cv)), hh - r)
    ox, oy = g.mx(qx, 0.0), g.mx(qy, 0.0)
    out = g.math("SQRT", g.add(g.mul(ox, ox), g.mul(oy, oy)))
    return g.sub(g.add(out, g.mn(g.mx(qx, qy), 0.0)), r)


def _cells(g, a, pitch, offset=0.0):
    """(local -0.5..0.5 coordinate in the cell, cell id) along one axis."""
    t = g.math("DIVIDE", g.sub(a, offset), pitch)
    return g.sub(g.math("FRACT", t), 0.5), g.math("FLOOR", t)


def decal_mask(g, d, soft):
    """Mask socket for one decal spec (see decorate)."""
    ax = dict(zip("xyz", g.xyz()))
    pl = d.get("plane", "xy")
    if "axes" in d:  # arbitrary plane: origin o, axes U, V (unit vectors); w along U x V
        o, U, V = (Vector(q) for q in d["axes"])
        Wn = U.cross(V)
        px, py, pz = (g.sub(ax[a], o[i]) for i, a in enumerate("xyz"))

        def dot3(A):
            return g.add(g.add(g.mul(px, A.x), g.mul(py, A.y)), g.mul(pz, A.z))
        u, v = dot3(U), dot3(V)
        ax["_w"] = dot3(Wn)
    else:
        u, v = ax[pl[0]], ax[pl[1]]
    cu, cv = d.get("c", (0.0, 0.0))
    hw, hh = d.get("s", (1e3, 1e3))
    sf = d.get("soft", soft)
    kind = d.get("kind", "rect")
    if kind == "circle":
        du, dv = g.sub(u, cu), g.sub(v, cv)
        m = _fill(g, g.sub(g.math("SQRT", g.add(g.mul(du, du), g.mul(dv, dv))), hw), sf)
    elif kind == "ring":
        du, dv = g.sub(u, cu), g.sub(v, cv)
        dist = g.math("SQRT", g.add(g.mul(du, du), g.mul(dv, dv)))
        m = _fill(g, g.sub(g.abs(g.sub(dist, hw)), hh), sf)
    else:
        m = _fill(g, _rrect_sdf(g, u, v, cu, cv, hw, hh, d.get("r", 0.0)), sf)
    if kind == "image":  # a picture (text sheet cell) stretched over the rect: its alpha is the mask
        uu = g.mad(g.sub(u, cu), 0.5 / hw, 0.5)
        vv = g.mad(g.sub(v, cv), 0.5 / hh, 0.5)
        x0, y0, x1, y1 = d.get("cell", (0.0, 0.0, 1.0, 1.0))
        uu = g.mad(uu, x1 - x0, x0)
        vv = g.mad(vv, y1 - y0, y0)
        if d.get("flip_u"):
            uu = g.sub(x0 + x1, uu)
        comb = g.node("ShaderNodeCombineXYZ")
        g.put(comb.inputs[0], uu)
        g.put(comb.inputs[1], vv)
        tex = g.node("ShaderNodeTexImage", extension="CLIP", interpolation="Linear")
        tex.image = bpy.data.images.load(d["image"], check_existing=True)
        g.link(comb.outputs[0], tex.inputs["Vector"])
        m = g.mul(m, tex.outputs["Alpha"])
        d["_col"] = tex.outputs["Color"]
    if kind == "dots":  # perforation: holes of radius `hole` every `pitch`
        pu, pv = d["pitch"] if isinstance(d["pitch"], (tuple, list)) else (d["pitch"], d["pitch"])
        fu, iu = _cells(g, u, pu, cu)
        voff = g.mul(g.math("MODULO", iu, 2.0), 0.5) if d.get("stagger", True) else 0.0
        fv, _ = _cells(g, g.add(v, g.mul(voff, pv)), pv, cv)
        du, dv = g.mul(fu, pu), g.mul(fv, pv)
        m = g.mul(m, _fill(g, g.sub(g.math("SQRT", g.add(g.mul(du, du), g.mul(dv, dv))), d["hole"]), sf))
    elif kind == "lines":  # parallel grooves across u (or v with axis="v"), `width` wide every `pitch`
        a = u if d.get("axis", "u") == "u" else v
        f, _ = _cells(g, a, d["pitch"], d.get("phase", 0.0))
        m = g.mul(m, _fill(g, g.sub(g.abs(g.mul(f, d["pitch"])), d["width"] / 2), sf))
    elif kind == "grid":  # window grid: cells `pitch`=(pu, pv) with mullions `frame` wide; lit = fraction on
        pu, pv = d["pitch"]
        fu, iu = _cells(g, u, pu, cu)
        fv, iv = _cells(g, v, pv, cv)
        fr = d["frame"]
        fru, frv = fr if isinstance(fr, (tuple, list)) else (fr, fr)
        inner = g.mul(_fill(g, g.sub(g.abs(g.mul(fu, pu)), pu / 2 - fru), sf),
                      _fill(g, g.sub(g.abs(g.mul(fv, pv)), pv / 2 - frv), sf))
        if "lit" in d:  # random cells on
            h = g.hash2(iu, g.add(iv, d.get("seed", 0.0)))
            inner = g.mul(inner, g.math("LESS_THAN", h, d["lit"]))
        m = g.mul(m, inner)
    if "w" in d:  # limit to a slab of the third axis
        w = ax["_w"] if "axes" in d else ax[({"x", "y", "z"} - set(pl)).pop()]
        lo, hi = d["w"]
        m = g.mul(m, g.mul(_fill(g, g.sub(lo, w), sf), _fill(g, g.sub(w, hi), sf)))
    if "face" in d:  # only faces whose normal points this way
        n = g.nrm()
        f = d["face"]
        dot = g.add(g.add(g.mul(n[0], f[0]), g.mul(n[1], f[1])), g.mul(n[2], f[2]))
        m = g.mul(m, g.mad(dot, 8.0, -5.0, clamp=True))
    if "noise" in d:  # break it up (grime, wear): keep where noise > threshold
        sc, th = d["noise"]
        m = g.mul(m, g.mad(g.noise(sc, 4.0), 6.0, -6.0 * th, clamp=True))
    if "amount" in d:
        m = g.mul(m, d["amount"])
    return m


def decorate(m, decals, soft=0.005, bump=1.0):
    """Layer detail onto a material in object space. Each decal is a dict:

    kind   rect (default) | circle | ring | dots | lines | grid | image (image=path, cell=(u0, v0, u1, v1):
           the picture's alpha is the mask, its colour the colour unless `color` is given)
    plane  two object axes for (u, v): "xy" (floors), "xz" (faces along X), "yz"
    axes   (origin, U, V) instead of plane: any oriented plane (u, v measured from origin)
    c, s   centre (u, v) and half size (hu, hv); circle: s[0] radius; ring: (radius, half width)
    r      corner radius (rect)
    w      (lo, hi) range on the third axis   face  (nx, ny, nz) facing filter
    pitch/hole/stagger (dots), pitch/width/axis (lines), pitch/frame/lit (grid)
    noise  (scale, threshold) wear breakup      amount  mask multiplier
    color / rough / metal   values inside the mask
    depth  height (m, negative = recessed), turned into a bump
    emit   (colour, strength) glow inside the mask (baked into the emissive atlas)"""
    g = G(m)
    p = g.p
    col, rough, metal = _src(p, "Base Color"), _src(p, "Roughness"), _src(p, "Metallic")
    nrm_in = p.inputs["Normal"].links[0].from_socket if p.inputs["Normal"].is_linked else None
    height = None
    emits = [d["emit"][1] for d in decals if "emit" in d]
    top = max(emits) if emits else 0.0
    emi = None
    for d in decals:
        mk = decal_mask(g, d, soft)
        if "_col" in d and "color" not in d:
            col = g.lerpc(mk, col, d.pop("_col"))
        elif "color" in d:
            col = g.lerpc(mk, col, d["color"])
        if "rough" in d:
            rough = g.lerp(mk, rough, d["rough"])
        if "metal" in d:
            metal = g.lerp(mk, metal, d["metal"])
        if "depth" in d:
            h = g.mul(mk, d["depth"])
            height = h if height is None else g.add(height, h)
        if "emit" in d:
            c = mat.rgb(d["emit"][0])
            k = d["emit"][1] / top
            emi = g.lerpc(mk, emi if emi is not None else (0.0, 0.0, 0.0, 1.0), (c[0] * k, c[1] * k, c[2] * k, 1.0))
    for name, v in (("Base Color", col), ("Roughness", rough), ("Metallic", metal)):
        g.put(p.inputs[name], v)
    if height is not None:
        b = g.node("ShaderNodeBump")
        b.inputs["Strength"].default_value = bump
        b.inputs["Distance"].default_value = 1.0
        g.link(height, b.inputs["Height"])
        if nrm_in is not None:
            g.link(nrm_in, b.inputs["Normal"])
        g.link(b.outputs["Normal"], p.inputs["Normal"])
    if emi is not None:
        g.link(emi, p.inputs["Emission Color"])
        p.inputs["Emission Strength"].default_value = top
    return m


# =================================================================== materials

def metal(name, textures="Metal009", scale=0.6, tint="#9d9aa6", rough=None, rough_scale=0.85, rough_offset=0.0,
          normal=0.6):
    """Brushed/blasted metal from a CC0 set, object-space box mapped."""
    kw = dict(roughness=rough) if rough is not None else dict(roughness_scale=rough_scale,
                                                              roughness_offset=rough_offset)
    return mat.pbr(name, textures, mapping="BOX", box_scale=scale, box_blend=0.2, tint=tint, metallic=1.0,
                   normal_strength=normal, **kw)


def smudged(name, color, rough=0.06, amount=0.28, scale=1.0, smudge="Fingerprints002", metal_=0.0):
    """Glossy dielectric (black glass, lacquer) with fingerprint smudges in the roughness."""
    m = mat.flat(name, color, rough=rough, metal=metal_)
    maps = mat.find_maps(smudge)
    kind = next(k for k in ("roughness", "opacity", "color") if k in maps)
    g = G(m)
    vec = mat.box_vector(g.nt, scale)
    t = g.node("ShaderNodeTexImage", projection="BOX", projection_blend=0.3)
    t.image = mat.image(maps[kind], True)
    g.link(vec, t.inputs["Vector"])
    g.link(g.mad(t.outputs["Color"], amount, rough, clamp=True), g.p.inputs["Roughness"])
    return m


def glow(name, color, strength=5.0, base="#101010"):
    return mat.flat(name, base, rough=0.4, emission=color, strength=strength)


# =================================================================== mesh building

def rrect_pts(w, h, r, seg, cx=0.0, cy=0.0):
    """Rounded rectangle outline, CCW seen from +Z, 4 * (seg + 1) points."""
    r = max(1e-3, min(r, w / 2 - 1e-4, h / 2 - 1e-4))
    out = []
    for x, y, a0 in ((w / 2 - r, -h / 2 + r, -90), (w / 2 - r, h / 2 - r, 0), (-w / 2 + r, h / 2 - r, 90),
                     (-w / 2 + r, -h / 2 + r, 180)):
        for k in range(seg + 1):
            a = math.radians(a0 + 90.0 * k / seg)
            out.append((cx + x + r * math.cos(a), cy + y + r * math.sin(a)))
    return out


def circle_pts(r, n, cx=0.0, cy=0.0, a0=0.0):
    return [(cx + r * math.cos(a0 + TAU * i / n), cy + r * math.sin(a0 + TAU * i / n)) for i in range(n)]


class MB:
    """Mesh builder: vertices, faces with a material slot each, then one object with a UVMap layer."""

    def __init__(self, mats):
        self.mats = list(mats)
        self.v, self.f, self.fm = [], [], []

    def slot(self, m):
        if isinstance(m, int):
            return m
        if m not in self.mats:
            self.mats.append(m)
        return self.mats.index(m)

    def verts(self, pts):
        i0 = len(self.v)
        self.v.extend(tuple(float(c) for c in p) for p in pts)
        return list(range(i0, len(self.v)))

    def face(self, idx, m=0):
        self.f.append(tuple(idx))
        self.fm.append(self.slot(m))

    def bridge(self, a, b, m=0, closed=True):
        """Quads between two equal loops a -> b (outward if the profile runs back -> side -> front)."""
        n = len(a)
        for i in range(n if closed else n - 1):
            j = (i + 1) % n
            self.face((a[i], a[j], b[j], b[i]), m)

    def fan(self, ring, apex, m=0, flip=False):
        n = len(ring)
        for i in range(n):
            j = (i + 1) % n
            self.face((ring[i], ring[j], apex) if not flip else (ring[j], ring[i], apex), m)

    def cap(self, ring, m=0, flip=False):
        self.face(list(reversed(ring)) if flip else list(ring), m)

    def build(self, name):
        me = bpy.data.meshes.new(name)
        me.from_pydata(self.v, [], self.f)
        me.update(calc_edges=True)
        for m in self.mats:
            me.materials.append(m)
        me.polygons.foreach_set("material_index", self.fm)
        me.uv_layers.new(name="UVMap")
        me.update()
        return lib.link(bpy.data.objects.new(name, me))


def loft(b, outlines, mats, caps=(None, None)):
    """Loft closed outlines [(pts2d or pts3d), ...] given as rings of 3D points."""
    rings = [b.verts(r) for r in outlines]
    for i in range(len(rings) - 1):
        b.bridge(rings[i], rings[i + 1], mats[i] if isinstance(mats, (list, tuple)) else mats)
    if caps[0] is not None:
        b.cap(rings[0], caps[0], flip=True)
    if caps[1] is not None:
        b.cap(rings[-1], caps[1])
    return rings


def phone(name, W, H, T, r, frame, face, back, screen=None, screen_mat=None, chamfer=None, seg=4, prof=None,
          cap_back=True, xform=None):
    """A phone lying in XY (x across W, y along H, the phone's top at +y), back at z=0, front at z=T.

    prof     rings (inset, z) from the back edge round the side to the front edge
             (default: small back round, flat side, 45 degree front chamfer)
    chamfer  material of the last (front) band: the polished diamond cut
    screen   (sw, sh, cy, sr): display rectangle (centre y offset, corner radius) inset in the front
    Returns an object (transformed by `xform`, a Matrix, if given)."""
    b = MB([frame, face, back])
    if prof is None:
        c = min(0.12 * T, 0.2 * r)
        prof = [(0.35 * c, 0.0), (0.0, 0.35 * c), (0.0, T - c), (c, T)]
    rings = [[(x, y, z) for x, y in rrect_pts(W - 2 * d, H - 2 * d, r - d, seg)] for d, z in prof]
    band = [frame] * (len(rings) - 1)
    if chamfer is not None:
        band[-1] = chamfer
    rr = loft(b, rings, band, caps=(back if cap_back else None, None))
    front = rr[-1]
    if screen is not None:
        sw, sh, cy, sr = screen
        inner = b.verts([(x, y, T) for x, y in rrect_pts(sw, sh, sr, seg, cy=cy)])
        b.bridge(front, inner, face)
        b.cap(inner, screen_mat if screen_mat is not None else face)
    else:
        b.cap(front, face)
    o = b.build(name)
    if screen is not None and screen_mat is not None and screen_mat.name in ("ScreenFeed", "AdFace"):
        mesh.uv_fit_faces(o, material=screen_mat.name)
    if xform is not None:
        o.data.transform(xform)
    return o


def rbox(name, sx, sy, sz, r, c, m, top=None, bottom=None, seg=3, center=(0, 0, 0), xform=None):
    """Rounded-corner box (corner radius r in XY, chamfer c on the Z edges), centred."""
    c = min(c, sz / 2 - 1e-4)
    prof = [(c, 0.0), (0.0, c), (0.0, sz - c), (c, sz)] if c > 0 else [(0.0, 0.0), (0.0, sz)]
    o = phone(name, sx, sy, sz, r, m, top or m, bottom or m, seg=seg, prof=prof)
    M = Matrix.Translation(Vector(center) - Vector((0, 0, sz / 2)))
    o.data.transform(M)
    if xform is not None:
        o.data.transform(xform)
    return o


def lathe(name, prof, n, mats, cap_bottom=None, cap_top=None, xform=None, a0=0.0):
    """Surface of revolution about Z: prof [(radius, z), ...] bottom to top; r == 0 makes a point."""
    b = MB([mats] if not isinstance(mats, (list, tuple)) else mats)
    rings = []
    for rad, z in prof:
        if rad <= 1e-6:
            rings.append(b.verts([(0.0, 0.0, z)]))
        else:
            rings.append(b.verts([(x, y, z) for x, y in circle_pts(rad, n, a0=a0)]))
    band = mats if isinstance(mats, (list, tuple)) else [mats] * (len(rings) - 1)
    for i in range(len(rings) - 1):
        a, c = rings[i], rings[i + 1]
        mi = band[min(i, len(band) - 1)]
        if len(a) == 1 and len(c) > 1:
            b.fan(c, a[0], mi, flip=True)
        elif len(c) == 1 and len(a) > 1:
            b.fan(a, c[0], mi)
        elif len(a) > 1:
            b.bridge(a, c, mi)
    if cap_bottom is not None and len(rings[0]) > 1:
        b.cap(rings[0], cap_bottom, flip=True)
    if cap_top is not None and len(rings[-1]) > 1:
        b.cap(rings[-1], cap_top)
    o = b.build(name)
    if xform is not None:
        o.data.transform(xform)
    return o


def tube(name, path, radius, n, m, caps=True, flat_y=False):
    """A tube of `n` sides swept along a polyline (radius a float or per-point list). flat_y: rings lie
    in constant-y planes (for cables running along the track: put the points on the bend loops and
    subdivide_along adds nothing)."""
    pts = [Vector(p) for p in path]
    if flat_y:
        b = MB([m])
        rads = radius if isinstance(radius, (list, tuple)) else [radius] * len(pts)
        rings = []
        for i, p in enumerate(pts):
            a, c = pts[max(0, i - 1)], pts[min(len(pts) - 1, i + 1)]
            t = (c - a).normalized()
            k = 1.0 / max(0.3, abs(t.y))  # keep the thickness where the cable dips
            rings.append(b.verts([p + Vector((rads[i] * math.cos(TAU * j / n), 0.0, rads[i] * k * math.sin(TAU * j / n)))
                                  for j in range(n)]))
        sgn = 1 if (pts[-1] - pts[0]).y > 0 else -1
        for i in range(len(rings) - 1):
            a, c = rings[i], rings[i + 1]
            if sgn > 0:
                b.bridge(list(reversed(a)), list(reversed(c)), 0)
            else:
                b.bridge(a, c, 0)
        if caps:
            b.cap(rings[0], 0, flip=sgn < 0)
            b.cap(rings[-1], 0, flip=sgn > 0)
        return b.build(name)
    rads = radius if isinstance(radius, (list, tuple)) else [radius] * len(pts)
    tans = []
    for i in range(len(pts)):
        a, c = pts[max(0, i - 1)], pts[min(len(pts) - 1, i + 1)]
        tans.append((c - a).normalized())
    ref = Vector((0, 0, 1)) if abs(tans[0].z) < 0.9 else Vector((1, 0, 0))
    nrm = ref.cross(tans[0]).cross(tans[0]).normalized() * -1
    b = MB([m])
    rings = []
    for i, (p, t) in enumerate(zip(pts, tans)):
        nrm = (nrm - t * nrm.dot(t)).normalized()  # parallel transport
        bi = t.cross(nrm)
        rings.append(b.verts([p + rads[i] * (math.cos(TAU * k / n) * nrm + math.sin(TAU * k / n) * bi)
                              for k in range(n)]))
    for i in range(len(rings) - 1):
        b.bridge(rings[i], rings[i + 1], 0)
    if caps:
        b.cap(rings[0], 0, flip=True)
        b.cap(rings[-1], 0)
    return b.build(name)


def sweep(name, profile_at, ys, mats_fn, mats, closed=False):
    """Profile (x, z) points swept along Y through rings at `ys`. Face normal = profile direction x +Y,
    so run the profile up the left side, over the top to the right, down (and back under if closed)."""
    b = MB(mats)
    rings = [b.verts([(x, y, z) for x, z in profile_at(y)]) for y in ys]
    n = len(rings[0])
    for k in range(len(rings) - 1):
        for j in range(n if closed else n - 1):
            j2 = (j + 1) % n
            mi = mats_fn(j, k)
            if mi is None:
                continue
            # (P(j,k), P(j+1,k), P(j+1,k+1), P(j,k+1)): e1 along the profile, e2 along +Y
            b.face((rings[k][j], rings[k][j2], rings[k + 1][j2], rings[k + 1][j]), mi)
    return b.build(name)


def basis(front, up, origin=(0.0, 0.0, 0.0)):
    """Matrix taking local +Z to `front`, +Y to `up` (+X = up x front), then to `origin`."""
    f = Vector(front).normalized()
    u = Vector(up)
    u = (u - f * u.dot(f)).normalized()
    x = u.cross(f)
    o = Vector(origin)
    return Matrix(((x.x, u.x, f.x, o.x), (x.y, u.y, f.y, o.y), (x.z, u.z, f.z, o.z), (0, 0, 0, 1)))


def T(x=0.0, y=0.0, z=0.0):
    return Matrix.Translation((x, y, z))


def R(axis, deg):
    return Matrix.Rotation(math.radians(deg), 4, axis)


def xf(o, M):
    o.data.transform(M)
    o.data.update()
    return o


def join(parts, name):
    parts = [p for p in parts if p is not None]
    o = mesh.join(parts, name)
    return o


def finish(o, angle=35.0, weighted=True):
    """Sharp edges from angle + weighted normals, applied (after subdivide_along)."""
    me = o.data
    me.shade_smooth()
    me.set_sharp_from_angle(angle=math.radians(angle))
    if weighted:
        mod = o.modifiers.new("wn", "WEIGHTED_NORMAL")
        mod.keep_sharp = True
        mod.weight = 50
        mesh.apply_modifiers(o)
    return o


def loops(o, step=1.0, positions=None):
    """Bend loops along Y (contract: <= 1 m, <= 0.5 m on deck and tunnels)."""
    if positions is not None:
        return mesh.subdivide_along(o, "Y", positions=positions)
    lo, hi = mesh.bounds(o)
    if hi.y - lo.y > 1.2 * step:
        return mesh.subdivide_along(o, "Y", step)
    return 0


def weight(o, w):
    o["atlas_weight"] = float(w)
    return o


def split_faces(o, pred, name):
    """Move the faces where pred(center, normal, material_name) is true into a new object (its own
    texel weight in the atlas); returns it (or None if no face matched)."""
    import bmesh
    names = [m.name if m else "" for m in o.data.materials]
    hit = [p.index for p in o.data.polygons if pred(p.center, p.normal, names[p.material_index])]
    if not hit:
        return None
    new = mesh.duplicate(o, name)
    hs = set(hit)
    for obj, keep in ((o, False), (new, True)):
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        kill = [f for f in bm.faces if (f.index in hs) != keep]
        bmesh.ops.delete(bm, geom=kill, context="FACES")
        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()
    return new


def away_parts(o, name, w_front, w_back=0.03, w_deep=0.02, deep=-8.0, away=0.5):
    """Split a scenery piece: faces facing away from the track (+X) and faces far below the track get
    a tiny texel weight; returns the parts list."""
    deep_p = split_faces(o, lambda c, n, m: c.z < deep, name + "_deep")
    back_p = split_faces(o, lambda c, n, m: n.x > away, name + "_back")
    weight(o, w_front)
    out = [o]
    for p, w in ((back_p, w_back), (deep_p, w_deep)):
        if p is not None:
            weight(p, w)
            out.append(p)
    return out


# =================================================================== kit assembly

class Kit:
    """Pieces of one biome kit: each node is a list of bake parts (own texel weights) joined after baking."""

    def __init__(self, name, keep=("ScreenFeed", "AdFace", "Seam")):
        self.name = name
        self.keep = tuple(keep)
        self.parts = {}    # node -> [objects]
        self.extras = {}   # node -> dict
        self.plain = {}    # node -> object that skips the atlas (deck_seam)
        self.shares = {}   # node -> target atlas fraction

    def add(self, node, parts, extras=None, share=None):
        """share: this node's target fraction of the atlas (texel weights are rescaled to hit it)."""
        parts = parts if isinstance(parts, (list, tuple)) else [parts]
        for i, p in enumerate(parts):
            p.name = f"{node}__{i}"
        self.parts[node] = list(parts)
        if extras:
            self.extras[node] = dict(extras)
        if share is not None:
            self.shares[node] = share

    def add_plain(self, node, obj):
        obj.name = node
        obj.data.name = node
        self.plain[node] = obj

    def all_parts(self):
        return [p for ps in self.parts.values() for p in ps]

    def tris(self, node):
        if node in self.plain:
            return mesh.tri_count(self.plain[node])
        return mesh.tri_count(self.parts[node])

    def report(self):
        total = 0
        est = 0.0
        for node in list(self.parts) + list(self.plain):
            t = self.tris(node)
            total += t
            x = self.extras.get(node)
            line = f"  {node:<22} {t:>6} tris"
            if x:
                sides = 2 if x.get("side", "both") == "both" else 1
                vis = 200.0 / x["every"] * sides * x["chance"] * t
                est += vis
                line += f"   slot={x['slot']} every={x['every']} chance={x['chance']} side={x.get('side', 'both')}" \
                        f"  -> {vis / 1000:.1f}k visible"
            if node in self.parts:
                seg = max(mesh.max_segment(p) for p in self.parts[node])
                line += f"   maxY {seg:.2f}"
            log(line)
        log(f"{self.name}: {total} unique tris; visible-scenery estimate {est / 1000:.1f}k (<= 220k)")
        return total, est


def bake_kit(kit, size, tex_dir, name, samples=8, ao_samples=32, ao_distance=0.6, alpha=None):
    """Atlas-bake every part, then join each node's parts into one object named after the node."""
    parts = kit.all_parts()

    def weighted():
        areas = {}
        for p in parts:
            a = sum(poly.area for poly in p.data.polygons
                    if p.data.materials[poly.material_index] is None
                    or p.data.materials[poly.material_index].name not in kit.keep)
            areas[p.name] = a * p.get("atlas_weight", 1.0)
        tot = sum(areas.values()) or 1.0
        return {n: sum(areas[p.name] for p in ps) / tot for n, ps in kit.parts.items()}
    by_node = weighted()
    if kit.shares:  # rescale each node's weights so its share of the atlas hits the target
        free = 1.0 - sum(kit.shares.values())
        rest = sum(v for n, v in by_node.items() if n not in kit.shares) or 1.0
        for n, ps in kit.parts.items():
            want = kit.shares.get(n, by_node[n] / rest * max(free, 0.0))
            k = want / max(by_node[n], 1e-9)
            for p in ps:
                p["atlas_weight"] = p.get("atlas_weight", 1.0) * k
        by_node = weighted()
    log("atlas share: " + ", ".join(f"{n} {100 * v:.1f}%" for n, v in sorted(by_node.items(), key=lambda kv: -kv[1])))
    res = bake.bake_kit_atlas(parts, size, tex_dir, name=name, keep_materials=kit.keep, samples=samples,
                              ao_samples=ao_samples, ao_distance=ao_distance, alpha=alpha)
    nodes = {}
    for n, ps in kit.parts.items():
        o = join(ps, n) if len(ps) > 1 else ps[0]
        o.name = n
        o.data.name = n
        for k, v in kit.extras.get(n, {}).items():
            o[k] = v
        if "atlas_weight" in o:
            del o["atlas_weight"]
        nodes[n] = o
    for n, o in kit.plain.items():
        nodes[n] = o
    return res, nodes


def cache_nodes(nodes, path):
    """Write the baked nodes (meshes, materials, atlas images by path) to a .blend for --game-only."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bpy.data.libraries.write(path, set(nodes.values()), fake_user=True)
    return path


def load_nodes(path):
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        dst.objects = list(src.objects)
    out = {}
    for o in dst.objects:
        if o is not None:
            lib.link(o)
            out[o.name] = o
    return out


def export_kit(nodes, out, size):
    objs = list(nodes.values())
    for o in objs:
        o.location = (0, 0, 0)
        o.rotation_euler = (0, 0, 0)
        o.scale = (1, 1, 1)
    path = export.export_glb(out, objs)
    export.compress(path, max_texture=size, inspect=False)
    log(f"{os.path.basename(out)}: {os.path.getsize(path) / 1024:.0f} KB compressed")
    return path


# =================================================================== previews

def hash32(a, b):
    """src/render/atlas.ts hash(), bit for bit."""
    M = 0xFFFFFFFF

    def imul(x, y):
        return ((x & M) * (y & M)) & M
    h = imul((a & M) ^ 0x9E3779B9, 0x85EBCA6B) ^ imul((b + 0x632BE5AB) & M, 0xC2B2AE35)
    h &= M
    h ^= h >> 13
    h = imul(h, 0x27D4EB2F)
    h ^= h >> 15
    return (h & M) / 4294967296.0


SLOTS = {"wall": (4.6, 7.0), "mid": (8.0, 20.0), "far": (20.0, 60.0)}


def placements(extras_by_node, s0, s1):
    """(node, s, x, yaw, scale) exactly like BiomeView.place (no course/tunnel gaps)."""
    out = []
    names = sorted(extras_by_node)  # the renderer iterates kit.names('side_') in file order; order only salts
    for index, name in enumerate(names):
        x = extras_by_node[name]
        every = max(2.0, float(x.get("every", 12)))
        chance = float(x.get("chance", 0.6))
        side = x.get("side", "both")
        slot = SLOTS.get(x.get("slot", "wall"), SLOTS["wall"])
        jitter = x.get("slot", "wall") != "wall"
        sides = [-1] if side == "left" else [1] if side == "right" else [-1, 1]
        for i in range(math.floor((s0 - 10) / every), math.floor(s1 / every) + 1):
            for sd in sides:
                salt = index * 37 + sd + 5
                if hash32(i, salt) >= chance:
                    continue
                s = i * every + (hash32(i, salt + 1) - 0.5) * every * 0.6
                px = sd * (slot[0] + (slot[1] - slot[0]) * hash32(i, salt + 2))
                yaw = (0.0 if sd > 0 else math.pi) + ((hash32(i, salt + 3) - 0.5) * 0.5 if jitter else 0.0)
                k = 0.85 + 0.35 * hash32(i, salt + 4) if jitter else 1.0
                out.append((name, s, px, yaw, k))
    return out


def fog_materials(mats, color, near, far):
    """three.js-style linear fog on every material (view distance), for the game shot."""
    fc = mat.rgba(color)
    done = []
    for m in mats:
        if m is None or m in done or not m.use_nodes:
            continue
        done.append(m)
        nt = m.node_tree
        out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None)
        if out is None or not out.inputs["Surface"].is_linked:
            continue
        src = out.inputs["Surface"].links[0].from_socket
        cam = nt.nodes.new("ShaderNodeCameraData")
        f = nt.nodes.new("ShaderNodeMapRange")
        f.clamp = True
        f.inputs["From Min"].default_value = near
        f.inputs["From Max"].default_value = far
        nt.links.new(cam.outputs["View Distance"], f.inputs["Value"])
        em = nt.nodes.new("ShaderNodeEmission")
        em.inputs["Color"].default_value = fc
        mix = nt.nodes.new("ShaderNodeMixShader")
        mix.name = "_fog_mix"
        nt.links.new(f.outputs["Result"], mix.inputs[0])
        nt.links.new(src, mix.inputs[1])
        nt.links.new(em.outputs["Emission"], mix.inputs[2])
        nt.links.new(mix.outputs[0], out.inputs["Surface"])
    return done


def sky_world(path, strength=1.0, hemi=None, hemi_strength=0.0, name="_game_world"):
    """World from an equirect made by render_sky (forward = +Y at the image centre). The camera sees the
    panorama as is; lighting gets strength * pano (+ a hemisphere tint like three's HemisphereLight)."""
    w = bpy.data.worlds.new(name)
    nt = w.node_tree
    nt.nodes.clear()
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Rotation"].default_value = (0.0, 0.0, math.radians(90.0))  # +Y (pano centre) -> Blender env u=0.5
    nt.links.new(tc.outputs["Generated"], mp.inputs["Vector"])
    env = nt.nodes.new("ShaderNodeTexEnvironment")
    env.image = bpy.data.images.load(path, check_existing=True)
    nt.links.new(mp.outputs["Vector"], env.inputs["Vector"])
    lp = nt.nodes.new("ShaderNodeLightPath")
    cam_bg = nt.nodes.new("ShaderNodeBackground")
    nt.links.new(env.outputs["Color"], cam_bg.inputs["Color"])
    lit = nt.nodes.new("ShaderNodeBackground")
    lit.inputs["Strength"].default_value = strength
    col = env.outputs["Color"]
    if hemi is not None:
        sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        nt.links.new(tc.outputs["Generated"], sep.inputs[0])
        rng = nt.nodes.new("ShaderNodeMapRange")
        rng.inputs["From Min"].default_value = -1.0
        rng.inputs["From Max"].default_value = 1.0
        nt.links.new(sep.outputs["Z"], rng.inputs["Value"])
        hm = nt.nodes.new("ShaderNodeMix")
        hm.data_type = "RGBA"
        nt.links.new(rng.outputs["Result"], hm.inputs[0])
        hm.inputs[6].default_value = mat.rgba(hemi[1])
        hm.inputs[7].default_value = mat.rgba(hemi[0])
        sc = nt.nodes.new("ShaderNodeMix")
        sc.data_type = "RGBA"
        sc.blend_type = "ADD"
        sc.inputs[0].default_value = 1.0
        nt.links.new(env.outputs["Color"], sc.inputs[6])
        # hemi colour scaled so strength * (pano + k * hemi) ~ env * pano + hemi / pi
        k = hemi_strength / math.pi / max(strength, 1e-3)
        scl = nt.nodes.new("ShaderNodeVectorMath")
        scl.operation = "SCALE"
        nt.links.new(hm.outputs[2], scl.inputs[0])
        scl.inputs["Scale"].default_value = k
        nt.links.new(scl.outputs[0], sc.inputs[7])
        col = sc.outputs[2]
    nt.links.new(col, lit.inputs["Color"])
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(lp.outputs["Is Camera Ray"], mix.inputs[0])
    nt.links.new(lit.outputs[0], mix.inputs[1])
    nt.links.new(cam_bg.outputs[0], mix.inputs[2])
    out = nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(mix.outputs[0], out.inputs["Surface"])
    return w


def fake_feed_material(name="_game_feed", k=0.55):
    """Stand-in for the renderer's feed atlas on the lane screens: tiles of colour with 'text' bars."""
    m = mat.new_material(name)
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    info = nt.nodes.new("ShaderNodeObjectInfo")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    cr = ramp.color_ramp
    cr.interpolation = "CONSTANT"
    pal = ["#ff3d7f", "#7b2eff", "#1fd1ff", "#ffb020", "#2effa0", "#ff5a2e", "#b388ff"]
    while len(cr.elements) < len(pal):
        cr.elements.new(0.5)
    for i, c in enumerate(pal):
        cr.elements[i].position = i / len(pal)
        cr.elements[i].color = mat.rgba(c)
    nt.links.new(info.outputs["Random"], ramp.inputs["Fac"])
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["UV"], sep.inputs[0])
    # gradient top-to-bottom plus dark caption band
    grad = nt.nodes.new("ShaderNodeMapRange")
    grad.inputs["From Min"].default_value = 0.0
    grad.inputs["From Max"].default_value = 1.0
    grad.inputs["To Min"].default_value = 0.25
    grad.inputs["To Max"].default_value = 1.0
    nt.links.new(sep.outputs["Y"], grad.inputs["Value"])
    mul = nt.nodes.new("ShaderNodeMix")
    mul.data_type = "RGBA"
    mul.blend_type = "MULTIPLY"
    mul.inputs[0].default_value = 1.0
    nt.links.new(ramp.outputs["Color"], mul.inputs[6])
    nt.links.new(grad.outputs["Result"], mul.inputs[7])
    em.inputs["Strength"].default_value = k * 0.9
    nt.links.new(mul.outputs[2], em.inputs["Color"])
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    return m


def game_view(out_path, nodes, extras, sky_path, look, length=150.0, size=(620, 1340), runner=True,
              engine="EEVEE", samples=48, extra_objects=(), overhang_at=None, tunnel=None, cam_y=0.0):
    """Camera 3.5 m up, 6.4 m behind the runner, looking down the track (portrait, fov 70 like a phone).
    Deck rows every 4.4 m, lane screens, scenery placed like the renderer, linear fog."""
    sc = bpy.context.scene
    made = []

    def inst(src, loc, yaw=0.0, k=1.0):
        o = bpy.data.objects.new(src.name + "_g", src.data)
        o.location = loc
        o.rotation_euler = (0.0, 0.0, yaw)
        o.scale = (k, k, k)
        lib.link(o)
        made.append(o)
        return o

    for o in list(nodes.values()):
        o.hide_render = True
    feed = fake_feed_material()
    tile = MB([feed])
    tile.face(tile.verts([(-0.96, -2.03, 0.011), (0.96, -2.03, 0.011), (0.96, 2.03, 0.011), (-0.96, 2.03, 0.011)]))
    tile_o = tile.build("_game_tile")
    mesh.uv_fit_faces(tile_o)
    tile_o.hide_render = True
    made.append(tile_o)
    rows = range(-3, int(length / 4.4) + 2)
    for i in rows:
        y = i * 4.4 + 2.2
        if "deck" in nodes:
            inst(nodes["deck"], (0, y, 0))
        if "deck_seam" in nodes:
            inst(nodes["deck_seam"], (0, y, 0))
        for lane in (-1, 0, 1):
            inst(tile_o, (lane * 2.2, y, 0))
    for name, s, x, yaw, k in placements(extras, -10.0, length + 60.0):
        if name in nodes and not (tunnel and tunnel[0] - 10 <= s <= tunnel[1] + 10):
            inst(nodes[name], (x, s, 0.0), yaw, k)
    if tunnel and "tunnel" in nodes:
        n = max(1, round((tunnel[1] - tunnel[0]) / 4.4))
        step = (tunnel[1] - tunnel[0]) / n
        for i in range(n):
            o = inst(nodes["tunnel"], (0, tunnel[0] + (i + 0.5) * step, 0))
            o.scale = (1, step / 4.4, 1)
    if overhang_at is not None and "overhang" in nodes:
        inst(nodes["overhang"], (0, overhang_at, 0))
    for o in extra_objects:
        made.append(o)
    if runner:
        body = lathe("_game_runner", [(0.0, 0.0), (0.16, 0.05), (0.2, 0.9), (0.24, 1.35), (0.12, 1.5), (0.13, 1.62),
                                      (0.0, 1.75)], 12, mat.flat("_runner", "#1c1826", rough=0.7))
        body.location = (0, cam_y, 0)
        made.append(body)
    cam_d = bpy.data.cameras.new("_game_cam")
    cam_d.sensor_fit = "VERTICAL"
    cam_d.angle_y = math.radians(70.0)
    cam_d.clip_start = 0.1
    cam_d.clip_end = 400.0
    cam = lib.link(bpy.data.objects.new("_game_cam", cam_d))
    cam.location = (0.0, cam_y - 6.4, 3.5)
    cam.rotation_euler = (Vector((0.0, cam_y + 9.0, 1.1)) - cam.location).to_track_quat("-Z", "Y").to_euler()
    made.append(cam)
    sun_d = bpy.data.lights.new("_game_sun", "SUN")
    sun_d.energy = look["sunI"]
    sun_d.color = mat.rgb(look.get("sun", "#ffffff"))
    sun = lib.link(bpy.data.objects.new("_game_sun", sun_d))
    sun.rotation_euler = Vector((-4.0, 6.0, -10.0)).to_track_quat("-Z", "Y").to_euler()  # three (4,10,6)
    made.append(sun)
    world = sky_world(sky_path, strength=look["env"], hemi=(look["hemi_sky"], look["hemi_ground"]),
                      hemi_strength=look["hemi"])
    mats = set()
    for o in made:
        if o.type == "MESH":
            mats.update(m for m in o.data.materials if m is not None)
    fogged = fog_materials(mats, look["fog"], look["near"], look["far"])
    saved = dict(engine=sc.render.engine, world=sc.world, camera=sc.camera, x=sc.render.resolution_x,
                 y=sc.render.resolution_y, view=sc.view_settings.view_transform, look=sc.view_settings.look,
                 exposure=sc.view_settings.exposure)
    sc.render.engine = "CYCLES" if engine == "CYCLES" else "BLENDER_EEVEE"
    if engine == "CYCLES":
        bake.setup_cycles(samples)
        sc.cycles.use_denoising = True
    else:
        sc.eevee.taa_render_samples = samples
        if hasattr(sc.eevee, "use_raytracing"):
            sc.eevee.use_raytracing = True
    sc.world = world
    sc.camera = cam
    sc.render.resolution_x, sc.render.resolution_y = size
    sc.render.resolution_percentage = 100
    sc.render.film_transparent = False
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "AgX - Medium High Contrast" if "AgX - Medium High Contrast" in [
        i.name for i in sc.view_settings.bl_rna.properties["look"].enum_items] else "None"
    sc.view_settings.exposure = math.log2(max(look.get("exposure", 1.0), 1e-3))
    sc.render.image_settings.file_format = "PNG"
    sc.render.filepath = out_path
    bpy.ops.render.render(write_still=True)
    log(f"game view: {out_path}")
    # clean up
    for m in fogged:
        nt = m.node_tree
        mix = nt.nodes.get("_fog_mix")
        if mix is not None:
            src = mix.inputs[1].links[0].from_socket
            out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
            nt.links.new(src, out.inputs["Surface"])
            for n in [n for n in nt.nodes if n.type in ("CAMERA", "MAP_RANGE", "EMISSION", "MIX_SHADER")
                      and n.name.startswith(("Camera", "Map Range", "Emission", "_fog_mix"))]:
                if n.type == "EMISSION" and n.outputs[0].is_linked:
                    continue
                nt.nodes.remove(n)
    for o in made:
        bpy.data.objects.remove(o, do_unlink=True)
    for o in nodes.values():
        o.hide_render = False
    sc.render.engine, sc.world, sc.camera = saved["engine"], saved["world"], saved["camera"]
    sc.render.resolution_x, sc.render.resolution_y = saved["x"], saved["y"]
    sc.view_settings.view_transform, sc.view_settings.look = saved["view"], saved["look"]
    sc.view_settings.exposure = saved["exposure"]
    return out_path


def pano_camera(z=4.0, clip=6000.0):
    cd = bpy.data.cameras.new("_sky_cam")
    cd.type = "PANO"
    cd.panorama_type = "EQUIRECTANGULAR"
    cd.clip_start = 0.5
    cd.clip_end = clip
    cam = lib.link(bpy.data.objects.new("_sky_cam", cd))
    cam.location = (0.0, 0.0, z)
    cam.rotation_euler = (math.radians(90.0), 0.0, 0.0)  # looking along +Y, Z up
    return cam


def render_sky(out_jpg, cam, world, size=(2048, 1024), samples=96, quality=88, exposure=0.0, max_kb=600, only=None):
    """Cycles equirect render to JPG (quality stepped down until it fits max_kb). only: the objects
    to render (everything else is hidden meanwhile)."""
    sc = bpy.context.scene
    hidden = {}
    if only is not None:
        keep = set(only)
        for o in sc.objects:
            hidden[o] = o.hide_render
            o.hide_render = o not in keep
    saved = dict(engine=sc.render.engine, world=sc.world, camera=sc.camera, view=sc.view_settings.view_transform,
                 x=sc.render.resolution_x, y=sc.render.resolution_y, look=sc.view_settings.look)
    bake.setup_cycles(samples)
    sc.cycles.use_denoising = True
    sc.world = world
    sc.camera = cam
    sc.render.resolution_x, sc.render.resolution_y = size
    sc.render.resolution_percentage = 100
    sc.render.film_transparent = False
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    sc.view_settings.exposure = exposure
    tmp = out_jpg + ".png"
    sc.render.image_settings.file_format = "PNG"
    sc.render.filepath = tmp
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(tmp, check_existing=False)
    q = quality
    while True:
        sc.render.image_settings.file_format = "JPEG"
        sc.render.image_settings.quality = q
        img.save_render(out_jpg, scene=sc)
        kb = os.path.getsize(out_jpg) / 1024
        if kb <= max_kb or q <= 60:
            break
        q -= 4
    bpy.data.images.remove(img)
    os.remove(tmp)
    log(f"sky: {out_jpg} {size[0]}x{size[1]} q{q} {kb:.0f} KB")
    sc.render.engine, sc.world, sc.camera = saved["engine"], saved["world"], saved["camera"]
    sc.view_settings.view_transform, sc.view_settings.look = saved["view"], saved["look"]
    sc.view_settings.exposure = 0.0
    sc.render.resolution_x, sc.render.resolution_y = saved["x"], saved["y"]
    for o, h in hidden.items():
        o.hide_render = h
    return out_jpg


def world_nodes(name):
    w = bpy.data.worlds.new(name)
    nt = w.node_tree
    nt.nodes.clear()
    return w, nt


def emission_material(name, color, strength, fade_color=None, fade_dist=None, alpha=None):
    """Sky-scene emitter; with fade_* it mixes toward fade_color by camera distance (aerial haze)."""
    m = mat.new_material(name)
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Strength"].default_value = strength
    if isinstance(color, bpy.types.NodeSocket):
        nt.links.new(color, em.inputs["Color"])
    else:
        em.inputs["Color"].default_value = mat.rgba(color)
    shader = em.outputs[0]
    nt.links.new(shader, out.inputs["Surface"])
    return m


SCENERY_VIEWS = {"track": (-1.0, -0.55, 0.28), "face": (-1.0, 0.08, 0.1), "back": (0.8, 0.9, 0.45)}
PIECE_VIEWS = {"game": (0.0, -1.0, 0.42), "three_quarter": (0.8, 0.9, 0.45), "side": (1.0, 0.0, 0.12)}


def preview_piece(out_dir, name, parts, views, size=(560, 700), zmin=None, zmax=None, samples=24):
    """Eevee previews of one node's parts (everything else hidden), framed on the part of it above
    `zmin` (tall scenery drops to z -40)."""
    everything = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    saved = {o: o.hide_render for o in everything}
    for o in everything:
        o.hide_render = o not in parts
    lo, hi = mesh.bounds(parts)
    if zmin is not None:
        lo.z = max(lo.z, zmin)
    if zmax is not None:
        hi.z = min(hi.z, zmax)
    b = MB([])
    b.verts([(x, y, z) for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)])
    proxy = b.build("_frame_proxy")
    try:
        paths = []
        for vn, vd in views.items():
            paths += preview.render_previews(out_dir, [proxy], views=(vd,), size=size, prefix=f"{name}_{vn}",
                                             samples=samples, sheet=False)
        # render_previews names direction views "view0": rename to the view name
        out = []
        for vn, pth in zip(views, paths):
            dst = os.path.join(out_dir, f"{name}_{vn}.png")
            os.replace(pth, dst)
            out.append(dst)
        sheet(out, os.path.join(out_dir, f"{name}_sheet.png"))
    finally:
        bpy.data.objects.remove(proxy, do_unlink=True)
        for o, h in saved.items():
            o.hide_render = h
    return out


def sheet(paths, out, cols=None):
    paths = [p for p in paths if p and os.path.exists(p)]
    if paths:
        preview.contact_sheet(paths, out, cols=cols)
    return out


def font(name):
    """A font by file name from the system (macOS) folders, else Blender's built-in one."""
    for d in ("/System/Library/Fonts", "/System/Library/Fonts/Supplemental", "/Library/Fonts",
              os.path.expanduser("~/Library/Fonts")):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return bpy.data.fonts.load(p, check_existing=True)
    return None


def text_sheet(path, cells, cols, rows, cell_px=(512, 128)):
    """Render text cells into one PNG sheet (Eevee, orthographic, colours exact, transparent where no bg).
    cells: dicts text, fg, bg (None = transparent), font (file name), size (fraction of the cell height),
    pad (fraction of the width kept free), shape "rect" | "round" (pill bg). Returns {index: (u0, v0, u1, v1)}."""
    sc = bpy.context.scene
    cw, ch = 1.0 * cell_px[0] / cell_px[1], 1.0
    everything = [o for o in sc.objects]
    saved_h = {o: o.hide_render for o in everything}
    for o in everything:
        o.hide_render = True
    made, rects = [], {}
    for i, c in enumerate(cells):
        col, row = i % cols, i // cols
        cx = (col + 0.5) * cw
        cy = (rows - row - 0.5) * ch
        if c.get("bg"):
            b = MB([emission_material(f"_txt_bg{i}", c["bg"], 1.0)])
            if c.get("shape") == "round":
                pts = rrect_pts(cw * 0.98, ch * 0.9, ch * 0.45, 8, cx, cy)
            else:
                pts = rrect_pts(cw, ch, 0.001, 1, cx, cy)
            b.face(b.verts([(x, y, 0.0) for x, y in pts]))
            made.append(b.build(f"_txt_bgo{i}"))
        cu = bpy.data.curves.new(f"_txt{i}", "FONT")
        cu.body = c["text"]
        f = font(c.get("font", "")) if c.get("font") else None
        if f is not None:
            cu.font = f
        cu.align_x, cu.align_y = "CENTER", "CENTER"
        cu.space_character = c.get("tracking", 1.0)
        ob = lib.link(bpy.data.objects.new(f"_txt{i}", cu))
        ob.data.materials.append(emission_material(f"_txt_fg{i}", c.get("fg", "#ffffff"), 1.0))
        bpy.context.view_layer.update()
        w, h = max(ob.dimensions.x, 1e-3), max(ob.dimensions.y, 1e-3)
        k = min(cw * (1.0 - c.get("pad", 0.12)) / w, ch * c.get("size", 0.62) / h)
        ob.scale = (k, k, 1.0)
        ob.location = (cx, cy, 0.01)
        made.append(ob)
        rects[i] = (col / cols, (rows - row - 1) / rows, (col + 1) / cols, (rows - row) / rows)
    cam_d = bpy.data.cameras.new("_txt_cam")
    cam_d.type = "ORTHO"
    cam_d.ortho_scale = max(cols * cw, rows * ch)
    cam = lib.link(bpy.data.objects.new("_txt_cam", cam_d))
    cam.location = (cols * cw / 2, rows * ch / 2, 5.0)
    made.append(cam)
    saved = dict(engine=sc.render.engine, camera=sc.camera, x=sc.render.resolution_x, y=sc.render.resolution_y,
                 film=sc.render.film_transparent, view=sc.view_settings.view_transform, look=sc.view_settings.look,
                 world=sc.world)
    sc.render.engine = "BLENDER_EEVEE"
    sc.eevee.taa_render_samples = 16
    sc.camera = cam
    sc.render.resolution_x, sc.render.resolution_y = cols * cell_px[0], rows * cell_px[1]
    sc.render.resolution_percentage = 100
    sc.render.film_transparent = True
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGBA"
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    for o in made:
        bpy.data.objects.remove(o, do_unlink=True)
    for o, h in saved_h.items():
        o.hide_render = h
    sc.render.engine, sc.camera = saved["engine"], saved["camera"]
    sc.render.resolution_x, sc.render.resolution_y = saved["x"], saved["y"]
    sc.render.film_transparent = saved["film"]
    sc.view_settings.view_transform, sc.view_settings.look = saved["view"], saved["look"]
    sc.render.image_settings.color_mode = "RGB"
    log(f"text sheet: {path} ({len(cells)} cells)")
    return rects


def uv_to_cell(o, material, rect):
    """Squeeze the 0..1 UVs of faces on `material` into a sheet cell (u0, v0, u1, v1)."""
    me = o.data
    idx = [i for i, m in enumerate(me.materials) if m and m.name == material]
    lay = me.uv_layers.active
    u0, v0, u1, v1 = rect
    for p in me.polygons:
        if p.material_index in idx:
            for li in p.loop_indices:
                u, v = lay.data[li].uv
                lay.data[li].uv = (u0 + u * (u1 - u0), v0 + v * (v1 - v0))


# =================================================================== FEED CITY

FOG = "#07040f"
LOOK = dict(fog=FOG, near=45.0, far=160.0, hemi=1.3, hemi_sky="#a58cff", hemi_ground="#150a24", sun="#ffffff",
            sunI=1.6, exposure=1.0, env=0.5)
# the deck's Y loops: 0.485 m apart, plus +-1.94 where the phones' rounded corners start
DECK_YS = [-2.2, -1.94, -1.455, -0.97, -0.485, 0.0, 0.485, 0.97, 1.455, 1.94, 2.2]
LANES = (-2.2, 0.0, 2.2)


class FeedMats:
    def __init__(self):
        # graphite titanium frames, a polished diamond-cut chamfer, glossy black glass
        self.alu = metal("F_Alu", scale=0.45, tint="#8f8b99", rough_scale=0.7, rough_offset=0.05)
        self.alu_big = metal("F_AluBig", scale=3.5, tint="#8f8b99", rough_scale=0.7, rough_offset=0.05)
        self.polish = metal("F_Polish", scale=0.3, tint="#d4d0dc", rough=0.14, normal=0.2)
        self.polish_big = metal("F_PolishBig", scale=2.0, tint="#d4d0dc", rough=0.16, normal=0.2)
        self.glass = smudged("F_Glass", "#040406", rough=0.05, amount=0.3, scale=0.8)
        self.glass_big = smudged("F_GlassBig", "#040406", rough=0.05, amount=0.25, scale=6.0)
        self.back = smudged("F_Back", "#1d1a24", rough=0.32, amount=0.2, scale=1.2, smudge="SurfaceImperfections003")
        self.back_big = smudged("F_BackBig", "#1d1a24", rough=0.32, amount=0.2, scale=8.0,
                                smudge="SurfaceImperfections003")
        self.paint = mat.pbr("F_Paint", "Metal027", mapping="BOX", box_scale=1.5, tint="#8a8698")
        self.paint_big = mat.pbr("F_PaintBig", "Metal027", mapping="BOX", box_scale=6.0, tint="#8a8698")
        self.plastic = mat.pbr("F_Plastic", "Plastic010", mapping="BOX", box_scale=1.2, tint="#d9d8de")
        self.rubber = mat.pbr("F_Rubber", "Rubber004", mapping="BOX", box_scale=0.8, tint="#5a5860")
        self.chrome = mat.flat("F_Chrome", "#c9c7d2", rough=0.12, metal=1.0)
        self.lens = mat.flat("F_Lens", "#020203", rough=0.03)
        self.dark = mat.flat("F_Dark", "#0b0a0e", rough=0.6)
        self.off = mat.flat("F_Off", "#050507", rough=0.2)  # hidden display faces
        self.led = glow("F_Led", "#ffe2cc", 2.4)
        self.red = glow("F_Red", "#ff2233", 8.0)
        self.screen = mat.emissive_screen("ScreenFeed", "#6c62ff", 1.4, base="#050507")
        self.ad = mat.emissive_screen("AdFace", "#ff3d7f", 1.6, base="#050507")
        self.seam = mat.flat("Seam", "#9a40ff", rough=0.4, emission="#9a40ff", strength=3.0)


# ------------------------------------------------------------------ deck

def feed_deck(M, kit):
    """One 4.4 m row: three giant phones lying face up in a dark glass tray, the lane screens in their
    displays; aluminium curbs with antenna lines, ports and buttons on the outer sides."""
    # tray profile (x, z): up the left side, over the top, down the right side (then the bottom part)
    right = [(3.35, -0.10), (3.35, -0.014), (3.364, 0.0), (4.56, 0.0), (4.60, 0.075), (4.655, 0.10), (4.765, 0.10),
             (4.80, 0.065), (4.80, -0.52)]
    left = [(-x, z) for x, z in reversed(right)]
    lanes_top = [(-3.25, -0.10), (-1.15, -0.10), (-1.05, -0.10), (1.05, -0.10), (1.15, -0.10), (3.25, -0.10)]
    prof = left + lanes_top + right
    ix = {p: i for i, p in enumerate(prof)}
    hidden_spans = {ix[(-3.25, -0.10)], ix[(-1.05, -0.10)], ix[(1.15, -0.10)]}  # segment j starts at these

    shoulder = decorate(smudged("F_DeckShoulder", "#050508", rough=0.06, amount=0.16, scale=2.2), [
        # bottom-speaker style grille on both shoulders, and a status LED
        *[dict(kind="dots", plane="xy", c=(sx * 3.95, -0.9), s=(0.28, 0.5), r=0.05, pitch=0.05, hole=0.013,
               color="#010101", rough=0.7, depth=-0.004, face=(0, 0, 1)) for sx in (-1, 1)],
        *[dict(kind="rect", plane="xy", c=(sx * 3.95, -0.9), s=(0.3, 0.52), r=0.07, color="#0c0b10", rough=0.35,
               depth=-0.002, face=(0, 0, 1)) for sx in (-1, 1)],
        *[dict(kind="circle", plane="xy", c=(sx * 4.25, 1.3), s=(0.028, 0.0), emit=("#42ffb0", 3.0),
               color="#103020", face=(0, 0, 1)) for sx in (-1, 1)],
    ], soft=0.006)
    curb = decorate(metal("F_DeckCurb", scale=0.4, tint="#9b97a6", rough_scale=0.6, rough_offset=0.04), [
        # antenna lines across the curb and down the outer side
        *[dict(kind="rect", plane="yz", c=(yy, 0.0), s=(0.018, 2.0), color="#15141a", rough=0.55, metal=0.0,
               depth=-0.002, w=(4.5, 4.9) if sx > 0 else (-4.9, -4.5)) for sx in (-1, 1) for yy in (-1.55, 1.55)],
        # USB-C port and speaker holes on the outer side face
        *[dict(kind="rect", plane="yz", c=(-0.3, -0.22), s=(0.2, 0.065), r=0.065, color="#030304", rough=0.8,
               metal=0.0, depth=-0.03, face=(sx, 0, 0)) for sx in (-1, 1)],
        *[dict(kind="dots", plane="yz", c=(yy, -0.22), s=(0.2, 0.03), pitch=(0.075, 1.0), hole=0.022,
               stagger=False, color="#020203", rough=0.8, metal=0.0, depth=-0.02, face=(sx, 0, 0))
          for sx in (-1, 1) for yy in (-0.8, 0.2)],
        # screws either side of the port
        *[dict(kind="circle", plane="yz", c=(yy, -0.22), s=(0.018, 0), color="#6f6c78", rough=0.3,
               depth=-0.003, face=(sx, 0, 0)) for sx in (-1, 1) for yy in (-1.12, 0.52)],
        # the SIM tray
        *[dict(kind="rect", plane="yz", c=(1.05, -0.2), s=(0.34, 0.05), r=0.05, color="#6b6874", rough=0.4,
               depth=-0.004, face=(sx, 0, 0)) for sx in (-1, 1)],
        *[dict(kind="circle", plane="yz", c=(0.78, -0.2), s=(0.012, 0), color="#050506", depth=-0.004,
               face=(sx, 0, 0)) for sx in (-1, 1)],
        # volume rocker and action button (raised, polished), baked
        *[dict(kind="rect", plane="yz", c=(yy, -0.36), s=(ln / 2, 0.04), r=0.04, color="#c9c5d2", rough=0.14,
               depth=0.012, face=(sx, 0, 0)) for sx in (-1, 1) for yy, ln in ((0.55, 0.42), (1.08, 0.42),
                                                                              (-1.75, 0.22))],
    ], soft=0.006)
    channel = smudged("F_DeckChannel", "#07060a", rough=0.2, amount=0.12, scale=1.6)
    mats = [channel, shoulder, curb]

    def seg_mat(j, k):
        x0, z0 = prof[j]
        x1, z1 = prof[j + 1]
        if j in hidden_spans and 0 < k < len(DECK_YS) - 2:
            return None  # under a phone: hidden (the phone's display face closes it)
        if abs(x0) >= 4.56 - 1e-6 and abs(x1) >= 4.56 - 1e-6:
            return 2
        if abs(x0) >= 3.36 and abs(x1) >= 3.36 and z0 >= -0.001 and z1 >= -0.001:
            return 1
        if abs(abs(x0) - 3.35) < 0.02 and abs(abs(x1) - 3.35) < 0.02:  # shoulder inner wall
            return 1
        return 0
    top = sweep("deck_top", lambda y: prof, DECK_YS, seg_mat, mats)

    # underside: chamfer + flat belly, painted
    under_prof = [(4.80, -0.52), (4.74, -0.58), (-4.74, -0.58), (-4.80, -0.52)]
    belly = decorate(mat.pbr("F_DeckBelly", "Metal027", mapping="BOX", box_scale=1.2, tint="#6d6a78"), [
        dict(kind="lines", plane="xy", axis="u", pitch=2.4, width=0.02, color="#050506", depth=-0.004),
        *[dict(kind="circle", plane="xy", c=(sx * 3.0, yy), s=(0.03, 0), color="#9a98a4", metal=1.0, rough=0.3)
          for sx in (-1, 1) for yy in (-1.8, 1.8)],
    ], soft=0.008)
    under = sweep("deck_under", lambda y: under_prof, DECK_YS, lambda j, k: 0, [belly])

    phones, hidden = [], []
    for cx in LANES:
        face = decorate(smudged(f"F_PhoneFace{cx:+.0f}", "#030304", rough=0.05, amount=0.35, scale=0.7), [
            # earpiece slit and front camera in the far border, a proximity dot
            dict(kind="rect", plane="xy", c=(cx, 2.084), s=(0.2, 0.011), r=0.011, color="#16151b", rough=0.6,
                 depth=-0.004),
            dict(kind="dots", plane="xy", c=(cx, 2.084), s=(0.19, 0.008), pitch=0.012, hole=0.004,
                 color="#050506", rough=0.7),
            dict(kind="circle", plane="xy", c=(cx + 0.36, 2.084), s=(0.024, 0), color="#0b0d1a", rough=0.02,
                 depth=-0.002),
            dict(kind="ring", plane="xy", c=(cx + 0.36, 2.084), s=(0.03, 0.004), color="#2b2a36", metal=1.0,
                 rough=0.2),
            dict(kind="circle", plane="xy", c=(cx - 0.3, 2.084), s=(0.01, 0), color="#101018"),
        ], soft=0.004)
        frame = decorate(metal(f"F_PhoneFrame{cx:+.0f}", scale=0.35, tint="#8f8b99", rough_scale=0.65,
                               rough_offset=0.05), [
            # antenna lines: across the long sides near the ends, and across the short sides
            *[dict(kind="rect", plane="yz", c=(yy, 0.0), s=(0.012, 1.0), color="#1a1920", rough=0.5, metal=0.0,
                   w=(cx + sx * 1.08 - 0.06, cx + sx * 1.08 + 0.06)) for sx in (-1, 1) for yy in (-1.72, 1.72)],
            *[dict(kind="rect", plane="xz", c=(cx + xx, 0.0), s=(0.012, 1.0), color="#1a1920", rough=0.5,
                   metal=0.0, w=(sy * 2.16 - 0.06, sy * 2.16 + 0.06)) for sy in (-1, 1) for xx in (-0.62, 0.62)],
        ], soft=0.004)
        polish = M.polish
        W, H, Tt, r = 2.10, 4.32, 0.10, 0.22
        prof_p = [(0.0, 0.0), (0.0, Tt - 0.03), (0.028, Tt)]
        ph = phone(f"deck_phone{cx:+.0f}", W, H, Tt, r, frame, face, M.off, screen=(1.92, 4.06, 0.0, 0.012),
                   screen_mat=M.off, chamfer=polish, seg=3, prof=prof_p, cap_back=False, xform=T(cx, 0, -0.10))
        # split the hidden display face into its own low-weight part
        me = ph.data
        off_idx = [i for i, m in enumerate(me.materials) if m == M.off]
        hid = mesh.duplicate(ph, f"deck_hidden{cx:+.0f}")
        import bmesh
        for obj, keep_off in ((ph, False), (hid, True)):
            bm = bmesh.new()
            bm.from_mesh(obj.data)
            kill = [f for f in bm.faces if (f.material_index in off_idx) != keep_off]
            bmesh.ops.delete(bm, geom=kill, context="FACES")
            bm.to_mesh(obj.data)
            bm.free()
        phones.append(ph)
        hidden.append(hid)

    top_all = join([top] + phones, "deck_top")
    hidden_all = join(hidden, "deck_hidden")
    for o in (top_all, hidden_all, under):
        loops(o, positions=DECK_YS[1:-1])
        mesh.clean(o, recalc_normals=False)
        finish(o, 40)
    weight(top_all, 7.0)
    weight(hidden_all, 0.02)
    weight(under, 0.6)
    kit.add("deck", [top_all, hidden_all, under], share=0.22)

    # lane seams: glowing strips in the channels (material Seam: the renderer gives it the zone glow)
    seams = []
    for sx in (-3.3, -1.1, 1.1, 3.3):
        b = MB([M.seam])
        w2 = 0.017
        pr = [(sx - w2, -0.10), (sx - w2, -0.074), (sx + w2, -0.074), (sx + w2, -0.10)]
        seams.append(sweep("seam", lambda y, pr=pr: pr, DECK_YS, lambda j, k: 0, [M.seam]))
    seam = join(seams, "deck_seam")
    finish(seam, 30)
    kit.add_plain("deck_seam", seam)


# ------------------------------------------------------------------ scenery

def lens_cluster(M, cx, cy, z, s, name="lens"):
    """Camera bump lenses (for a phone back facing +Z at height z): ring + glass, scale s."""
    parts = []
    for i, (dx, dy) in enumerate(((-0.24, 0.24), (-0.24, -0.24), (0.24, 0.0))):
        x, y = cx + dx * s, cy + dy * s
        parts.append(lathe(f"{name}{i}", [(0.17 * s, 0.0), (0.17 * s, 0.05 * s), (0.155 * s, 0.07 * s),
                                          (0.12 * s, 0.07 * s), (0.1 * s, 0.05 * s)], 16,
                           [M.polish_big, M.polish_big, M.polish_big, M.alu_big], cap_top=M.lens,
                           xform=T(x, y, z)))
    parts.append(lathe(f"{name}_flash", [(0.05 * s, 0.0), (0.05 * s, 0.015 * s)], 10, [M.chrome], cap_top=M.led,
                       xform=T(cx + 0.24 * s, cy + 0.3 * s, z)))
    return parts


def feed_tower(M, kit):
    """Far: a flagship phone standing on end in a charging dock whose stalk drops into the abyss."""
    W, H, Tt, r = 20.0, 42.0, 2.4, 2.8
    z0 = 7.0
    # standing: local +Z (front) -> -X (the track), local +Y (the phone's top) -> +Z, back at x = Tt
    stand = basis((-1, 0, 0), (0, 0, 1), (Tt, 0, z0 + H / 2))
    frame = decorate(metal("F_TowerFrame", scale=3.0, tint="#8f8b99", rough_scale=0.65), [
        # antenna lines across the side edges and the top and bottom edges
        *[dict(kind="rect", plane="xz", c=(0, zz), s=(4.0, 0.09), color="#17161c", rough=0.5, metal=0.0,
               face=(0, sy, 0)) for sy in (-1, 1) for zz in (z0 + 4.5, z0 + H - 4.5)],
        *[dict(kind="rect", plane="yz", c=(yy, 0), s=(0.09, 200), color="#17161c", rough=0.5, metal=0.0,
               face=(0, 0, sz)) for yy in (-6.5, 6.5) for sz in (-1, 1)],
        # speaker grille on the bottom edge (seen from below on drops), mic holes on top
        dict(kind="dots", plane="xy", c=(Tt / 2, -5.0), s=(0.35, 2.6), pitch=0.28, hole=0.09, color="#020203",
             depth=-0.06, face=(0, 0, -1)),
        dict(kind="dots", plane="xy", c=(Tt / 2, 5.0), s=(0.2, 0.6), pitch=0.3, hole=0.08, color="#020203",
             depth=-0.05, face=(0, 0, 1)),
    ], soft=0.05)
    face = smudged("F_TowerFace", "#030304", rough=0.05, amount=0.25, scale=5.0)
    body = phone("tower_body", W, H, Tt, r, frame, face, M.back_big, screen=(W - 1.0, H - 1.2, 0.0, r - 0.5),
                 screen_mat=M.screen, chamfer=M.polish_big, seg=5,
                 prof=[(0.35, 0.0), (0.12, 0.08), (0.0, 0.35), (0.0, Tt - 0.3), (0.3, Tt)], xform=stand)
    island = rbox("tower_island", 3.4, 1.0, 0.1, 0.5, 0.03, M.lens, seg=4,
                  xform=basis((-1, 0, 0), (0, 0, 1), (-0.05, 0, z0 + H - 1.9)))
    # camera bump on the back (faces +X), top left seen from behind
    bump = rbox("tower_bump", 8.0, 8.4, 0.5, 2.2, 0.2, M.back_big, seg=4,
                xform=basis((1, 0, 0), (0, 0, 1), (Tt + 0.25, -4.6, z0 + H - 5.2)))
    lenses = [xf(p, basis((1, 0, 0), (0, 0, 1), (Tt + 0.5, -4.6, z0 + H - 5.2))) for p in
              lens_cluster(M, 0, 0, 0.0, 9.0, "tower_lens")]
    # side buttons: volume + action on -Y (the edge you run toward on the right), power on +Y
    btns = []
    for sy, spots in ((-1, ((z0 + H - 9.0, 3.2), (z0 + H - 13.5, 3.2), (z0 + H - 5.5, 1.6))),
                      (1, ((z0 + H - 11.0, 5.0),))):
        for zz, ln in spots:
            btns.append(rbox("tower_btn", ln, 0.9, 0.22, 0.42, 0.06, M.polish_big, seg=2,
                             xform=basis((0, sy, 0), (1, 0, 0), (Tt / 2, sy * W / 2, zz))))
    # charging dock: a cradle round the bottom edge, a status LED, a stalk down into the void
    cradle = rbox("tower_cradle", 23.0, 5.5, 6.0, 2.4, 0.6, M.paint_big, seg=4,
                  xform=basis((0, 0, 1), (1, 0, 0), (Tt / 2, 0, z0 - 1.5)))
    cradle_led = rbox("tower_led", 2.2, 0.3, 0.08, 0.15, 0.02, M.led, seg=2,
                      xform=basis((-1, 0, 0), (0, 0, 1), (Tt / 2 - 2.76, 0, z0 + 0.3)))
    stalk = rbox("tower_stalk", 9.0, 4.0, 44.0, 1.6, 0.3, M.paint_big, seg=3,
                 xform=basis((0, 0, 1), (1, 0, 0), (Tt / 2 + 0.6, 0, z0 - 4.0 - 22.0)))
    o = join([body, island, bump, cradle, cradle_led, stalk] + lenses + btns, "side_tower")
    loops(o, 1.0)
    finish(o, 38)
    kit.add("side_tower", away_parts(o, "side_tower", 0.12), dict(slot="far", every=30.0, chance=0.8, side="both"), share=0.09)


def feed_fold(M, kit):
    """Far: a foldable standing half open like a book on a round plinth; one inner display folded
    across both halves (one feed cell over the crease), facing the track."""
    W, H, Tt, r = 10.2, 36.0, 1.3, 2.0
    z0 = 10.0
    half_open = math.radians(60.0)  # each half from the -X axis
    hinge = Vector((8.0, 0.0, 0.0))
    frame = metal("F_FoldFrame", scale=3.0, tint="#b7a8c9", rough_scale=0.55)
    face = smudged("F_FoldFace", "#030304", rough=0.05, amount=0.25, scale=5.0)
    parts = []
    for sgn in (-1, 1):
        dirv = Vector((-math.cos(half_open), sgn * math.sin(half_open), 0.0))
        nrm = Vector((-math.sin(half_open), -sgn * math.cos(half_open), 0.0))
        centre = hinge + dirv * (W / 2 + 0.55)
        Mh = basis(nrm, (0, 0, 1), centre - nrm * (Tt * 0.5) + Vector((0, 0, z0 + H / 2)))
        half = phone(f"fold_half{sgn:+d}", W, H, Tt, r, frame, face, M.back_big,
                     screen=(W - 0.6, H - 0.8, 0, r - 0.3), screen_mat=M.screen, chamfer=M.polish_big, seg=5,
                     prof=[(0.2, 0.0), (0.0, 0.2), (0.0, Tt - 0.2), (0.2, Tt)], xform=Mh)
        # one display over both halves: the +Y half is the viewer's left
        lay = half.data.uv_layers["UVMap"]
        si = [i for i, m in enumerate(half.data.materials) if m.name == "ScreenFeed"][0]
        for poly in half.data.polygons:
            if poly.material_index == si:
                for li in poly.loop_indices:
                    u, v = lay.data[li].uv
                    lay.data[li].uv = ((0.5 * u) if sgn > 0 else (0.5 + 0.5 * u), v)
        parts.append(half)
    hinge_o = lathe("fold_hinge", [(0.0, z0 - 0.4), (1.25, z0 - 0.4), (1.25, z0 + H + 0.4), (0.0, z0 + H + 0.4)], 16,
                    [M.polish_big, M.alu_big, M.polish_big], xform=T(hinge.x, 0, 0))
    base = lathe("fold_base", [(0.0, z0 - 3.2), (7.4, z0 - 3.2), (7.6, z0 - 2.6), (7.6, z0 - 1.2), (7.0, z0 - 0.5),
                               (0.0, z0 - 0.5)], 32, [M.paint_big, M.paint_big, M.polish_big, M.paint_big,
                                                      M.paint_big], xform=T(hinge.x - 3.0, 0, 0))
    ring = lathe("fold_ring", [(7.62, z0 - 2.3), (7.62, z0 - 1.6)], 32, glow("F_FoldLed", "#b48cff", 3.0),
                 xform=T(hinge.x - 3.0, 0, 0))
    column = lathe("fold_column", [(3.4, -44.0), (3.4, z0 - 3.2)], 16, M.paint_big, xform=T(hinge.x - 3.0, 0, 0))
    o = join(parts + [hinge_o, base, ring, column], "side_fold")
    loops(o, 1.0)
    finish(o, 38)
    kit.add("side_fold", away_parts(o, "side_fold", 0.1, away=0.8), dict(slot="far", every=44.0, chance=0.6,
                                                                           side="both"), share=0.06)


def feed_stack(M, kit):
    """Mid: a residential slab whose balconies are giant notification pills, stacked like unread banners."""
    import random
    rnd = random.Random(7)
    Wy, D = 11.0, 7.0      # slab length along Y, depth away from the track
    x0 = 2.2               # facade plane (pills stick out toward the track from here)
    top = 36.0
    fl = 3.6  # floor height: pills sit on the slabs
    facade = decorate(smudged("F_StackFacade", "#07060b", rough=0.07, amount=0.12, scale=8.0), [
        # mullions every 1.2 m, a spandrel band at each floor slab
        dict(kind="lines", plane="yz", c=(0.0, 0.0), s=(Wy / 2 - 0.3, 200), pitch=1.2, width=0.09, axis="u",
             color="#23202b", rough=0.35, metal=0.6, w=(x0 - 0.1, x0 + 0.1)),
        dict(kind="lines", plane="yz", c=(0.0, 0.0), s=(Wy / 2 - 0.3, 200), pitch=fl, width=0.75, axis="v",
             phase=0.3, color="#15131b", rough=0.4, w=(x0 - 0.1, x0 + 0.1)),
        # a few lit rooms behind the glass, warm and screen-blue
        dict(kind="grid", plane="yz", c=(0.0, fl / 2 + 0.3), s=(Wy / 2 - 0.3, 200), pitch=(2.4, fl), frame=0.45,
             lit=0.2, seed=3.0, emit=("#ffcf9e", 0.9), color="#3a2c2a", w=(x0 - 0.1, x0 + 0.1)),
        dict(kind="grid", plane="yz", c=(0.0, fl / 2 + 0.3), s=(Wy / 2 - 0.3, 200), pitch=(2.4, fl), frame=0.45,
             lit=0.1, seed=11.0, emit=("#8fa8ff", 1.1), color="#262a3a", w=(x0 - 0.1, x0 + 0.1)),
    ], soft=0.04)
    core = rbox("stack_core", D, Wy, top + 40.0, 1.6, 0.25, M.paint_big, seg=3,
                xform=basis((0, 0, 1), (0, 1, 0), (x0 + D / 2, 0, top - (top + 40.0) / 2)))
    # the facade: a glass curtain wall on the track side
    wall = MB([facade])
    wall.face(wall.verts([(x0 - 0.02, Wy / 2 - 0.2, -40), (x0 - 0.02, -Wy / 2 + 0.2, -40),
                          (x0 - 0.02, -Wy / 2 + 0.2, top - 0.6), (x0 - 0.02, Wy / 2 - 0.2, top - 0.6)]))
    wall = wall.build("stack_wall")
    parts = [core, wall]
    brands = ["#ff2e2e", "#ffcc00", "#1fff8f", "#7b2eff", "#ff7a1f", "#ff8ad8", "#9fd2ff", "#00e1ff"]
    pills, decals = [], []
    k = 0
    zz = 0.3 + fl + 0.85
    while zz < top - 3.0:
        ln = rnd.uniform(7.0, 9.4)
        cy = rnd.uniform(-1.3, 1.3)
        h = 1.7
        depth = rnd.uniform(1.9, 2.5)
        fx = x0 - depth
        pills.append((ln, cy, h, depth, zz))
        # icon tile (a brand colour, glowing) and two grey "text" bars on the pill's face (facing -X)
        yi = cy + ln / 2 - 1.0
        decals.append(dict(kind="rect", plane="yz", c=(yi, zz), s=(0.52, 0.52), r=0.14, color=brands[k % 8],
                           emit=(brands[k % 8], 1.4), rough=0.3, w=(fx - 0.2, fx + 0.05), face=(-1, 0, 0)))
        for bl, bz, shade in ((ln * 0.5, 0.25, "#3a3842"), (ln * 0.32, -0.22, "#6a6772")):
            decals.append(dict(kind="rect", plane="yz", c=(yi - 0.85 - bl / 2, zz + bz), s=(bl / 2, 0.1), r=0.1,
                               color=shade, w=(fx - 0.2, fx + 0.05), face=(-1, 0, 0)))
        decals.append(dict(kind="rect", plane="yz", c=(cy - ln / 2 + 0.9, zz + 0.3), s=(0.35, 0.08), r=0.08,
                           color="#8d8a96", w=(fx - 0.2, fx + 0.05), face=(-1, 0, 0)))
        zz += fl
        k += 1
    pill_mat = decorate(smudged("F_Pill", "#e6e3ec", rough=0.3, amount=0.15, scale=2.0,
                                smudge="SurfaceImperfections003"), decals, soft=0.03)
    for k, (ln, cy, h, depth, zz) in enumerate(pills):
        parts.append(phone(f"pill{k}", ln, h, depth, h / 2 - 0.02, pill_mat, pill_mat, pill_mat, seg=3,
                           prof=[(0.0, 0.0), (0.0, depth - 0.16), (0.16, depth)], cap_back=False,
                           xform=basis((-1, 0, 0), (0, 0, 1), (x0 + 0.05, cy, zz))))
    # roof: 5G mast + aviation light
    mast = lathe("stack_mast", [(0.25, top), (0.12, top + 8.0), (0.0, top + 8.2)], 8, M.paint_big,
                 xform=T(x0 + D / 2, 2.0, 0))
    beacon = lathe("stack_beacon", [(0.0, top + 7.4), (0.3, top + 7.6), (0.0, top + 7.9)], 8, M.red,
                   xform=T(x0 + D / 2, 2.0, 0))
    parts += [mast, beacon]
    o = join(parts, "side_stack")
    loops(o, 1.0)
    finish(o, 38)
    kit.add("side_stack", away_parts(o, "side_stack", 0.22), dict(slot="mid", every=40.0, chance=0.55, side="both"), share=0.1)


def feed_billboard(M, kit):
    """Mid: a portrait phone billboard (ScreenFeed) on a mast, a catwalk and two spotlights on arms."""
    W, H, Tt, r = 7.0, 15.0, 0.7, 1.0
    z0 = 8.0
    xf_ = 1.6  # screen plane
    frame = decorate(metal("F_BoardFrame", scale=1.5, tint="#8f8b99", rough_scale=0.65), [
        *[dict(kind="rect", plane="xz", c=(0, zz), s=(4.0, 0.05), color="#17161c", rough=0.5, metal=0.0,
               face=(0, sy, 0)) for sy in (-1, 1) for zz in (z0 + 2.0, z0 + H - 2.0)],
    ], soft=0.02)
    face = smudged("F_BoardFace", "#030304", rough=0.05, amount=0.3, scale=2.0)
    body = phone("board_body", W, H, Tt, r, frame, face, M.back_big, screen=(W - 0.44, H - 0.6, 0.0, r - 0.2),
                 screen_mat=M.screen, chamfer=M.polish_big, seg=4,
                 prof=[(0.12, 0.0), (0.0, 0.12), (0.0, Tt - 0.1), (0.1, Tt)],
                 xform=basis((-1, 0, 0), (0, 0, 1), (xf_ + Tt, 0, z0 + H / 2)))
    island = rbox("board_island", 1.2, 0.36, 0.05, 0.18, 0.015, M.lens, seg=3,
                  xform=basis((-1, 0, 0), (0, 0, 1), (xf_ - 0.02, 0, z0 + H - 0.75)))
    mx = xf_ + Tt + 1.0
    mast = lathe("board_mast", [(0.6, -44.0), (0.6, z0 + H * 0.75), (0.0, z0 + H * 0.75 + 0.3)], 14, M.paint_big,
                 xform=T(mx, 0, 0))
    yoke = rbox("board_yoke", 1.4, 5.0, 1.0, 0.2, 0.08, M.paint_big, seg=2, xform=T(mx - 0.7, 0, z0 + H * 0.55))
    yoke2 = rbox("board_yoke2", 1.4, 5.0, 1.0, 0.2, 0.08, M.paint_big, seg=2, xform=T(mx - 0.7, 0, z0 + 3.0))
    walk = rbox("board_walk", 2.2, W + 1.2, 0.2, 0.05, 0.02, M.paint_big, seg=1, xform=T(xf_ - 0.4, 0, z0 - 0.4))
    rails = [tube("board_rail", [(xf_ - 1.45, -W / 2 - 0.55, z0 + 0.75), (xf_ - 1.45, W / 2 + 0.55, z0 + 0.75)],
                  0.05, 6, M.paint_big)]
    for yy in (-W / 2 - 0.5, -1.2, 1.2, W / 2 + 0.5):
        rails.append(tube("board_post", [(xf_ - 1.45, yy, z0 - 0.3), (xf_ - 1.45, yy, z0 + 0.75)], 0.04, 5,
                          M.paint_big, caps=False))
    spots = []
    for sy in (-1, 1):
        tip = Vector((xf_ - 2.4, sy * 2.2, z0 + 0.4))
        spots.append(tube("board_arm", [(mx, sy * 2.2, z0 + 0.6), (xf_ - 1.0, sy * 2.2, z0 + 0.3), tuple(tip)],
                          0.09, 6, M.paint_big))
        aim = Vector((0.55, 0.0, 0.84))
        spots.append(lathe("board_spot", [(0.0, -0.3), (0.3, -0.3), (0.36, 0.25), (0.4, 0.3)], 12,
                           [M.paint_big, M.paint_big, M.paint_big], cap_top=M.led,
                           xform=basis(aim, (1, 0, 0), tip + Vector((0, 0, 0.35)))))
    o = join([body, island, mast, yoke, yoke2, walk] + rails + spots, "side_billboard")
    loops(o, 1.0)
    finish(o, 38)
    kit.add("side_billboard", away_parts(o, "side_billboard", 0.35),
            dict(slot="mid", every=46.0, chance=0.5, side="both"), share=0.05)


def feed_lamp(M, kit):
    """Wall: a selfie-stick street lamp: telescoping chrome pole, a ring light leaning over the track
    with a phone in it, a coiled cable and a shutter remote."""
    px = 0.55
    # (radius, z): telescoping sections with dark collars
    prof = [(0.17, -30.0), (0.17, -0.95), (0.195, -0.9), (0.195, -0.75), (0.14, -0.7), (0.14, 2.6), (0.158, 2.64),
            (0.158, 2.8), (0.11, 2.84), (0.11, 5.2), (0.128, 5.24), (0.128, 5.38), (0.085, 5.42), (0.085, 7.3),
            (0.12, 7.34), (0.12, 7.52), (0.0, 7.58)]
    band = []
    for i in range(len(prof) - 1):
        (r0, z0), (r1, z1) = prof[i], prof[i + 1]
        collar = abs(r0 - r1) < 1e-6 and (z1 - z0) < 0.25
        band.append(M.dark if collar or r1 == 0.0 else M.chrome)
    pole = lathe("lamp_pole", prof, 8, band, xform=T(px, 0, 0))
    head_c = Vector((-0.6, 0.0, 7.0))
    arm = tube("lamp_arm", [(px, 0, 7.5), (px - 0.3, 0, 7.72), (head_c.x + 0.45, 0, head_c.z + 0.62)], 0.07, 8,
               M.chrome)
    ball = lathe("lamp_ball", [(0.0, -0.13), (0.1, -0.09), (0.13, 0.0), (0.1, 0.09), (0.0, 0.13)], 10, M.dark,
                 xform=T(px, 0, 7.5))
    # ring light: an annulus facing toward the track and down; profile counter-clockwise in (r, z)
    nrm = Vector((-0.55, 0.0, -0.84)).normalized()
    ringM = basis(nrm, (1, 0, 0.6), head_c)
    rp = [(0.62, 0.02), (0.64, -0.1), (1.0, -0.1), (1.02, 0.02), (0.99, 0.05), (0.65, 0.05), (0.62, 0.02)]
    ring = lathe("lamp_ring", rp, 22, [M.dark, M.dark, M.dark, M.led, M.led, M.led], xform=ringM)
    ph = phone("lamp_phone", 0.5, 1.02, 0.06, 0.08, M.alu, M.glass, M.back, screen=(0.46, 0.96, 0, 0.06),
               screen_mat=M.screen, seg=3, xform=ringM @ T(0, 0, 0.015))
    clamp = rbox("lamp_clamp", 0.64, 0.12, 0.08, 0.04, 0.02, M.dark, seg=2, xform=ringM @ T(0, 0.0, 0.0))
    spoke = rbox("lamp_spoke", 0.08, 1.28, 0.05, 0.02, 0.01, M.dark, seg=1, xform=ringM @ T(0, 0, -0.04))
    coil = []
    for i in range(0, 57):
        t = i / 56
        a = t * TAU * 7
        coil.append((px + 0.21 * math.cos(a), 0.21 * math.sin(a), 6.9 - t * 6.3))
    cable = tube("lamp_cable", coil, 0.024, 3, M.plastic)
    remote = rbox("lamp_remote", 0.16, 0.34, 0.07, 0.05, 0.02, M.dark, seg=2,
                  xform=basis((-1, 0, 0), (0, 0, 1), (px - 0.2, 0, 1.3)))
    rbtn = lathe("lamp_rbtn", [(0.05, 0.0), (0.05, 0.02), (0.0, 0.025)], 10, M.polish,
                 xform=basis((-1, 0, 0), (0, 0, 1), (px - 0.235, 0, 1.36)))
    o = join([pole, arm, ball, ring, ph, clamp, spoke, cable, remote, rbtn], "side_lamp")
    finish(o, 40)
    kit.add("side_lamp", away_parts(o, "side_lamp", 1.4, w_back=0.5, deep=-3.0),
            dict(slot="wall", every=14.0, chance=0.85, side="both"), share=0.06)


def feed_plaza(M, kit):
    """Mid: a wireless-charging-pad plaza: a giant puck with its glowing coil ring, a phone on a
    magnetic stand charging on it, its cable dropping into the void."""
    R0 = 7.0
    cx = R0 + 0.5
    zt = -1.2
    pad_top = decorate(mat.pbr("F_PadTop", "Rubber004", mapping="BOX", box_scale=2.0, tint="#c9c6cf"), [
        dict(kind="ring", plane="xy", c=(cx, 0), s=(4.2, 0.18), color="#8f8c96", depth=-0.03),
        dict(kind="ring", plane="xy", c=(cx, 0), s=(2.1, 0.06), color="#a9a6b0", depth=-0.015),
        dict(kind="circle", plane="xy", c=(cx, 0), s=(0.9, 0), color="#b8b5bf", depth=0.01),
    ], soft=0.05)
    puck = lathe("pad_puck", [(0.0, zt - 1.6), (R0 - 0.6, zt - 1.6), (R0, zt - 1.0), (R0, zt - 0.25),
                              (R0 - 0.25, zt), (0.0, zt)], 40,
                 [M.plastic, M.plastic, M.plastic, M.polish_big, pad_top], xform=T(cx, 0, 0))
    led = lathe("pad_led", [(R0 + 0.02, zt - 0.72), (R0 + 0.02, zt - 0.5)], 40, glow("F_PadLed", "#56e6ff", 3.5),
                xform=T(cx, 0, 0))
    # magnetic stand: a stalk leaning back with a puck holding the phone
    stand_base = lathe("pad_standbase", [(0.0, zt), (1.2, zt), (1.2, zt + 0.25), (0.9, zt + 0.35), (0.0, zt + 0.35)],
                       20, M.alu_big, xform=T(cx + 0.8, 0, 0))
    tilt = math.radians(14)
    up = Vector((math.sin(tilt), 0, math.cos(tilt)))
    top_pt = Vector((cx + 0.8, 0, zt + 0.35)) + up * 2.3
    stalk = tube("pad_stalk", [(cx + 0.8, 0, zt + 0.3), tuple(top_pt)], 0.22, 10, M.alu_big)
    nrm = Vector((-math.cos(tilt), 0, math.sin(tilt)))
    phM = basis(nrm, up, top_pt + up * 3.2 + nrm * 0.32)
    ph = phone("pad_phone", 4.6, 9.6, 0.42, 0.62, M.alu_big, M.glass_big, M.back_big,
               screen=(4.3, 9.25, 0, 0.5), screen_mat=M.screen, chamfer=M.polish_big, seg=4,
               prof=[(0.06, 0.0), (0.0, 0.06), (0.0, 0.36), (0.06, 0.42)], xform=phM)
    mag = lathe("pad_mag", [(0.0, 0.0), (1.0, 0.0), (1.0, 0.3), (0.0, 0.32)], 20, M.alu_big,
                xform=basis(nrm, up, top_pt))
    bollards = []
    for i in range(6):
        a = TAU * (i + 0.5) / 6
        bx, by = cx + (R0 - 1.0) * math.cos(a), (R0 - 1.0) * math.sin(a)
        if bx < cx - 2.0:
            continue
        bollards.append(lathe(f"pad_bollard{i}", [(0.0, zt), (0.22, zt), (0.2, zt + 0.9), (0.0, zt + 0.95)], 8,
                              M.plastic, xform=T(bx, by, 0)))
        bollards.append(lathe(f"pad_bollard_led{i}", [(0.205, zt + 0.72), (0.2, zt + 0.84)], 8,
                              glow("F_PadLed2", "#56e6ff", 3.0), xform=T(bx, by, 0)))
    # the cable: from under the puck, a thick USB-C cable arcing down into the void
    path = [(cx + 1.0 * math.cos(t * 1.4), 0.9 * math.sin(t * 2.0), zt - 1.6 - 2.5 * t * t - t * 1.2)
            for t in [i / 14 for i in range(15)]]
    path += [(cx + 2.0, -1.0, -40.0)]
    cable = tube("pad_cable", path, 0.7, 10, M.plastic)
    boot = lathe("pad_boot", [(0.0, zt - 2.3), (0.95, zt - 2.3), (0.95, zt - 1.55), (0.0, zt - 1.55)], 12, M.plastic,
                 xform=T(cx + 1.0, 0, 0))
    o = join([puck, led, stand_base, stalk, ph, mag, cable, boot] + bollards, "side_plaza")
    loops(o, 1.0)
    finish(o, 38)
    kit.add("side_plaza", away_parts(o, "side_plaza", 0.3), dict(slot="mid", every=80.0, chance=0.45, side="both"), share=0.06)


def feed_antenna(M, kit):
    """Mid: a 5G monopole: sector panels on a triangular head frame, microwave drums, a dish,
    cable ladder and a red aviation light."""
    x = 1.5
    parts = [lathe("ant_pole", [(0.75, -40.0), (0.7, 0.0), (0.42, 26.0), (0.3, 31.0), (0.0, 31.2)], 12, M.paint_big,
                   xform=T(x, 0, 0))]
    for lvl, zz in enumerate((24.0, 19.5)):
        ring = lathe(f"ant_frame{lvl}", [(2.0, zz - 0.12), (2.0, zz + 0.12)], 3, M.paint_big, cap_top=M.paint_big,
                     cap_bottom=M.paint_big, xform=T(x, 0, 0), a0=math.radians(90))
        parts.append(ring)
        for i in range(3):
            a = math.radians(90 + 120 * i + (60 if lvl else 0))
            px, py = x + 2.1 * math.cos(a), 2.1 * math.sin(a)
            panel = rbox(f"ant_panel{lvl}{i}", 0.75, 0.28, 3.0 if lvl == 0 else 2.2, 0.1, 0.05, M.plastic, seg=2,
                         xform=T(px, py, zz) @ R("Z", math.degrees(a) - 90))
            parts.append(panel)
    for i, (a, zz) in enumerate(((200.0, 14.0), (-30.0, 12.0))):
        ar = math.radians(a)
        c = Vector((x + 0.95 * math.cos(ar), 0.95 * math.sin(ar), zz))
        drum = lathe(f"ant_drum{i}", [(0.0, 0.0), (0.6, 0.0), (0.62, 0.35), (0.55, 0.42), (0.0, 0.44)], 14,
                     [M.plastic, M.plastic, M.plastic, M.plastic], xform=basis((math.cos(ar), math.sin(ar), 0),
                                                                               (0, 0, 1), c))
        parts.append(drum)
    dish_c = Vector((x - 1.6, 0.0, 8.0))
    dish = lathe("ant_dish", [(0.0, 0.0), (0.8, 0.12), (1.5, 0.45), (1.55, 0.5), (1.45, 0.52), (0.0, 0.1)], 16,
                 [M.plastic, M.plastic, M.polish_big, M.plastic, M.plastic],
                 xform=basis(Vector((-0.7, 0.0, 0.7)), (0, 0, 1), dish_c))
    feedarm = tube("ant_feedarm", [tuple(dish_c + Vector((-0.1, 0, 0.1))), tuple(dish_c + Vector((-1.0, 0, 1.0)))], 0.04,
                   4, M.paint_big)
    lnb = rbox("ant_lnb", 0.2, 0.2, 0.35, 0.05, 0.02, M.plastic, seg=1,
               xform=T(*(dish_c + Vector((-1.05, 0, 1.05)))))
    platform = lathe("ant_platform", [(0.0, 7.3), (1.9, 7.3), (1.9, 7.5), (0.0, 7.5)], 16, M.paint_big,
                     xform=T(x - 0.6, 0, 0))
    ladder = rbox("ant_ladder", 0.18, 0.5, 70.0, 0.02, 0.01, M.paint_big, seg=1, xform=T(x + 0.72, 0, -5.0))
    beacon = lathe("ant_beacon", [(0.0, 31.1), (0.22, 31.2), (0.18, 31.55), (0.0, 31.6)], 8, M.red, xform=T(x, 0, 0))
    beacon2 = lathe("ant_beacon2", [(0.0, 0.0), (0.16, 0.05), (0.0, 0.3)], 6, M.red, xform=T(x + 0.7, 0, 16.0))
    parts += [dish, feedarm, lnb, platform, ladder, beacon, beacon2]
    o = join(parts, "side_antenna")
    loops(o, 1.0)
    finish(o, 38)
    kit.add("side_antenna", away_parts(o, "side_antenna", 0.35, away=0.7),
            dict(slot="mid", every=70.0, chance=0.45, side="both"), share=0.04)


def catenary(a, b, sag, n):
    a, b = Vector(a), Vector(b)
    return [tuple(a.lerp(b, t) - Vector((0, 0, sag * 4 * t * (1 - t)))) for t in [i / n for i in range(n + 1)]]


def feed_powerline(M, kit):
    """Mid: charging-cable power line: two pylons (giant wall chargers on masts), three white USB
    cables sagging between them, plugged in with USB-C heads, and drooping off into the void."""
    span = 24.0
    x = 2.5
    ys = [float(v) for v in range(-18, 19)]
    parts = []
    tips = {}
    for sy in (-1, 1):
        y = sy * span / 2
        mast = rbox(f"pl_mast{sy}", 0.9, 0.9, 58.0, 0.2, 0.0, M.paint_big, seg=1, xform=T(x, y, -15.0))
        brace = rbox(f"pl_brace{sy}", 7.2, 0.5, 0.5, 0.1, 0.0, M.paint_big, seg=1, xform=T(x, y, 12.5))
        brick = rbox(f"pl_brick{sy}", 2.6, 2.6, 2.8, 0.45, 0.22, M.plastic, seg=2, xform=T(x, y, 15.0))
        prongs = [rbox(f"pl_prong{sy}{i}", 0.12, 0.35, 1.0, 0.03, 0.0, M.polish_big, seg=1,
                       xform=T(x + dx, y, 16.8)) for i, dx in enumerate((-0.45, 0.45))]
        led = rbox(f"pl_led{sy}", 0.4, 0.06, 0.06, 0.02, 0.0, glow("F_PlLed", "#56ff9a", 3.0), seg=1,
                   xform=T(x - 1.31, y, 14.3) @ R("Z", 90))
        parts += [mast, brace, brick, led] + prongs
        for i, dx in enumerate((-3.2, 0.0, 3.2)):
            zt = 12.8 if i != 1 else 13.6
            yh = y - sy * 1.0
            head = rbox(f"pl_head{sy}{i}", 0.55, 1.0, 0.3, 0.12, 0.06, M.polish_big, seg=2,
                        xform=T(x + dx, yh, zt))
            boot = rbox(f"pl_boot{sy}{i}", 0.7, 1.0, 0.42, 0.18, 0.08, M.plastic, seg=2,
                        xform=T(x + dx, yh - sy * 1.0, zt))
            parts += [head, boot]
            tips[(sy, i)] = (x + dx, yh - sy * 1.5, zt)
    for i in range(3):
        (ax, ay, az), (bx, by, bz) = tips[(-1, i)], tips[(1, i)]
        sag = 2.8 + 0.3 * i
        pts = [(ax, ay, az)] + [(ax, yy, az - sag * (1 - ((yy - ay) / (by - ay) * 2 - 1) ** 2))
                                for yy in ys if ay < yy < by] + [(bx, by, bz)]
        parts.append(tube(f"pl_cable{i}", pts, 0.16, 5, M.plastic, caps=False, flat_y=True))
    # droops off the outer ends (where the next span would be), into the void
    for sy in (-1, 1):
        x0, y0, z0 = x - 3.2, sy * (span / 2 + 0.3), 12.4
        pts = [(x0, y0, z0)]
        for yy in ys:
            if abs(y0) < sy * yy <= abs(y0) + 5.0:
                t = (sy * yy - abs(y0)) / 5.0
                pts.append((x0 + 0.3 * t, yy, z0 - 3.0 * t - 10.0 * t * t))
        pts.append((x0 + 0.4, pts[-1][1] + sy * 0.6, -40.0))
        parts.append(tube(f"pl_droop{sy}", pts, 0.16, 5, M.plastic, caps=False))
    o = join(parts, "side_powerline")
    loops(o, positions=ys)
    finish(o, 38)
    kit.add("side_powerline", away_parts(o, "side_powerline", 0.3, away=0.7),
            dict(slot="mid", every=90.0, chance=0.4, side="both"), share=0.03)


# ------------------------------------------------------------------ tunnel

TUN_YS = [-2.2, -2.13, -2.03, -1.624, -1.218, -0.812, -0.406, 0.0, 0.406, 0.812, 1.218, 1.624, 2.03, 2.13, 2.2]


def vault_joints(xw=6.1, zf=-1.8, zs=5.6, zc=10.4, wall=3, vault=4):
    """Inner surface joints of a phone vault, up the right wall, over the crown, down the left wall."""
    right = [(xw, zf + (zs - zf) * i / wall) for i in range(wall + 1)]
    for i in range(1, vault + 1):
        a = (math.pi / 2) * i / vault
        right.append((xw * math.cos(a), zs + (zc - zs) * math.sin(a)))
    left = [(-x, z) for x, z in reversed(right[:-1])]
    return right + left, zs


def phone_vault(name, joints, zs, ys, face_mat, frame_mat, screen_mat, screens, groove=0.08, edge=0.08,
                border=0.1, outward_c=None):
    """Sweep of phones lying lengthwise (along Y) round an arch: each facet between two joints is one
    phone face, V grooves (chamfered frames) at the joints and at the row ends. `screens`: facet
    indices that are live screens (inset by `border`)."""
    oc = outward_c if outward_c is not None else (0.0, zs)
    pts, kinds = [], []
    nf = len(joints) - 1
    for j in range(nf):
        p0, p1 = Vector(joints[j]), Vector(joints[j + 1])
        t = (p1 - p0).normalized()
        L = (p1 - p0).length
        if j == 0:
            pts.append(tuple(p0))
            kinds.append("joint")
        seq = [p0 + t * edge]
        kk = ["edge"]
        if j in screens:
            seq += [p0 + t * (edge + border), p1 - t * (edge + border)]
            kk += ["scr0", "scr1"]
        seq.append(p1 - t * edge)
        kk.append("edge")
        pts += [tuple(q) for q in seq] + [tuple(p1)]
        kinds += kk + ["joint"]

    def outward(x, z):
        if z <= zs:
            return Vector((1.0 if x > 0 else -1.0, 0.0))
        return Vector((x - oc[0], z - oc[1])).normalized()

    def prof(y):
        end = abs(y) > 2.14
        out = []
        for (x, z), kd in zip(pts, kinds):
            push = (groove if kd == "joint" else 0.0) + (groove * 0.9 if end else 0.0)
            d = outward(x, z)
            out.append((x + d.x * push, z + d.y * push))
        return out
    nr = len(ys)

    def mfn(j, k):
        a, b = kinds[j], kinds[j + 1]
        if a == "joint" or b == "joint" or k == 0 or k == nr - 2:
            return 1
        if k == 1 or k == nr - 3:
            return 0
        if a == "scr0" and b == "scr1":
            return 2
        return 0
    o = sweep(name, prof, ys, mfn, [face_mat, frame_mat, screen_mat])
    return o, prof, pts


def feed_tunnel(M, kit):
    """The feed curls up over you: a vault of giant phones lying lengthwise, faces in, some screens live."""
    joints, zs = vault_joints()
    nf = len(joints) - 1
    screens = {1, 4, nf - 5, nf - 2}
    facet_decals = []
    for j in range(nf):
        p0, p1 = Vector(joints[j]), Vector(joints[j + 1])
        c = (p0 + p1) / 2
        t = (p1 - p0).normalized()
        fr = ((c.x, 0.0, c.y), (t.x, 0.0, t.y), (0.0, 1.0, 0.0))
        for sy in (1,):
            facet_decals += [
                dict(kind="rect", axes=fr, c=(0.0, sy * 2.085), s=(0.22, 0.012), r=0.012, color="#17161c",
                     rough=0.6, depth=-0.004, w=(-0.15, 0.15)),
                dict(kind="dots", axes=fr, c=(0.0, sy * 2.085), s=(0.21, 0.008), pitch=0.012, hole=0.004,
                     color="#050506", w=(-0.15, 0.15)),
                dict(kind="circle", axes=fr, c=(0.4, sy * 2.085), s=(0.026, 0), color="#0b0d1a", rough=0.02,
                     w=(-0.15, 0.15)),
                dict(kind="ring", axes=fr, c=(0.4, sy * 2.085), s=(0.032, 0.004), color="#2b2a36", metal=1.0,
                     rough=0.2, w=(-0.15, 0.15)),
            ]
    tface = decorate(smudged("F_TunFace", "#040406", rough=0.06, amount=0.2, scale=2.0), facet_decals, soft=0.005)
    tframe = decorate(metal("F_TunFrame", scale=0.8, tint="#8f8b99", rough_scale=0.6), [
        # a notification-LED line in the crown groove
        dict(kind="rect", plane="xz", c=(0.0, 10.5), s=(0.035, 0.3), emit=("#b48cff", 3.0), color="#1a1030"),
    ], soft=0.01)
    inner, prof, pts = phone_vault("tun_inner", joints, zs, TUN_YS, tface, tframe, M.screen, screens)
    fit_screens(inner, "ScreenFeed", rotate=1)
    # outer shell over the joints (0.6 m out), its bottom, the floor under the deck, portal end caps
    th = 0.6
    outer = []
    for x, z in joints:
        d = Vector((1.0 if x > 0 else -1.0, 0.0)) if z <= zs else Vector((x, z - zs)).normalized()
        outer.append((x + d.x * th, z + d.y * th))
    outer[0] = (outer[0][0], joints[0][1] - th)
    outer[-1] = (outer[-1][0], joints[-1][1] - th)
    outer_rev = list(reversed(outer))  # normals out: up the left, over, down the right
    shell_m = smudged("F_TunShell", "#15131b", rough=0.4, amount=0.2, scale=6.0, smudge="SurfaceImperfections003")
    shell = sweep("tun_shell", lambda y: outer_rev + [outer_rev[0]][:0], TUN_YS, lambda j, k: 0, [shell_m])
    base = sweep("tun_base", lambda y: [outer[0], outer[-1]], TUN_YS, lambda j, k: 0, [shell_m])  # facing down
    floor = sweep("tun_floor", lambda y: [joints[-1], joints[0]], TUN_YS, lambda j, k: 0, [M.dark])
    caps = []
    for sy in (-1, 1):
        b = MB([M.alu_big])
        y = sy * 2.2
        ip = prof(y)
        # one polygon per facet between the inner points of that facet and the two outer joints
        ji = [i for i, _ in enumerate(pts) if i == 0 or i == len(pts) - 1 or
              any((abs(pts[i][0] - jx) < 1e-6 and abs(pts[i][1] - jz) < 1e-6) for jx, jz in joints)]
        for f in range(len(ji) - 1):
            a, c = ji[f], ji[f + 1]
            poly = [(ip[i][0], y, ip[i][1]) for i in range(a, c + 1)]
            poly += [(outer[f + 1][0], y, outer[f + 1][1]), (outer[f][0], y, outer[f][1])]
            idx = b.verts(poly)
            b.face(idx if sy > 0 else list(reversed(idx)), 0)
        # floor strip between the inner floor corners and the outer base
        idx = b.verts([(joints[0][0], y, joints[0][1]), (joints[-1][0], y, joints[-1][1]),
                       (outer[-1][0], y, outer[-1][1]), (outer[0][0], y, outer[0][1])])
        b.face(idx if sy < 0 else list(reversed(idx)), 0)
        caps.append(b.build(f"tun_cap{sy}"))
    o = join([inner, shell, base, floor] + caps, "tunnel")
    mesh.clean(o, recalc_normals=False)
    loops(o, positions=TUN_YS[1:-1])
    finish(o, 30)
    parts = [o]
    back = split_faces(o, lambda c, n, m: m in ("F_TunShell", "F_Dark") or (m == "F_AluBig"), "tunnel_out")
    weight(o, 1.1)
    if back is not None:
        weight(back, 0.05)
        parts.append(back)
    kit.add("tunnel", parts, share=0.13)


def fit_screens(o, name, rotate=0):
    """uv_fit_faces per connected island of faces on material `name` (one 0..1 per screen)."""
    import bmesh
    me = o.data
    idx = next((i for i, m in enumerate(me.materials) if m and m.name == name), None)
    if idx is None:
        return
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    faces = [f for f in bm.faces if f.material_index == idx]
    seen, islands = set(), []
    for f in faces:
        if f.index in seen:
            continue
        stack, isl = [f], []
        seen.add(f.index)
        while stack:
            c = stack.pop()
            isl.append(c.index)
            for e in c.edges:
                for nf in e.link_faces:
                    if nf.material_index == idx and nf.index not in seen:
                        seen.add(nf.index)
                        stack.append(nf)
        islands.append(set(isl))
    bm.free()
    for isl in islands:
        mesh.uv_fit_faces(o, faces=lambda p, isl=isl: p.index in isl, rotate=rotate)


# ------------------------------------------------------------------ overhang

def feed_overhang(M, kit):
    """A giant phone fallen across all three lanes, standing on its long edge on two heaps of dropped
    phones. AdFace on both faces, letterboxed (the ad is 2:1, the phone is not), a cracked corner."""
    L, Hh, Tt, r = 8.5, 2.3, 0.34, 0.42
    zb = 0.97
    lean = 5.0
    frame = decorate(metal("F_OhFrame", scale=0.5, tint="#8f8b99", rough_scale=0.6), [
        *[dict(kind="rect", plane="xz", c=(xx, 0), s=(0.015, 10), color="#17161c", rough=0.5, metal=0.0)
          for xx in (-3.4, 3.4)],
    ], soft=0.006)
    glass = decorate(smudged("F_OhGlass", "#030304", rough=0.05, amount=0.35, scale=0.9), [
        # a cracked corner in the right letterbox bar of the front (final object space)
        dict(kind="lines", plane="xz", c=(3.55, 2.75), s=(0.5, 0.45), pitch=0.07, width=0.006, axis="u",
             color="#a5a2b3", rough=0.2, noise=(8.0, 0.5), face=(0, -1, 0)),
        dict(kind="lines", plane="xz", c=(3.55, 2.75), s=(0.5, 0.45), pitch=0.11, width=0.005, axis="v",
             color="#9895a6", rough=0.2, noise=(6.0, 0.52), face=(0, -1, 0)),
    ], soft=0.004)
    sw, sh = L - 0.36, Hh - 0.26
    halves = []
    for sgn in (1, -1):
        h = phone(f"oh_half{sgn:+d}", L, Hh, Tt / 2, r, frame, glass, glass, screen=(sw, sh, 0, r - 0.12),
                  screen_mat=M.off, chamfer=M.polish, seg=5,
                  prof=[(0.0, 0.0), (0.0, Tt / 2 - 0.04), (0.04, Tt / 2)], cap_back=False)
        if sgn < 0:
            xf(h, R("Y", 180))
        halves.append(h)
    island = rbox("oh_island", 0.62, 0.17, 0.02, 0.085, 0.005, M.lens, seg=3,
                  xform=T(-L / 2 + 0.5, 0, Tt / 2 + 0.01) @ R("Z", 90))
    bump = rbox("oh_bump", 0.95, 0.95, 0.06, 0.24, 0.02, M.back, seg=3, xform=T(L / 2 - 0.8, 0.5, -Tt / 2 - 0.03))
    lens = [xf(p, T(L / 2 - 0.8, 0.5, -Tt / 2 - 0.06) @ R("X", 180)) for p in lens_cluster(M, 0, 0, 0, 1.2, "oh_lens")]
    btns = [rbox("oh_btn", ln, 0.06, 0.1, 0.028, 0.01, M.polish, seg=2, xform=T(xx, Hh / 2 + 0.015, 0) @ R("X", 90))
            for xx, ln in ((-2.3, 0.5), (-1.65, 0.5), (1.9, 0.8))]
    ads = []
    for sgn in (1, -1):
        b = MB([M.ad])
        aw, ah = sh * 2.0, sh
        zz = sgn * (Tt / 2 + 0.012)
        q = [(-aw / 2, -ah / 2, zz), (aw / 2, -ah / 2, zz), (aw / 2, ah / 2, zz), (-aw / 2, ah / 2, zz)]
        if sgn < 0:
            q = [(-x, y, z) for x, y, z in q]
        b.face(b.verts(q))
        a = b.build(f"oh_ad{sgn:+d}")
        mesh.uv_fit_faces(a, material="AdFace")
        ads.append(a)
    ph = join(halves + [island, bump] + lens + btns + ads, "oh_phone")
    # local: x along the lanes, y up the phone, z out of the front -> world: front toward -Y (the runner)
    xf(ph, T(0, 0, zb) @ R("X", -lean) @ basis((0, -1, 0), (0, 0, 1), (0, 0, Hh / 2)))
    import random
    rnd = random.Random(3)
    heap = []
    for sx in (-1, 1):
        z = 0.0
        for i in range(3):
            th = 0.3
            hp = phone(f"oh_heap{sx}{i}", 1.1, 2.3, th, 0.16, M.alu, M.glass, M.back,
                       screen=(1.0, 2.18, 0, 0.1), screen_mat=M.off, chamfer=M.polish, seg=3,
                       prof=[(0.02, 0.0), (0.0, 0.02), (0.0, th - 0.03), (0.03, th)],
                       xform=T(sx * (4.25 + rnd.uniform(-0.08, 0.08)), rnd.uniform(-0.12, 0.12), z)
                       @ R("Z", rnd.uniform(-22, 22)))
            heap.append(hp)
            z += th + 0.005
    o = join([ph] + heap, "overhang")
    finish(o, 35)
    weight(o, 2.2)
    kit.add("overhang", o, share=0.10)


# ------------------------------------------------------------------ sky

def feed_sky(out_jpg, preview_dir=None):
    """Night skyline of distant phone towers (lit screens as windows), haze, stars and a DND crescent."""
    import random
    rnd = random.Random(11)
    fog = mat.rgb(FOG)
    col = lib.collection("_sky")
    made = []
    world, nt = world_nodes("_feed_sky")
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Generated"], sep.inputs[0])
    # sky gradient by elevation z: fog colour below the horizon, violet glow at it, near black above
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    cr = ramp.color_ramp
    stops = [(0.0, FOG), (0.5, FOG), (0.502, "#2a1745"), (0.52, "#1a0e30"), (0.58, "#0d0719"), (1.0, "#030208")]
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
    # stars: voronoi points above the horizon
    vor = nt.nodes.new("ShaderNodeTexVoronoi")
    vor.feature = "F1"
    vor.inputs["Scale"].default_value = 70.0
    nt.links.new(tc.outputs["Generated"], vor.inputs["Vector"])
    st = nt.nodes.new("ShaderNodeMapRange")
    st.inputs["From Min"].default_value = 0.0
    st.inputs["From Max"].default_value = 0.22
    st.inputs["To Min"].default_value = 1.0
    st.inputs["To Max"].default_value = 0.0
    nt.links.new(vor.outputs["Distance"], st.inputs["Value"])
    pw = nt.nodes.new("ShaderNodeMath")
    pw.operation = "POWER"
    nt.links.new(st.outputs["Result"], pw.inputs[0])
    pw.inputs[1].default_value = 6.0
    # only some cells lit, brighter higher up
    bright = nt.nodes.new("ShaderNodeMath")
    bright.operation = "GREATER_THAN"
    nt.links.new(vor.outputs["Color"], bright.inputs[0])  # colour -> float (avg)
    bright.inputs[1].default_value = 0.6
    hz = nt.nodes.new("ShaderNodeMapRange")
    hz.inputs["From Min"].default_value = 0.08
    hz.inputs["From Max"].default_value = 0.5
    nt.links.new(sep.outputs["Z"], hz.inputs["Value"])
    m1 = nt.nodes.new("ShaderNodeMath")
    m1.operation = "MULTIPLY"
    nt.links.new(pw.outputs[0], m1.inputs[0])
    nt.links.new(bright.outputs[0], m1.inputs[1])
    m2 = nt.nodes.new("ShaderNodeMath")
    m2.operation = "MULTIPLY"
    nt.links.new(m1.outputs[0], m2.inputs[0])
    nt.links.new(hz.outputs["Result"], m2.inputs[1])
    m3 = nt.nodes.new("ShaderNodeMath")
    m3.operation = "MULTIPLY"
    nt.links.new(m2.outputs[0], m3.inputs[0])
    m3.inputs[1].default_value = 0.9
    add = nt.nodes.new("ShaderNodeMix")
    add.data_type = "RGBA"
    add.blend_type = "ADD"
    nt.links.new(m3.outputs[0], add.inputs[0])
    nt.links.new(ramp.outputs["Color"], add.inputs[6])
    add.inputs[7].default_value = (0.75, 0.72, 1.0, 1.0)
    # the Do Not Disturb crescent: disc minus an offset disc, in direction space
    moon_dir = Vector((math.sin(math.radians(-38)) * math.cos(math.radians(19)),
                       math.cos(math.radians(-38)) * math.cos(math.radians(19)), math.sin(math.radians(19))))
    cut_dir = (moon_dir + Vector((0.035, -0.02, 0.03))).normalized()

    def disc(direction, radius):
        dp = nt.nodes.new("ShaderNodeVectorMath")
        dp.operation = "DOT_PRODUCT"
        nt.links.new(tc.outputs["Generated"], dp.inputs[0])
        dp.inputs[1].default_value = tuple(direction)
        r = nt.nodes.new("ShaderNodeMapRange")
        r.inputs["From Min"].default_value = math.cos(radius) - 0.00006
        r.inputs["From Max"].default_value = math.cos(radius) + 0.00006
        nt.links.new(dp.outputs["Value"], r.inputs["Value"])
        return r.outputs["Result"]
    d1 = disc(moon_dir, math.radians(3.2))
    d2 = disc(cut_dir, math.radians(3.0))
    crescent = nt.nodes.new("ShaderNodeMath")
    crescent.operation = "SUBTRACT"
    crescent.use_clamp = True
    nt.links.new(d1, crescent.inputs[0])
    nt.links.new(d2, crescent.inputs[1])
    glowm = nt.nodes.new("ShaderNodeMix")
    glowm.data_type = "RGBA"
    glowm.blend_type = "MIX"
    nt.links.new(crescent.outputs[0], glowm.inputs[0])
    nt.links.new(add.outputs[2], glowm.inputs[6])
    glowm.inputs[7].default_value = mat.rgba("#d9d2ff")
    bg = nt.nodes.new("ShaderNodeBackground")
    nt.links.new(glowm.outputs[2], bg.inputs["Color"])
    out = nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(bg.outputs[0], out.inputs["Surface"])

    haze_c = "#1b1030"

    def dist_mix(t, a_sock, far_col, near=150.0, far=3200.0, power=0.8):
        """Aerial perspective: mix a colour socket toward far_col with camera distance."""
        cam = t.nodes.new("ShaderNodeCameraData")
        mr = t.nodes.new("ShaderNodeMapRange")
        mr.inputs["From Min"].default_value = near
        mr.inputs["From Max"].default_value = far
        t.links.new(cam.outputs["View Distance"], mr.inputs["Value"])
        pw = t.nodes.new("ShaderNodeMath")
        pw.operation = "POWER"
        t.links.new(mr.outputs["Result"], pw.inputs[0])
        pw.inputs[1].default_value = power
        mx_ = t.nodes.new("ShaderNodeMix")
        mx_.data_type = "RGBA"
        t.links.new(pw.outputs[0], mx_.inputs[0])
        if isinstance(a_sock, bpy.types.NodeSocket):
            t.links.new(a_sock, mx_.inputs[6])
        else:
            mx_.inputs[6].default_value = mat.rgba(a_sock)
        mx_.inputs[7].default_value = mat.rgba(far_col)
        return mx_.outputs[2]

    def screen_mat(name):
        """A phone tower's screen: an Instagram-style grid of posts (cells in object space, 3 per row),
        each a random hue and brightness, dim; hazed with distance."""
        m = mat.new_material(name)
        t = m.node_tree
        t.nodes.clear()
        o = t.nodes.new("ShaderNodeOutputMaterial")
        g = G.__new__(G)
        g.m, g.nt, g._xyz, g._n = m, t, None, None
        x, y, _ = g.xyz()
        info = t.nodes.new("ShaderNodeObjectInfo")
        attr = t.nodes.new("ShaderNodeAttribute")
        attr.attribute_type = "OBJECT"
        attr.attribute_name = "cell"
        cellw = attr.outputs["Fac"]
        fu = g.math("DIVIDE", x, cellw)
        fv = g.math("DIVIDE", y, cellw)
        iu, iv = g.math("FLOOR", fu), g.math("FLOOR", fv)
        du = g.abs(g.sub(g.math("FRACT", fu), 0.5))
        dv = g.abs(g.sub(g.math("FRACT", fv), 0.5))
        inner = g.mul(g.math("LESS_THAN", du, 0.44), g.math("LESS_THAN", dv, 0.44))
        seed = g.mul(info.outputs["Random"], 97.0)
        h1 = g.hash2(iu, g.add(iv, seed))
        h2 = g.hash2(g.add(iu, 31.0), g.add(iv, g.add(seed, 7.0)))
        ramp = t.nodes.new("ShaderNodeValToRGB")
        cr = ramp.color_ramp
        pal = ["#7b4bff", "#ff4f9a", "#46c9ff", "#ffb35c", "#b388ff", "#ff6b6b", "#2effa0", "#ffffff"]
        while len(cr.elements) < len(pal):
            cr.elements.new(0.5)
        for i, c in enumerate(pal):
            cr.elements[i].position = i / len(pal)
            cr.elements[i].color = mat.rgba(c)
        cr.interpolation = "CONSTANT"
        g.link(h1, ramp.inputs["Fac"])
        bright = g.mul(g.mad(g.math("POWER", h2, 3.0), 0.7, 0.07), inner)
        ramp2 = t.nodes.new("ShaderNodeValToRGB")  # the tower's dominant hue
        ramp2.color_ramp.interpolation = "CONSTANT"
        c2 = ramp2.color_ramp
        while len(c2.elements) < len(pal):
            c2.elements.new(0.5)
        for i, c in enumerate(pal):
            c2.elements[i].position = i / len(pal)
            c2.elements[i].color = mat.rgba(c)
        g.link(info.outputs["Random"], ramp2.inputs["Fac"])
        hue = g.lerpc(0.6, ramp.outputs["Color"], ramp2.outputs["Color"])
        col = g.node("ShaderNodeVectorMath", operation="SCALE")
        g.link(hue, col.inputs[0])
        g.link(g.mul(bright, 0.55), col.inputs["Scale"])
        base = g.node("ShaderNodeMix", data_type="RGBA", blend_type="ADD")
        base.inputs[0].default_value = 1.0
        g.link(col.outputs[0], base.inputs[6])
        base.inputs[7].default_value = mat.rgba("#0b0716")
        em = t.nodes.new("ShaderNodeEmission")
        t.links.new(dist_mix(t, base.outputs[2], haze_c), em.inputs["Color"])
        t.links.new(em.outputs[0], o.inputs["Surface"])
        return m

    def body_mat(name, col="#050309"):
        m = mat.new_material(name)
        t = m.node_tree
        t.nodes.clear()
        o = t.nodes.new("ShaderNodeOutputMaterial")
        em = t.nodes.new("ShaderNodeEmission")
        t.links.new(dist_mix(t, col, haze_c, near=100.0, power=0.7), em.inputs["Color"])
        t.links.new(em.outputs[0], o.inputs["Surface"])
        return m

    scr_m = screen_mat("_sky_screen")
    off_m = body_mat("_sky_off", "#0c0a14")
    body_m = body_mat("_sky_body")
    red_m = emission_material("_sky_red", "#ff2a3a", 8.0)

    def put(ob):
        for cl in ob.users_collection:
            cl.objects.unlink(ob)
        col.objects.link(ob)
        made.append(ob)
        return ob

    def tower(i, az, dist, h, w, bright=1.0, landmark=False):
        c = Vector((math.sin(az) * dist, math.cos(az) * dist, 0.0))
        face = -c.normalized()
        face.rotate(Matrix.Rotation(rnd.uniform(-0.6, 0.6), 3, "Z"))
        th = w * 0.11
        Mb = basis(face, (0, 0, 1), c + Vector((0, 0, h / 2 - 150)))
        ob = put(rbox(f"_skyt{i}", w, h + 300, th, w * 0.13, 0.0, body_m, seg=3))
        ob.matrix_world = Mb
        on = landmark or rnd.random() < 0.72
        sw, sh = w * 0.9, h * 0.93
        sc_ = put(rbox(f"_skys{i}", sw, sh, th * 0.1, w * 0.1, 0.0, scr_m if on else off_m, seg=3))
        sc_.matrix_world = basis(face, (0, 0, 1), c + face * (th / 2 + 0.05) + Vector((0, 0, h - sh / 2 - h * 0.035)))
        sc_["cell"] = sw / rnd.choice((3.0, 4.0, 5.0, 5.0, 6.0))
        if landmark or rnd.random() < 0.4:
            b = put(lathe(f"_skyb{i}", [(0.0, 0.0), (max(1.5, h * 0.012), 0.0), (0.0, max(1.5, h * 0.012))], 6,
                          red_m))
            b.matrix_world = T(c.x, c.y, h + 1.0)
        if landmark:
            sp = put(lathe(f"_skysp{i}", [(w * 0.05, 0.0), (w * 0.01, h * 0.25), (0.0, h * 0.26)], 6, body_m))
            sp.matrix_world = T(c.x + face.x * -th * 0.5, c.y + face.y * -th * 0.5, h)
            b2 = put(lathe(f"_skyb2{i}", [(0.0, 0.0), (2.5, 0.0), (0.0, 2.5)], 6, red_m))
            b2.matrix_world = T(c.x + face.x * -th * 0.5, c.y + face.y * -th * 0.5, h * 1.26 + 1)

    i = 0
    for n, (d0, d1), (h0, h1) in ((110, (320, 700), (40, 130)), (220, (700, 1600), (60, 230)),
                                (240, (1600, 3200), (90, 330))):
        for _ in range(n):
            az = rnd.uniform(0, TAU)
            dist = rnd.uniform(d0, d1)
            h = min(rnd.uniform(h0, h1) * (1.7 if rnd.random() < 0.15 else 1.0), dist * 0.26)
            w = h * rnd.uniform(0.3, 0.55)
            tower(i, az, dist, h, w)
            i += 1
    for az_deg, dist, h in ((9, 2300, 860), (-19, 1600, 560), (31, 2600, 980), (165, 1900, 700), (-140, 2400, 820),
                            (80, 2200, 640), (-80, 2500, 760)):
        tower(i, math.radians(az_deg), dist, h, h * 0.36, landmark=True)
        i += 1
    # the abyss: a fog-coloured floor just below the horizon hides every base
    floor_m = emission_material("_sky_floor", FOG, 1.0)
    put(lathe("_sky_floor", [(0.0, -14.0), (9000.0, -14.0)], 64, floor_m))
    # light pollution: glowing haze shells over the horizon, fading upward
    haze = mat.new_material("_sky_haze")
    t = haze.node_tree
    t.nodes.clear()
    o_ = t.nodes.new("ShaderNodeOutputMaterial")
    tcs = t.nodes.new("ShaderNodeTexCoord")
    sp = t.nodes.new("ShaderNodeSeparateXYZ")
    t.links.new(tcs.outputs["Object"], sp.inputs[0])
    fr = t.nodes.new("ShaderNodeMapRange")
    fr.inputs["From Min"].default_value = -14.0
    fr.inputs["From Max"].default_value = 180.0
    fr.inputs["To Min"].default_value = 0.4
    fr.inputs["To Max"].default_value = 0.0
    t.links.new(sp.outputs["Z"], fr.inputs["Value"])
    tr = t.nodes.new("ShaderNodeBsdfTransparent")
    em = t.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = mat.rgba("#4a2270")
    em.inputs["Strength"].default_value = 0.9
    addsh = t.nodes.new("ShaderNodeAddShader")
    t.links.new(tr.outputs[0], addsh.inputs[0])
    mixem = t.nodes.new("ShaderNodeMixShader")
    t.links.new(fr.outputs["Result"], mixem.inputs[0])
    t.links.new(tr.outputs[0], mixem.inputs[1])
    t.links.new(em.outputs[0], mixem.inputs[2])
    t.links.new(mixem.outputs[0], o_.inputs["Surface"])
    for rad in (500.0, 1200.0, 2600.0):
        put(lathe(f"_skyhaze{rad:.0f}", [(rad, -14.0), (rad, 400.0)], 96, haze))
    cam = pano_camera(4.0)
    made.append(cam)
    render_sky(out_jpg, cam, world, samples=64, only=made)
    if preview_dir:
        import shutil
        shutil.copy(out_jpg, os.path.join(preview_dir, "sky.jpg"))
    for o in made:
        bpy.data.objects.remove(o, do_unlink=True)
    return out_jpg


# =================================================================== main

def game_shots(prev, nodes, extras, sky_path, look, tag=""):
    game_view(os.path.join(prev, f"game{tag}.png"), nodes, extras, sky_path, look, overhang_at=34.0)
    game_view(os.path.join(prev, f"game{tag}_tunnel.png"), nodes, extras, sky_path, look, tunnel=(-20.0, 120.0),
              cam_y=40.0, overhang_at=None)


def main():
    size = lib.arg("size", 2048, int)
    prev = lib.arg("preview")
    only = lib.arg("only")
    only = set(only.split(",")) if only else None
    sky_path = os.path.join(KITS_OUT, "feed-sky.jpg")
    cache = os.path.join(lib.TOOLS, "cache", "kits", "feed_baked.blend")
    extras_path = os.path.join(lib.TOOLS, "cache", "kits", "feed_extras.json")
    lib.reset_scene()
    if prev:
        os.makedirs(prev, exist_ok=True)
    if lib.flag("sky-only"):
        feed_sky(sky_path, prev)
        if not lib.flag("game"):
            return
    if lib.flag("sky-only") or lib.flag("game-only"):
        import json
        nodes = load_nodes(cache)
        extras = json.load(open(extras_path))
        game_shots(prev, nodes, extras, sky_path, LOOK)
        return
    M = FeedMats()
    kit = Kit("feed")
    builders = [("deck", feed_deck), ("side_lamp", feed_lamp), ("side_tower", feed_tower), ("side_fold", feed_fold),
                ("side_stack", feed_stack), ("side_billboard", feed_billboard), ("side_plaza", feed_plaza),
                ("side_antenna", feed_antenna), ("side_powerline", feed_powerline), ("tunnel", feed_tunnel),
                ("overhang", feed_overhang)]
    for name, fn in builders:
        if only is None or name in only:
            fn(M, kit)
    kit.report()
    if prev and lib.flag("src"):
        src = os.path.join(prev, "src")
        for n, ps in list(kit.parts.items()):
            scenery = n.startswith("side_")
            preview_piece(src, n, ps, SCENERY_VIEWS if scenery else PIECE_VIEWS, zmin=-4.0 if scenery else None)
    if lib.flag("no-bake"):
        return
    tex_dir = os.path.join(lib.TOOLS, "cache", "kits", "feed")
    res, nodes = bake_kit(kit, size, tex_dir, "FeedKit")
    out = os.path.join(KITS_OUT, "feed.glb") if only is None else os.path.join(lib.TOOLS, "cache", "kits",
                                                                                 "feed_partial.glb")
    export_kit(nodes, out, size)
    extras = {n: kit.extras[n] for n in kit.extras if n.startswith("side_")}
    if only is None:
        import json
        cache_nodes(nodes, cache)
        json.dump(extras, open(extras_path, "w"), indent=1)
    if prev:
        for n, o in nodes.items():
            if n == "deck_seam":
                continue
            scenery = n.startswith("side_")
            preview_piece(prev, n, [o], SCENERY_VIEWS if scenery else PIECE_VIEWS, zmin=-4.0 if scenery else None)
    if not lib.flag("no-sky") and (only is None or lib.flag("sky")):
        feed_sky(sky_path, prev)
    if prev and not lib.flag("no-game") and os.path.exists(sky_path):
        game_shots(prev, nodes, extras, sky_path, LOOK)


if __name__ == "__main__":
    main()
