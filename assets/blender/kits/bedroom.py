# 3 AM Bedroom (biome 3): you are tiny in a giant dark bedroom at 3 AM, lit by
# your phone's cold blue light and one warm bedside lamp. The lanes lie in a
# quilted duvet with glowing charger-cable piping; beside the track: duvet
# dunes, a pillow hill, sock piles, SlopCola cans, the alarm clock at 3:12, a
# charging brick and its tangle, a stack of unread books, and far off the
# nightstand with the lamp (the sun) and a glass of water nobody drank. One
# scale throughout (40x: a 60 cm bed puts the floor at z -24, where the
# contract's scenery ends). Contract: docs/assets-v2.md ("Biome kits").
#
#   blender -b -P assets/blender/kits/bedroom.py -- [--preview <dir>] [--fast] [--no-sky] [--sky-only]
#                                                   [--only side_clock,deck] [--tex <dir>] [--size 2048]
#
# Writes public/assets/kits/bedroom.glb and bedroom-sky.jpg. --fast skips the
# sky, the bake and the export and previews the procedural source materials.
# Baked textures go to --tex (default tools/cache/kits/bedroom, gitignored).
# The helper section is shared in shape with kits/canyon.py.

import math
import os
import sys

sys.dont_write_bytecode = True  # no __pycache__ in the repo
_d = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _d if os.path.isdir(os.path.join(_d, "lib")) else os.path.dirname(_d))

import bmesh  # noqa: E402
import bpy  # noqa: E402
from mathutils import Matrix, Vector, noise  # noqa: E402

import lib  # noqa: E402
from lib import bake, export, log, mat, mesh, preview  # noqa: E402


BIOME = "bedroom"
OUT = lib.arg("out", os.path.join(lib.PUBLIC, "kits", f"{BIOME}.glb"))
SKY_OUT = os.path.join(os.path.dirname(os.path.abspath(OUT)), f"{BIOME}-sky.jpg")
PREVIEW = lib.arg("preview")
SIZE = lib.arg("size", 2048, int)
FAST = lib.flag("fast")
NO_SKY = lib.flag("no-sky") or FAST
SKY_ONLY = lib.flag("sky-only")
ONLY = [s for s in (lib.arg("only") or "").split(",") if s]
TEX_DIR = lib.arg("tex", os.path.join(lib.TOOLS, "cache", "kits", BIOME))
LOW_W = lib.arg("low-w", 0.12, float)   # texel weight of the hidden parts below -6 m
MARGIN = lib.arg("margin", 8, int)   # atlas island margin (px)
UV_ANGLE = lib.arg("uv-angle", 80.0, float)   # our own smart-UV angle (fewer, larger islands than the lib's 66)
SKY_SAMPLES = lib.arg("sky-samples", 160, int)

# The look proposed for src/config/content.json zones[3].look (the game view uses it).
LOOK = dict(fog="#010209", near=30, far=140, sun="#a3adde", sunI=0.9, hemi=0.8, hemi_sky="#6f7dff",
            hemi_ground="#150a24", exposure=1.0, env=0.6)

# ---------------------------------------------------------------- track constants (contract)
LANES = (-2.2, 0.0, 2.2)
SCR_HW, SCR_HL = 0.96, 2.03       # half size of a lane screen (1.92 x 4.06)
ROW = 4.4                          # one deck row along Y
SEAMS = (-3.3, -1.1, 1.1, 3.3)
BELOW = -24.0                      # scenery reaches down to here (here: the floor)
TAU = math.tau


# ================================================================ helpers (shared shape with canyon.py)

def clamp(v, a=0.0, b=1.0):
    return a if v < a else b if v > b else v


def lerp(a, b, t):
    return a + (b - a) * t


def smoothstep(a, b, v):
    t = clamp((v - a) / (b - a)) if b != a else (1.0 if v >= b else 0.0)
    return t * t * (3 - 2 * t)


def fbm(p, octaves=4, lac=2.0, gain=0.5):
    """Perlin fBm, roughly -1..1."""
    s, a, f, norm = 0.0, 1.0, 1.0, 0.0
    for _ in range(octaves):
        s += a * noise.noise(p * f)
        norm += a
        a *= gain
        f *= lac
    return s / norm * 1.6


def pnoise(x, y, z=0.0, scale=1.0, octaves=3, seed=0.0):
    """Noise periodic in y with the deck/tunnel row period (rows tile seamlessly)."""
    a = TAU * y / ROW
    r = ROW / TAU
    return fbm(Vector((x * scale + seed, r * math.cos(a) * scale, r * math.sin(a) * scale + z * scale + seed * 0.37)),
               octaves)


def origin_to(o, point):
    """Put the object origin at `point` (object space) and the object at the world origin:
    the renderer only reads each node's geometry relative to its origin."""
    o.data.transform(Matrix.Translation(-Vector(point)))
    o.location = (0.0, 0.0, 0.0)
    o.rotation_euler = (0.0, 0.0, 0.0)
    o.scale = (1.0, 1.0, 1.0)
    o.data.update()
    return o


def bm_obj(name, bm):
    return mesh.new_object(name, bm)


def quad_strip(bm, ring_a, ring_b, closed=True):
    n = len(ring_a)
    for k in range(n if closed else n - 1):
        k2 = (k + 1) % n
        bm.faces.new((ring_a[k], ring_a[k2], ring_b[k2], ring_b[k]))


def tube(bm, pts, radius, sides=8, caps=True, rfun=None, start_normal=None):
    """Sweep a ring along the polyline `pts`. rfun(i, t, theta) -> radius overrides
    `radius` (t = 0..1 along the path). Parallel-transport frames. The tube gets
    its own cylindrical UVs (u round, v along, one island) and the face flag
    "uvk" so the atlas unwrap keeps them. Returns the rings."""
    pts = [Vector(p) for p in pts]
    n = len(pts)
    tans = [(pts[min(i + 1, n - 1)] - pts[max(i - 1, 0)]).normalized() for i in range(n)]
    t0 = tans[0]
    ref = Vector(start_normal) if start_normal else (Vector((0, 0, 1)) if abs(t0.z) < 0.9 else Vector((1, 0, 0)))
    nrm = (ref - t0 * ref.dot(t0)).normalized()
    rings = []
    for i in range(n):
        t = tans[i]
        nrm = (nrm - t * nrm.dot(t)).normalized()
        bi = t.cross(nrm)
        ring = []
        for k in range(sides):
            th = TAU * k / sides
            r = rfun(i, i / max(1, n - 1), th) if rfun else radius
            ring.append(bm.verts.new(pts[i] + (nrm * math.cos(th) + bi * math.sin(th)) * r))
        rings.append(ring)
    uv = bm.loops.layers.uv.get("UVMap") or bm.loops.layers.uv.new("UVMap")
    keep = bm.faces.layers.int.get("uvk") or bm.faces.layers.int.new("uvk")
    circ = TAU * max(radius, 1e-3)
    along = [0.0]
    for a, b in zip(pts, pts[1:]):
        along.append(along[-1] + (b - a).length)
    for i in range(n - 1):
        for k in range(sides):
            k2 = (k + 1) % sides
            f = bm.faces.new((rings[i][k], rings[i][k2], rings[i + 1][k2], rings[i + 1][k]))
            u0, u1 = k / sides * circ, (k + 1) / sides * circ
            for loop, (u, v) in zip(f.loops, ((u0, along[i]), (u1, along[i]), (u1, along[i + 1]), (u0, along[i + 1]))):
                loop[uv].uv = (u, v)
            f[keep] = 1
    if caps:
        for ring, rev in ((rings[0], True), (rings[-1], False)):
            f = bm.faces.new(list(reversed(ring)) if rev else ring)
            for loop in f.loops:
                c = loop.vert.co - ring[0].co
                loop[uv].uv = (c.x, c.y + c.z)
    return rings


def prism(bm, outline, y0, y1, axis="Y"):
    """Extrude a closed 2D outline [(u, v)] between y0 and y1 along `axis`.
    axis Y: outline in X-Z; axis X: outline in Y-Z (u = y, v = z)."""
    def P(u, v, w):
        return (u, w, v) if axis == "Y" else (w, u, v)
    a = [bm.verts.new(P(u, v, y0)) for u, v in outline]
    b = [bm.verts.new(P(u, v, y1)) for u, v in outline]
    quad_strip(bm, a, b)
    bm.faces.new(list(reversed(a)))
    bm.faces.new(b)
    return a, b


def rounded_rect(x0, z0, x1, z1, r, n=6):
    """Counter-clockwise outline of a rounded rectangle in the (u, v) plane."""
    out = []
    for cx, cz, a0 in ((x1 - r, z0 + r, -90), (x1 - r, z1 - r, 0), (x0 + r, z1 - r, 90), (x0 + r, z0 + r, 180)):
        for k in range(n + 1):
            a = math.radians(a0 + 90 * k / n)
            out.append((cx + r * math.cos(a), cz + r * math.sin(a)))
    return out


def heightfield(bm, xs, ys, zf, keep=None, flip=False, xf=None):
    """Quad grid over xs x ys, z = zf(x, y) (xf(x, y) may move x). Faces whose
    centre fails keep(cx, cy) are skipped. Returns the vertex grid [row][col]."""
    grid = []
    for y in ys:
        grid.append([bm.verts.new((xf(x, y) if xf else x, y, zf(x, y))) for x in xs])
    for j in range(len(ys) - 1):
        for i in range(len(xs) - 1):
            if keep and not keep((xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2):
                continue
            q = (grid[j][i], grid[j][i + 1], grid[j + 1][i + 1], grid[j + 1][i])
            bm.faces.new(tuple(reversed(q)) if flip else q)
    return grid


def displace(o, fn, keep_y=False):
    """Move every vertex along its normal by fn(co, normal) (keep_y: never along Y,
    so lofted sections stay exact bend loops)."""
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bm.normal_update()
    moves = [(v, v.normal * fn(v.co.copy(), v.normal.copy())) for v in bm.verts]
    for v, d in moves:
        if keep_y:
            d.y = 0.0
        v.co += d
    bm.to_mesh(o.data)
    bm.free()
    o.data.update()
    return o


def warp(o, fn):
    """co -> fn(co) for every vertex."""
    for v in o.data.vertices:
        v.co = fn(v.co.copy())
    o.data.update()
    return o


def remesh(o, voxel, smooth_iter=0, smooth_factor=0.6):
    mesh.modifier(o, "REMESH", mode="VOXEL", voxel_size=voxel, adaptivity=0.0)
    if smooth_iter:
        mesh.modifier(o, "SMOOTH", factor=smooth_factor, iterations=smooth_iter)
    mesh.apply_modifiers(o)
    return o


def decimate_to(o, tris):
    cur = mesh.tri_count(o, evaluated=False)
    if cur > tris:
        mesh.decimate(o, ratio=tris / cur)
    return o


def delete_faces(o, pred):
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bm.normal_update()
    dead = [f for f in bm.faces if pred(f.calc_center_median(), f.normal)]
    bmesh.ops.delete(bm, geom=dead, context="FACES")
    bm.to_mesh(o.data)
    bm.free()
    o.data.update()
    return o


def join(objs, name):
    for o in objs:
        mesh.apply_transform(o)
    o = mesh.join(objs, name)
    mesh.apply_transform(o)
    return o


def text_mesh(name, body, size, extrude=0.01, offset=0.0, align="CENTER", spacing=1.0, res=3):
    """Blender text -> mesh, lying in XY (reading +X, facing +Z), centred."""
    cu = bpy.data.curves.new(name, "FONT")
    cu.body = body
    cu.size = size
    cu.extrude = 0.0   # flat glyphs: the walls cost islands and triangles nobody sees
    cu.offset = offset
    cu.align_x = align
    cu.align_y = "CENTER"
    cu.space_character = spacing
    cu.resolution_u = res
    tmp = lib.link(bpy.data.objects.new(name + "_tmp", cu))
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(tmp.evaluated_get(dg))
    bpy.data.objects.remove(tmp)
    bpy.data.curves.remove(cu)
    o = lib.link(bpy.data.objects.new(name, me))
    mesh.clean(o, merge=1e-4, recalc_normals=False)
    for p in me.polygons:   # flat glyphs must face +Z (single-sided materials)
        if p.normal.z < 0:
            p.flip()
    me.update()
    return o


FACE_TRACK = Matrix(((0, 0, -1, 0), (-1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 0, 1)))


def place(o, matrix):
    o.data.transform(matrix)
    o.data.update()
    return o


def set_mask(o, fn, name="mask"):
    """Per-vertex colour attribute (R, G, B) = fn(co) for material masks (baked, then dropped)."""
    me = o.data
    if name in me.color_attributes:
        me.color_attributes.remove(me.color_attributes[name])
    attr = me.color_attributes.new(name, "FLOAT_COLOR", "POINT")
    for i, v in enumerate(me.vertices):
        r, g, b = fn(v.co)
        attr.data[i].color = (r, g, b, 1.0)
    return o


def extras(o, slot, every, chance, side="both"):
    o["slot"] = slot
    o["every"] = float(every)
    o["chance"] = float(chance)
    o["side"] = side
    return o


def jhash(a, b):
    """src/render/atlas.ts hash(), for placing scenery like the renderer does."""
    def imul(x, y):
        return ((x & 0xFFFFFFFF) * (y & 0xFFFFFFFF)) & 0xFFFFFFFF
    h = imul(a ^ 0x9E3779B9, 0x85EBCA6B) ^ imul(b + 0x632BE5AB, 0xC2B2AE35)
    h &= 0xFFFFFFFF
    h ^= h >> 13
    h = imul(h, 0x27D4EB2F)
    h ^= h >> 15
    return h / 4294967296


class G:
    """A tiny node builder for one Principled material."""

    def __init__(self, m):
        self.m, self.nt = m, m.node_tree
        self.p = mat.principled(m)
        self._tc = None

    def n(self, kind, **kw):
        node = self.nt.nodes.new(kind)
        for k, v in kw.items():
            setattr(node, k, v)
        return node

    def ln(self, a, b):
        self.nt.links.new(a, b)

    def put(self, v, sock):
        if isinstance(v, bpy.types.NodeSocket):
            self.ln(v, sock)
        elif isinstance(v, str):
            sock.default_value = mat.rgba(v)
        elif isinstance(v, (tuple, list)) and len(v) == 3 and sock.type == "RGBA":
            sock.default_value = (*v, 1.0)
        else:
            sock.default_value = v

    def coord(self, kind="Object"):
        if self._tc is None:
            self._tc = self.n("ShaderNodeTexCoord")
        return self._tc.outputs[kind]

    def mapping(self, vec, scale=1.0, loc=(0, 0, 0), rot=(0, 0, 0)):
        mp = self.n("ShaderNodeMapping")
        self.ln(vec, mp.inputs["Vector"])
        s = (1 / scale,) * 3 if isinstance(scale, (int, float)) else tuple(1 / v for v in scale)
        mp.inputs["Scale"].default_value = s
        mp.inputs["Location"].default_value = loc
        mp.inputs["Rotation"].default_value = rot
        return mp.outputs["Vector"]

    def img(self, path, vec, data=False, box=True, blend=0.3):
        t = self.n("ShaderNodeTexImage")
        t.image = mat.image(path, data)
        if box:
            t.projection = "BOX"
            t.projection_blend = blend
        self.ln(vec, t.inputs["Vector"])
        return t

    def tex(self, set_id, vec, box=True, blend=0.3):
        """{color, normal, rough, ao, disp} sockets of a CC0 set, all on `vec`."""
        maps = mat.find_maps(set_id)
        out = {}
        for kind, key, data in (("color", "color", False), ("normal", "normal", True), ("roughness", "rough", True),
                                ("ao", "ao", True), ("displacement", "disp", True)):
            if kind in maps:
                out[key] = self.img(maps[kind], vec, data, box, blend).outputs["Color"]
        return out

    def math(self, op, a, b=0.0, c=0.0, clamp=False):
        node = self.n("ShaderNodeMath", operation=op, use_clamp=clamp)
        self.put(a, node.inputs[0])
        self.put(b, node.inputs[1])
        self.put(c, node.inputs[2])
        return node.outputs[0]

    def vmath(self, op, a, b=(0, 0, 0), scale=1.0):
        node = self.n("ShaderNodeVectorMath", operation=op)
        self.put(a, node.inputs[0])
        self.put(b, node.inputs[1])
        if "Scale" in node.inputs:
            node.inputs["Scale"].default_value = scale
        return node.outputs["Value"] if op in ("DOT_PRODUCT", "LENGTH", "DISTANCE") else node.outputs["Vector"]

    def mixc(self, fac, a, b, blend="MIX", clamp=True):
        node = self.n("ShaderNodeMix", data_type="RGBA", blend_type=blend, clamp_result=clamp)
        self.put(fac, node.inputs[0])
        self.put(a, node.inputs[6])
        self.put(b, node.inputs[7])
        return node.outputs[2]

    def mixf(self, fac, a, b):
        node = self.n("ShaderNodeMix", data_type="FLOAT")
        self.put(fac, node.inputs[0])
        self.put(a, node.inputs[2])
        self.put(b, node.inputs[3])
        return node.outputs[0]

    def mixv(self, fac, a, b):
        node = self.n("ShaderNodeMix", data_type="VECTOR")
        self.put(fac, node.inputs[0])
        self.put(a, node.inputs[4])
        self.put(b, node.inputs[5])
        return node.outputs[1]

    def noise(self, vec, scale=1.0, detail=4.0, rough=0.55, distortion=0.0, out="Fac"):
        t = self.n("ShaderNodeTexNoise")
        self.ln(vec, t.inputs["Vector"])
        t.inputs["Scale"].default_value = scale
        t.inputs["Detail"].default_value = detail
        t.inputs["Roughness"].default_value = rough
        t.inputs["Distortion"].default_value = distortion
        return t.outputs[out]

    def wave(self, vec, scale, distortion=0.0, detail=2.0, direction="Z", profile="SIN", phase=0.0,
             kind="BANDS", out="Fac"):
        t = self.n("ShaderNodeTexWave", wave_type=kind, wave_profile=profile)
        if kind == "BANDS":
            t.bands_direction = direction
        else:
            t.rings_direction = direction
        self.ln(vec, t.inputs["Vector"])
        t.inputs["Scale"].default_value = scale
        t.inputs["Distortion"].default_value = distortion
        t.inputs["Detail"].default_value = detail
        t.inputs["Phase Offset"].default_value = phase
        return t.outputs[out]

    def voronoi(self, vec, scale, out="Distance", feature="F1", randomness=1.0):
        t = self.n("ShaderNodeTexVoronoi", feature=feature)
        self.ln(vec, t.inputs["Vector"])
        t.inputs["Scale"].default_value = scale
        t.inputs["Randomness"].default_value = randomness
        return t.outputs[out]

    def ramp(self, fac, stops, interp="LINEAR"):
        r = self.n("ShaderNodeValToRGB")
        cr = r.color_ramp
        cr.interpolation = interp
        el = cr.elements
        for i, (pos, col) in enumerate(stops):
            e = el[i] if i < 2 else el.new(pos)
            e.position = pos
            e.color = mat.rgba(col) if isinstance(col, str) else (col, col, col, 1.0) if isinstance(col, (int, float)) else (*col, 1.0)
        self.ln(fac, r.inputs["Fac"])
        return r.outputs["Color"]

    def maprange(self, v, a, b, c=0.0, d=1.0, clamp=True, smooth=False):
        node = self.n("ShaderNodeMapRange", clamp=clamp, interpolation_type="SMOOTHSTEP" if smooth else "LINEAR")
        self.put(v, node.inputs["Value"])
        node.inputs["From Min"].default_value = a
        node.inputs["From Max"].default_value = b
        node.inputs["To Min"].default_value = c
        node.inputs["To Max"].default_value = d
        return node.outputs["Result"]

    def sep(self, vec):
        s = self.n("ShaderNodeSeparateXYZ")
        self.ln(vec, s.inputs["Vector"])
        return s.outputs

    def comb(self, x, y, z):
        c = self.n("ShaderNodeCombineXYZ")
        self.put(x, c.inputs[0])
        self.put(y, c.inputs[1])
        self.put(z, c.inputs[2])
        return c.outputs[0]

    def hsv(self, col, h=0.5, s=1.0, v=1.0):
        node = self.n("ShaderNodeHueSaturation")
        self.put(col, node.inputs["Color"])
        node.inputs["Hue"].default_value = h
        node.inputs["Saturation"].default_value = s
        node.inputs["Value"].default_value = v
        return node.outputs["Color"]

    def bw(self, col):
        node = self.n("ShaderNodeRGBToBW")
        self.put(col, node.inputs[0])
        return node.outputs[0]

    def normalmap(self, col, strength=1.0):
        nm = self.n("ShaderNodeNormalMap")
        nm.inputs["Strength"].default_value = strength
        self.ln(col, nm.inputs["Color"])
        return nm.outputs["Normal"]

    def bump(self, height, strength=0.3, distance=0.02, normal=None):
        b = self.n("ShaderNodeBump")
        b.inputs["Strength"].default_value = strength
        b.inputs["Distance"].default_value = distance
        self.put(height, b.inputs["Height"])
        if normal is not None:
            self.ln(normal, b.inputs["Normal"])
        return b.outputs["Normal"]

    def geo(self, out):
        if not hasattr(self, "_geo"):
            self._geo = self.n("ShaderNodeNewGeometry")
        return self._geo.outputs[out]

    def attr(self, name, out="Color"):
        a = self.n("ShaderNodeAttribute", attribute_name=name)
        return a.outputs[out]

    def rgb_split(self, col):
        s = self.n("ShaderNodeSeparateColor")
        self.put(col, s.inputs[0])
        return s.outputs

    def out(self, base=None, rough=None, normal=None, metal=None, emission=None, strength=None, ao=None,
            coat=None, sheen=None):
        p = self.p
        for v, key in ((base, "Base Color"), (rough, "Roughness"), (normal, "Normal"), (metal, "Metallic"),
                       (emission, "Emission Color"), (strength, "Emission Strength"), (coat, "Coat Weight"),
                       (sheen, "Sheen Weight")):
            if v is not None:
                self.put(v, p.inputs[key])
        if ao is not None:
            self.put(ao, mat.gltf_output(self.m).inputs["Occlusion"])
        return self.m


def edge_wear(g, col, amount=0.25, cavity=0.35):
    """Lighter convex edges, darker cavities (Cycles pointiness: the bake sees it)."""
    pt = g.geo("Pointiness")
    edge = g.maprange(pt, 0.52, 0.6)
    cav = g.maprange(pt, 0.48, 0.4)
    col = g.mixc(g.math("MULTIPLY", edge, amount), col, g.hsv(col, s=0.8, v=1.45))
    return g.mixc(g.math("MULTIPLY", cav, cavity), col, g.hsv(col, v=0.45))


def deck_ys():
    inner = [-SCR_HL + 2 * SCR_HL * k / 9 for k in range(10)]
    return [-ROW / 2, -2.055] + inner + [2.055, ROW / 2]


def opening_dist(x, y):
    best = 1e9
    for c in LANES:
        dx, dy = abs(x - c) - SCR_HW, abs(y) - SCR_HL
        d = max(dx, dy) if dx <= 0 and dy <= 0 else math.hypot(max(dx, 0), max(dy, 0))
        best = min(best, d)
    return best


def zipper(bm, A, B, want_y, centre=None):
    """Triangulate the strip between two vertex polylines running the same way;
    faces oriented to +-Y. With `centre` (x, z), both advance by their unwrapped
    angle round it (star-shaped arcs never cross), else by arc length."""
    def cum(L):
        if centre is not None:
            out, prev = [], None
            for v in L:
                a = math.atan2(v.co.z - centre[1], v.co.x - centre[0])
                if prev is not None:
                    while a < prev - math.pi:
                        a += TAU
                    while a > prev + math.pi:
                        a -= TAU
                out.append(a)
                prev = a
            return out
        d = [0.0]
        for a, b in zip(L, L[1:]):
            d.append(d[-1] + (b.co - a.co).length)
        return [x / (d[-1] or 1.0) for x in d]
    ta, tb = cum(A), cum(B)
    i = j = 0
    while i < len(A) - 1 or j < len(B) - 1:
        if j >= len(B) - 1 or (i < len(A) - 1 and ta[i + 1] <= tb[j + 1]):
            f = bm.faces.new((A[i], A[i + 1], B[j]))
            i += 1
        else:
            f = bm.faces.new((A[i], B[j + 1], B[j]))
            j += 1
        f.normal_update()
        if f.normal.y * want_y < 0:
            f.normal_flip()


def split_long(o, max_len=1.0, axis=1, iters=8):
    """Bend loops without slicing the whole mesh: split only edges spanning more
    than max_len along the track (Y). Returns the largest span left."""
    bm = bmesh.new()
    bm.from_mesh(o.data)
    for _ in range(iters):
        long = [e for e in bm.edges if abs(e.verts[0].co[axis] - e.verts[1].co[axis]) > max_len]
        if not long:
            break
        bmesh.ops.subdivide_edges(bm, edges=long, cuts=1, use_grid_fill=False, use_single_edge=False)
        ngons = [f for f in bm.faces if len(f.verts) > 4]
        if ngons:
            bmesh.ops.triangulate(bm, faces=ngons, quad_method="BEAUTY", ngon_method="BEAUTY")
    span = max((abs(e.verts[0].co[axis] - e.verts[1].co[axis]) for e in bm.edges), default=0.0)
    bm.to_mesh(o.data)
    bm.free()
    o.data.update()
    return span


def max_span(o, axis=1):
    me = o.data
    return max((abs(me.vertices[e.vertices[0]].co[axis] - me.vertices[e.vertices[1]].co[axis]) for e in me.edges),
               default=0.0)


def fit_tris(o, target, loops=1.0, tries=7):
    """Decimate so that the count after split_long lands just under `target`
    (bisection on the decimation target)."""
    src = o.data.copy()

    def attempt(t):
        old = o.data
        o.data = src.copy()
        bpy.data.meshes.remove(old)
        decimate_to(o, t)
        split_long(o, loops)
        return mesh.tri_count(o, evaluated=False)

    lo, hi, best = target * 0.15, target * 1.0, None
    for i in range(tries):
        t = int(target * 0.6) if i == 0 else int((lo + hi) / 2)
        got = attempt(t)
        if got <= target:
            best, lo = t, t
        else:
            hi = t
    got = attempt(best if best is not None else int(lo))
    bpy.data.meshes.remove(src)
    return got


def column(bm, x, y, z0, z1, rfun, sides=14, step=1.0):
    """A vertical radial solid: rfun(theta, z) -> radius, rings every `step`."""
    n = max(2, int(math.ceil((z1 - z0) / step)) + 1)
    zs = [z0 + (z1 - z0) * i / (n - 1) for i in range(n)]
    rings = []
    for z in zs:
        rings.append([bm.verts.new((x + rfun(TAU * k / sides, z) * math.cos(TAU * k / sides),
                                    y + rfun(TAU * k / sides, z) * math.sin(TAU * k / sides), z)) for k in range(sides)])
    for a, b in zip(rings, rings[1:]):
        quad_strip(bm, a, b)
    bm.faces.new(list(reversed(rings[0])))
    bm.faces.new(rings[-1])
    return rings


def slab(bm, x0, x1, y0, y1, z0, z1):
    bmesh.ops.create_cube(bm, size=1.0, matrix=Matrix.Translation(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)) @
                          Matrix.Diagonal((x1 - x0, y1 - y0, z1 - z0, 1)))


def bmesh_face_minus_x(o):
    for p in o.data.polygons:
        if p.normal.x > 0:
            p.flip()
    o.data.update()


def hard(o, angle=40):
    mesh.smooth(o, angle=angle)
    return o


def delete_bottom(o):
    delete_faces(o, lambda c, n: n.z < -0.9)



# ================================================================ materials

def m_linen(name, tint="#5c6784", scale=0.7, bright=1.0, rough=0.92, normal=1.0, quilt=0.0, stains=0.3, sheen=0.5):
    """Bed linen (CC0 rough_linen), a little sheen, lint and faint stains.
    quilt > 0: stitched quilting lines every 4.4 m (object space) with puffing."""
    m = mat.new_material(name)
    g = G(m)
    ob = g.coord("Object")
    t = g.tex("rough_linen", g.mapping(ob, scale))
    col = g.mixc(1.0, g.hsv(t["color"], s=0.25, v=1.9), tint, blend="MULTIPLY")
    col = g.hsv(col, v=bright)
    tone = g.maprange(g.noise(ob, 0.35, 3), 0.3, 0.7)
    col = g.mixc(tone, g.hsv(col, v=0.82), g.hsv(col, v=1.12))
    st = g.maprange(g.noise(ob, 0.12, 4, distortion=0.6), 0.62, 0.72)
    col = g.mixc(g.math("MULTIPLY", st, stains), col, g.hsv(col, s=1.3, v=0.8))
    n = g.normalmap(t["normal"], normal)
    if quilt > 0:
        xyz = g.sep(ob)
        dx = g.math("ABSOLUTE", g.math("SUBTRACT", g.math("FRACT", g.math("DIVIDE", xyz[0], 4.4)), 0.5))
        dy = g.math("ABSOLUTE", g.math("SUBTRACT", g.math("FRACT", g.math("DIVIDE", xyz[1], 4.4)), 0.5))
        d = g.math("MULTIPLY", g.math("SUBTRACT", 0.5, g.math("MAXIMUM", dx, dy)), 4.4)
        line = g.maprange(d, 0.05, 0.0)
        dash = g.math("GREATER_THAN", g.math("FRACT", g.math("MULTIPLY", g.math("ADD", xyz[0], xyz[1]), 5.0)), 0.35)
        stitch = g.math("MULTIPLY", g.maprange(d, 0.018, 0.0), dash)
        puff = g.maprange(d, 0.0, 1.4, 0.0, 1.0)
        col = g.mixc(g.math("MULTIPLY", line, 0.5 * quilt), col, g.hsv(col, v=0.45))
        col = g.mixc(g.math("MULTIPLY", stitch, quilt), col, g.hsv(col, s=0.6, v=1.5))
        n = g.bump(g.math("MULTIPLY", g.math("POWER", puff, 0.5), 1.0), 0.6 * quilt, 0.25, n)
    return g.out(col, rough, n, 0.0, ao=t.get("ao"), sheen=sheen)


def m_deck(name="DuvetDeck"):
    """Deck duvet: linen with the stitching (mask R), pocket hems round the
    screens (G, smoother), the hanging skirt / underside (B, darker)."""
    m = mat.new_material(name)
    g = G(m)
    ob = g.coord("Object")
    mk = g.rgb_split(g.attr("mask"))
    t = g.tex("rough_linen", g.mapping(ob, 0.55))
    t2 = g.tex("rough_linen", g.mapping(ob, 0.3, rot=(0, 0, 0.7)))
    base = g.mixc(1.0, g.hsv(t["color"], s=0.25, v=1.9), "#56617e", blend="MULTIPLY")
    tone = g.maprange(g.noise(ob, 0.6, 3), 0.3, 0.7)
    base = g.mixc(tone, g.hsv(base, v=0.85), g.hsv(base, v=1.1))
    hem = g.mixc(1.0, g.hsv(t2["color"], s=0.2, v=1.9), "#6d7896", blend="MULTIPLY")
    col = g.mixc(mk[1], base, hem)
    col = g.mixc(mk[2], col, g.hsv(col, v=0.55))
    # stitch thread: dashed pale lines where the mask says so
    xyz = g.sep(ob)
    dash = g.math("GREATER_THAN", g.math("FRACT", g.math("MULTIPLY", g.math("ADD", xyz[0], xyz[1]), 6.0)), 0.4)
    col = g.mixc(g.math("MULTIPLY", mk[0], g.math("MULTIPLY", dash, 0.8)), g.mixc(mk[0], col, g.hsv(col, v=0.5)),
                 g.hsv(col, s=0.5, v=1.4))
    n = g.mixv(mk[1], g.normalmap(t["normal"], 1.0), g.normalmap(t2["normal"], 0.6))
    n = g.bump(g.math("MULTIPLY", mk[0], -1.0), 0.4, 0.03, n)
    return g.out(col, 0.9, n, 0.0, sheen=0.5)


def m_fleece(name, tint, scale=0.35, stripe=None):
    """Knitted socks (CC0 knitted_fleece), optional heel/toe colour by mask G."""
    m = mat.new_material(name)
    g = G(m)
    ob = g.coord("Object")
    t = g.tex("knitted_fleece", g.mapping(ob, scale))
    col = g.mixc(1.0, g.hsv(t["color"], s=0.2, v=1.7), tint, blend="MULTIPLY")
    if stripe:
        k = g.rgb_split(g.attr("mask"))[1]
        col = g.mixc(k, col, g.mixc(1.0, g.hsv(t["color"], s=0.2, v=1.7), stripe, blend="MULTIPLY"))
    pill = g.maprange(g.noise(ob, 3.0, 4), 0.62, 0.8)
    col = g.mixc(g.math("MULTIPLY", pill, 0.4), col, g.hsv(col, s=0.5, v=1.4))
    return g.out(col, 0.95, g.normalmap(t["normal"], 1.3), 0.0, ao=t.get("ao"), sheen=0.6)


def m_plastic(name, color, rough=0.4, grime=0.35, scale=0.5):
    m = mat.new_material(name)
    g = G(m)
    ob = g.coord("Object")
    t = g.tex("Plastic010", g.mapping(ob, scale))
    dirt = g.maprange(g.noise(ob, 1.5, 4), 0.5, 0.8)
    col = g.mixc(g.math("MULTIPLY", dirt, grime), color, "#7a7468")
    col = edge_wear(g, col, 0.15, 0.4)
    scratch = g.maprange(g.noise(g.mapping(ob, (0.05, 0.05, 1.0)), 1.0, 3), 0.6, 0.7)
    return g.out(col, g.mixf(scratch, rough, rough + 0.25), g.normalmap(t["normal"], 0.35), 0.0)


def m_alu(name="CanAlu", tint="#c9ccd2", rough=0.28):
    m = mat.new_material(name)
    g = G(m)
    ob = g.coord("Object")
    t = g.tex("Metal009", g.mapping(ob, 0.6))
    col = g.mixc(1.0, t["color"], tint, blend="MULTIPLY")
    return g.out(col, g.math("MULTIPLY_ADD", t["rough"], 0.3, rough - 0.1, clamp=True), g.normalmap(t["normal"], 0.4), 1.0)


def m_paint(name, color, rough=0.35, metal=0.0, set_id="Plastic010", scale=0.6, wear=0.0):
    m = mat.new_material(name)
    g = G(m)
    ob = g.coord("Object")
    t = g.tex(set_id, g.mapping(ob, scale))
    col = mat.rgba(color)
    if wear:
        w = g.maprange(g.noise(ob, 2.5, 5, 0.7), 0.64, 0.74)
        col = g.mixc(g.math("MULTIPLY", w, wear), color, "#b8bcc4")
    else:
        col = g.mixc(0.0, color, color)
    return g.out(col, rough, g.normalmap(t["normal"], 0.25), metal)


def m_wood(name="NightstandWood", tint="#8a5e3c", scale=6.0):
    m = mat.new_material(name)
    g = G(m)
    ob = g.coord("Object")
    t = g.tex("WoodFloor051", g.mapping(ob, scale))
    col = g.hsv(g.mixc(1.0, t["color"], tint, blend="MULTIPLY"), s=0.85, v=1.6)
    col = edge_wear(g, col, 0.25, 0.4)
    return g.out(col, g.math("MULTIPLY_ADD", t["rough"], 0.3, 0.3, clamp=True), g.normalmap(t["normal"], 0.8), 0.0,
                 ao=t.get("ao"), coat=0.3)


def m_pages(name="BookPages"):
    """Off-white page block: fine page lines along Z, yellowing."""
    m = mat.new_material(name)
    g = G(m)
    ob = g.coord("Object")
    t = g.tex("Cardboard004", g.mapping(ob, 1.2))
    lines = g.wave(g.mapping(ob, 1.0), 9.0, distortion=0.4, detail=0.0, direction="Z")
    col = g.mixc(1.0, g.hsv(t["color"], s=0.2, v=2.2), "#e8dfc8", blend="MULTIPLY")
    col = g.mixc(g.math("MULTIPLY", lines, 0.25), col, g.hsv(col, v=0.7))
    return g.out(col, 0.85, g.bump(lines, 0.3, 0.01), 0.0)


def m_cloth_cover(name, color):
    m = mat.new_material(name)
    g = G(m)
    ob = g.coord("Object")
    t = g.tex("rough_linen", g.mapping(ob, 0.35))
    col = g.mixc(1.0, g.hsv(t["color"], s=0.2, v=1.8), color, blend="MULTIPLY")
    col = edge_wear(g, col, 0.35, 0.3)
    return g.out(col, 0.75, g.normalmap(t["normal"], 0.8), 0.0)


def m_plaid(name="FortBlanket"):
    """A cosy plaid throw, fleece-soft: stripes across and along, knitted normal."""
    m = mat.new_material(name)
    g = G(m)
    ob = g.coord("Object")
    t = g.tex("knitted_fleece", g.mapping(ob, 0.45))
    xyz = g.sep(ob)
    s1 = g.maprange(g.math("SINE", g.math("MULTIPLY", xyz[1], TAU / 2.2)), 0.55, 0.75)       # across the track
    s2 = g.maprange(g.math("SINE", g.math("MULTIPLY", g.math("ADD", xyz[2], xyz[0]), TAU / 3.1)), 0.55, 0.75)
    s3 = g.maprange(g.math("SINE", g.math("MULTIPLY", xyz[1], TAU / 0.55)), 0.8, 0.95)
    base = g.mixc(1.0, g.hsv(t["color"], s=0.2, v=2.2), "#9a3a36", blend="MULTIPLY")
    col = g.mixc(g.math("MULTIPLY", g.math("MAXIMUM", s1, s2), 0.8), base, "#3a4670")
    col = g.mixc(g.math("MULTIPLY", s3, 0.6), col, "#d8b070")
    return g.out(col, 0.95, g.normalmap(t["normal"], 1.2), 0.0, sheen=0.7)


def m_braid(name="BraidCable", color="#d9d6d0"):
    """Braided nylon sleeve round a cable along +Y centred on (0, *, 1.0)."""
    m = mat.new_material(name)
    g = G(m)
    ob = g.coord("Object")
    xyz = g.sep(ob)
    th = g.math("ARCTAN2", g.math("SUBTRACT", xyz[2], 1.0), xyz[0])
    a = g.math("SINE", g.math("ADD", g.math("MULTIPLY", th, 8.0), g.math("MULTIPLY", xyz[1], TAU / 0.16)))
    b = g.math("SINE", g.math("SUBTRACT", g.math("MULTIPLY", th, 8.0), g.math("MULTIPLY", xyz[1], TAU / 0.16)))
    weave = g.maprange(g.math("MULTIPLY", a, b), -1.0, 1.0)
    col = g.mixc(g.math("MULTIPLY", weave, 0.35), color, "#8c8a86")
    dirt = g.maprange(g.noise(ob, 2.0, 3), 0.5, 0.8)
    col = g.mixc(g.math("MULTIPLY", dirt, 0.3), col, "#6a6258")
    return g.out(col, 0.6, g.bump(weave, 0.5, 0.01), 0.0, sheen=0.4)


def m_glow(name, color, strength):
    return mat.flat(name, "#101010", rough=0.3, emission=color, strength=strength)


def m_seam():
    return mat.flat("Seam", "#6f8dff", rough=0.4, emission="#6f8dff", strength=4.0)


def m_glass():
    g = mat.glass("Glass", color=(0.85, 0.9, 1.0), rough=0.05, alpha=0.16, smudges="Fingerprints002", smudge_strength=0.3)
    return g


# ================================================================ pieces

PIECES = {}


def piece(fn):
    PIECES[fn.__name__.replace("build_", "", 1)] = fn
    return fn


# ---------------------------------------------------------------- deck: the quilted duvet

DECK_XS_HALF = [0.96, 0.99, 1.035, 1.075, 1.1, 1.125, 1.165, 1.21, 1.24,
                3.16, 3.19, 3.235, 3.275, 3.3, 3.325, 3.365, 3.52, 3.78, 4.05, 4.3, 4.52, 4.68, 4.8]


def seam_dist(x):
    return min(abs(x - s) for s in SEAMS)


def cushion(x, y):
    """Puffy quilted cushion on the margins, stitched across at the row ends."""
    ax = abs(x)
    if ax < 3.36 or ax > 4.66:
        return 0.0
    px = math.sin(math.pi * (ax - 3.36) / 1.3) ** 0.75
    py = max(0.0, math.sin(math.pi * (y + ROW / 2) / ROW)) ** 0.55
    return 0.3 * px * py


def deck_top_z(x, y):
    ax = abs(x)
    d = opening_dist(x, y)
    if d <= 1e-4:
        return -0.02
    wrinkle = 0.008 * pnoise(x, y, scale=2.2, seed=1) + 0.012 * pnoise(x, y, scale=0.7, seed=4)
    row_stitch = 1.0 - 0.55 * math.exp(-((abs(y) - ROW / 2) / 0.06) ** 2)
    if d <= 0.031:
        return 0.055 * row_stitch
    sd = seam_dist(x)
    if sd < 0.1:
        return (0.02 + 0.5 * max(0.0, sd - 0.02)) * row_stitch + wrinkle * 0.3   # stitched channel under the piping
    z = 0.075 + wrinkle
    if ax > 3.33:
        z += cushion(x, y)
        if ax >= 4.66:
            z = lerp(z, -0.22, smoothstep(4.66, 4.8, ax) ** 0.7)
    return z * row_stitch if ax < 3.33 else z


@piece
def build_deck():
    xs = sorted({-x for x in DECK_XS_HALF} | set(DECK_XS_HALF))
    ys = deck_ys()
    bm = bmesh.new()
    top = heightfield(bm, xs, ys, deck_top_z, lambda cx, cy: opening_dist(cx, cy) > 0)

    # the duvet skirt hanging over the edge (folds, 3 per row) and a hidden underside
    def skirt(side, k):
        zk = (-0.62, -1.02, -1.38)[k]
        return [bm.verts.new((side * (4.84 + 0.05 * k + 0.07 * math.sin(TAU * 3 * y / ROW + side + k * 0.6)), y, zk))
                for y in ys]
    for side, ti in ((-1, 0), (1, -1)):
        rows = [[top[j][ti] for j in range(len(ys))]] + [skirt(side, k) for k in range(3)]
        for a, b in zip(rows, rows[1:]):
            for j in range(len(ys) - 1):
                q = (a[j], a[j + 1], b[j + 1], b[j])
                bm.faces.new(q if side < 0 else tuple(reversed(q)))
        if side < 0:
            left_bottom = rows[-1]
        else:
            right_bottom = rows[-1]
    xu = [-3.6, -1.2, 1.2, 3.6]
    under = [[left_bottom[j]] + [bm.verts.new((x, y, -1.42)) for x in xu] + [right_bottom[j]] for j, y in enumerate(ys)]
    for j in range(len(ys) - 1):
        for i in range(len(under[0]) - 1):
            bm.faces.new((under[j][i], under[j + 1][i], under[j + 1][i + 1], under[j][i + 1]))
    o = bm_obj("deck", bm)
    mesh.clean(o, recalc_normals=False)

    def mask(co):
        stitch = 1.0 if (seam_dist(co.x) < 0.045 or (abs(abs(co.y) - ROW / 2) < 0.03 and co.z > -0.1)) else 0.0
        hem = 1.0 if (opening_dist(co.x, co.y) < 0.05 and co.z > -0.1) else 0.0
        under = 1.0 if co.z < -0.25 else 0.0
        return stitch, hem, under
    set_mask(o, mask)
    mesh.smooth(o, angle=None)
    mat.assign(o, m_deck())
    o["atlas_weight"] = 60.0
    return o


@piece
def build_deck_seam():
    """Charger-cable piping along the four stitch lines (half cords)."""
    bm = bmesh.new()
    ys = [-ROW / 2 + ROW * k / 10 for k in range(11)]
    r, zc = 0.046, 0.05
    for s in SEAMS:
        prof = [(s + r * math.cos(a), zc + r * math.sin(a)) for a in (math.pi, 0.75 * math.pi, 0.5 * math.pi, 0.25 * math.pi, 0.0)]
        rings = [[bm.verts.new((px, y, pz)) for px, pz in prof] for y in ys]
        for j in range(len(ys) - 1):
            quad_strip(bm, rings[j + 1], rings[j], closed=False)
    o = bm_obj("deck_seam", bm)
    for p in o.data.polygons:
        if p.normal.z < 0:
            p.flip()
    mesh.smooth(o, angle=None)
    mat.assign(o, m_seam())
    mesh.uv_box(o, 0.5)
    return o


# ---------------------------------------------------------------- tunnel: a blanket fort

def fort_section(y, off=0.0, n_side=7, n_roof=9):
    """Open polyline (x, z) of the draped blanket, left hem -> ridge -> right hem.
    off: offset outward (the blanket's outer face)."""
    ph = TAU * y / ROW
    pts = []
    for side in (-1, 1):
        half = []
        # hanging side: from the hem (below the deck) up to the chair-back top
        for i in range(n_side):
            t = i / (n_side - 1)
            z = lerp(-5.5, 8.1, t)
            fold = 0.32 * math.sin(3 * ph + side * 0.9 + z * 0.12) * (1.0 - 0.8 * t) + 0.1 * math.sin(7 * ph + z * 0.4)
            x = side * (6.55 + 0.25 * (1 - t) ** 2 + fold + off)
            half.append((x, z))
        # roof: sagging from the chair top up to the ridge pole
        for i in range(1, n_roof):
            t = i / n_roof
            x = side * lerp(6.45, 0.0, t)
            z = lerp(8.35, 11.35, t) - 0.55 * math.sin(math.pi * t) + 0.12 * math.sin(2 * ph + side + t * 5.0) * \
                math.sin(math.pi * t)
            half.append((x + side * off * 0.3, z + off))
        pts.append(half)
    left, right = pts
    return left + [(0.0, 11.35 + 0.08 + off)] + list(reversed(right))


@piece
def build_tunnel():
    ys = [-ROW / 2 + ROW * k / 10 for k in range(11)]
    bm = bmesh.new()
    inner = [[bm.verts.new((x, y, z)) for x, z in fort_section(y)] for y in ys]
    outer = [[bm.verts.new((x, y, z)) for x, z in fort_section(y, off=0.14, n_side=4, n_roof=5)] for y in ys]
    for j in range(len(ys) - 1):
        quad_strip(bm, inner[j + 1], inner[j], closed=False)   # faces the cavity
        quad_strip(bm, outer[j], outer[j + 1], closed=False)   # faces outside
    for ring_i, ring_o, want in ((inner[0], outer[0], -1.0), (inner[-1], outer[-1], 1.0)):
        zipper(bm, ring_i, ring_o, want)
    o = bm_obj("tunnel", bm)
    mesh.smooth(o, angle=None)
    mat.assign(o, m_plaid())
    parts = [o]
    # ridge pole (a broom handle) under the blanket
    bm = bmesh.new()
    tube(bm, [(0, y, 11.18) for y in ys], 0.13, sides=8, caps=False)
    pole = bm_obj("pole", bm)
    mat.assign(pole, m_wood("PoleWood", "#6e4a30", scale=2.0))
    parts.append(hard(pole, 70))
    # fairy lights: two swagged strands along the roof, warm bulbs
    bm = bmesh.new()
    bulbs = bmesh.new()
    for side in (-1, 1):
        xs_ = side * 3.3
        pts = []
        for k in range(11):
            y = ys[k]
            t = 3.3 / 6.45
            z = lerp(11.35, 8.35, t) - 0.55 * math.sin(math.pi * (1 - t)) - 0.28 - 0.25 * math.sin(math.pi * ((y + 2.2) / 2.2 % 1.0))
            pts.append((xs_, y, z))
        tube(bm, pts, 0.018, sides=3, caps=False)
        for k in range(6):
            y = -ROW / 2 + ROW * (k + 0.5) / 6
            z = lerp(11.35, 8.35, 3.3 / 6.45) - 0.55 * math.sin(math.pi * (1 - 3.3 / 6.45)) - 0.36 - \
                0.25 * math.sin(math.pi * ((y + 2.2) / 2.2 % 1.0))
            bmesh.ops.create_icosphere(bulbs, subdivisions=1, radius=0.085,
                                       matrix=Matrix.Translation((xs_, y, z)) @ Matrix.Diagonal((1, 1, 1.35, 1)))
    wire = bm_obj("fairy_wire", bm)
    mat.assign(wire, mat.flat("FairyWire", "#2a2a22", rough=0.5))
    parts.append(wire)
    lights = bm_obj("fairy_bulbs", bulbs)
    mat.assign(lights, m_glow("FairyBulb", "#ffb45e", 7.0))
    parts.append(lights)
    # clothes pegs holding the blanket on the chair backs
    for side in (-1, 1):
        for y in (-1.2, 1.3):
            pg = mesh.box("peg", (0.12, 0.08, 0.5), location=(side * 6.62, y, 8.05), bevel=0.02, segments=1)
            mat.assign(pg, m_wood("PegWood", "#b89468", scale=1.0))
            parts.append(hard(pg))
    o = join(parts, "tunnel")
    o["atlas_weight"] = 6.0
    return o


# ---------------------------------------------------------------- overhang: a pillow bridge on two book stacks

@piece
def build_overhang():
    bm = bmesh.new()
    prism(bm, rounded_rect(-4.15, 1.14, 4.15, 3.18, 0.55, n=6), -0.55, 0.55)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    o = bm_obj("pillow", bm)
    remesh(o, 0.06, smooth_iter=14, smooth_factor=0.8)

    def inflate(co, n):
        u = clamp(abs(co.x) / 4.15)
        v = clamp(abs(co.z - 2.16) / 1.04)
        body = (1 - u ** 4) * (1 - v ** 3)
        puff = 0.32 * body * abs(n.y)
        crease = -0.03 * abs(math.sin(co.x * 2.1 + co.z * 3.0 + 1.3 * fbm(co * 0.8, 2))) * body
        return puff + crease + 0.012 * fbm(co * 3.0, 2)
    displace(o, inflate)

    def sag(co):
        co.z -= 0.07 * (1 - (co.x / 4.2) ** 2)
        if abs(co.x) < 3.25 and co.z < 1.06:
            co.z = 1.06
        return co
    warp(o, sag)
    decimate_to(o, 1900)
    mesh.smooth(o, angle=None)
    mat.assign(o, m_linen("PillowCase", tint="#9aa6c6", scale=0.45, bright=1.15, stains=0.2))
    parts = [o]
    # glowing piping round the seam (blue, readable in the dark)
    bm = bmesh.new()
    rr = rounded_rect(-4.12, 1.11, 4.12, 3.14, 0.5, n=5)
    loop = [Vector((x, 0.0, z)) for x, z in rr]
    loop = [loop[i].lerp(loop[(i + 1) % len(loop)], t) for i in range(len(loop)) for t in (0.0, 0.5)]
    for p in loop:
        p.z -= 0.07 * (1 - (p.x / 4.2) ** 2)
        if abs(p.x) < 3.25:
            p.z = max(p.z, 1.07)
    tube(bm, loop + loop[:1], 0.055, sides=6, caps=False)
    piping = bm_obj("piping", bm)
    mat.assign(piping, m_glow("PipingGlow", "#6f9dff", 4.5))
    parts.append(piping)
    # book stacks under its ends (outside the lanes)
    covers = [m_cloth_cover(f"OverBook{i}", c) for i, c in enumerate(("#2c4a52", "#5a2a2a", "#6b5a2c"))]
    pages = m_pages("OverPages")
    for sx in (-1, 1):
        z = 0.0
        for i, (w, d, t, rot) in enumerate(((1.35, 1.2, 0.42, 0.06), (1.2, 1.05, 0.36, -0.1), (1.28, 1.1, 0.38, 0.12))):
            cx = sx * 4.25
            bk = book(f"ob{sx}{i}", w, d, t, covers[i], pages)
            place(bk, Matrix.Translation((cx, 0.0, z)) @ Matrix.Rotation(rot, 4, "Z"))
            parts.append(bk)
            z += t
    o = join(parts, "overhang")
    o["atlas_weight"] = 12.0
    return o


def book(name, w, d, t, cover, pages, spine_side=-1):
    """A hardcover lying flat: page block inset on three sides, boards and a
    spine; origin at the bottom centre. w along X (spine at -X), d along Y."""
    b = 0.06 * t / 0.4
    parts = []
    for z0 in (0.0, t - b):
        c = mesh.box("board", (w, d, b), location=(0, 0, z0 + b / 2), bevel=b * 0.3, segments=1)
        mat.assign(c, cover)
        parts.append(hard(c))
    sp = mesh.box("spine", (b * 1.4, d, t), location=(spine_side * (w / 2 - b * 0.7), 0, t / 2), bevel=b * 0.5, segments=1)
    mat.assign(sp, cover)
    parts.append(hard(sp, 50))
    pb = mesh.box("pages", (w - 0.12 * w / 1.3, d - 0.08, t - 2 * b + 0.01), location=(-spine_side * 0.04, 0, t / 2))
    mat.assign(pb, pages)
    parts.append(hard(pb))
    return join(parts, name)


# ---------------------------------------------------------------- duvet mounds (what the props stand on)

def loft(name, y0, y1, step, height, front, back, zs, top_n=6, end=0.2, disp=None, top_z=None):
    """Sections every `step` along Y (bend loops for free): front face x =
    front(y, z, h) for z in zs(h), a top (z = top_z(u, y, h)), the back. Ends
    round off in plan over `end` of the length. Fan caps."""
    n = max(2, int(math.ceil((y1 - y0) / step)) + 1)
    ys = [y0 + (y1 - y0) * i / (n - 1) for i in range(n)]
    bm = bmesh.new()
    rings = []
    for y in ys:
        t = 2 * (y - y0) / (y1 - y0) - 1
        k = smoothstep(1 - end, 1.0, abs(t))
        pull = 0.85 * (1 - math.sqrt(max(0.0, 1 - k * k)))
        h0 = height(y)
        h = h0 - (h0 + 1.5) * 0.8 * k * k
        zl = zs(h)
        fr = [(min(front(y, z, h), back(y, z, h) - 0.8), z) for z in zl]   # never through the back
        bk = [(back(y, z, h), z) for z in reversed(zl[:: max(1, len(zl) // 4)])]
        if bk[-1][1] != zl[0]:
            bk.append((back(y, zl[0], h), zl[0]))
        xa, xb = fr[-1][0], bk[0][0]
        top = [(lerp(xa, xb, i / top_n), (top_z(i / top_n, y, h) if top_z else h)) for i in range(1, top_n)]
        sec = fr + top + bk
        mid = sum(x for x, _ in sec) / len(sec)
        zmid = sum(z for _, z in sec) / len(sec)
        sec = [(lerp(x, mid, pull), z) for x, z in sec]
        rings.append([bm.verts.new((x, y, z)) for x, z in sec])
    for a, b in zip(rings, rings[1:]):
        quad_strip(bm, a, b)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    f0 = bm.faces[len(rings[0]) // 3]
    c0 = f0.calc_center_median()
    rm = sum((v.co for v in rings[len(rings) // 2]), Vector()) / len(rings[0])
    if f0.normal.dot(Vector((c0.x - rm.x, 0.0, c0.z - rm.z))) < 0:
        for f in bm.faces:
            f.normal_flip()
    if disp:  # detail along the normal, never along Y (sections stay exact bend loops), before the caps
        bm.normal_update()
        moves = []
        ends = set(rings[0]) | set(rings[-1])   # the end rings stay put: their caps must not fold
        for v in bm.verts:
            if v in ends:
                continue
            d = v.normal * disp(v.co.copy(), v.normal.copy())
            d.y = 0.0
            moves.append((v, d))
        for v, d in moves:
            v.co += d
    for ring, want in ((rings[0], -1.0), (rings[-1], 1.0)):
        # the end sections are flat, possibly concave polygons: ear-clip them, on their own
        # vertices, so the cap is its own UV island (the pulled-in end faces fold behind it)
        cap = bm.faces.new([bm.verts.new(v.co) for v in ring])
        res = bmesh.ops.triangulate(bm, faces=[cap], quad_method="BEAUTY", ngon_method="EAR_CLIP")
        for f in res["faces"]:
            f.normal_update()
            if f.normal.y * want < 0:
                f.normal_flip()
    o = bm_obj(name, bm)
    delete_faces(o, lambda c, nn: c.z < BELOW + 0.5 and nn.z < -0.5)
    return o


def mound(name, L, depth, top=0.35, seed=0.0, fold=0.5, lam=3.6, step=0.8, puff=0.6):
    """A patch of duvet: a puffy top, the front rolling over and hanging down to
    the floor (z -24) in soft vertical folds that widen as they fall."""
    def height(y):
        return top + 0.25 * fbm(Vector((y * 0.2, seed, 0.0)), 2)

    def zs(h):
        return sorted({BELOW, -19.0, -14.0, -10.0, -6.5, -3.8, round(min(-1.9, h - 1.9), 3), h - 1.4, h - 0.9, h - 0.45,
                       h - 0.15, h})

    def front(y, z, h):
        roll = 1.4 * (1 - math.sqrt(max(0.0, 1 - ((z - (h - 1.4)) / 1.4) ** 2))) if z > h - 1.4 else 0.0
        hang = max(0.0, (h - 1.4 - z)) / 24.0
        ph = seed + 0.9 * fbm(Vector((y * 0.12, 0.0, seed)), 2)
        f = fold * (0.4 + 1.6 * hang) * math.sin(TAU * y / lam + ph + 0.04 * z) + \
            0.45 * hang * math.sin(TAU * y / (lam * 0.43) + seed * 2.0 + 0.8 * ph)
        flare = -0.9 * math.sin(math.pi * min(1.0, hang * 3.0)) - 2.0 * hang
        return roll + f + flare + 0.15 * fbm(Vector((y * 0.3, z * 0.2, seed)), 2)

    def back(y, z, h):
        return depth + 0.3 * math.sin(TAU * y / lam + seed)

    def top_z(u, y, h):
        return h + puff * math.sin(math.pi * u) ** 0.6 * (0.8 + 0.2 * math.sin(TAU * y / 4.4 + seed))

    o = loft(name, -L / 2, L / 2, step, height, front, back, zs, top_n=6, end=0.28, top_z=top_z,
             disp=lambda co, n: 0.05 * fbm(co * 0.8 + Vector((seed, 0, 0)), 3))
    mesh.smooth(o, angle=None)
    mat.assign(o, m_linen(name + "Linen", tint="#4c5674", quilt=1.0, bright=0.95))
    return o


def finish_piece(o, slot, every, chance, side="both", weight=2.0):
    split_long(o)
    lo, hi = mesh.bounds(o, world=False)
    origin_to(o, (lo.x, 0.0, 0.0))
    o["atlas_weight"] = weight
    return extras(o, slot, every, chance, side)


# ---------------------------------------------------------------- wall: duvet dunes

@piece
def build_side_duvet():
    L = 15.0

    def height(y):
        return 0.9 + 2.3 * (0.5 - 0.5 * math.cos(TAU * y / 7.5 + 0.35)) + 0.35 * fbm(Vector((y * 0.2, 2.0, 0.0)), 2)

    def zs(h):
        return sorted({BELOW, -19.0, -14.0, -10.0, -6.5, -3.8, -1.8, round(min(-0.4, h - 1.8), 3), h - 1.6, h - 0.9,
                       h - 0.4, h})

    def front(y, z, h):
        roll = 1.3 * (1 - math.sqrt(max(0.0, 1 - ((z - (h - 1.6)) / 1.6) ** 2))) if z > h - 1.6 else 0.0
        hang = max(0.0, (h - 1.6 - z)) / 24.0
        f = 0.55 * (0.4 + 1.3 * hang) * math.sin(TAU * y / 3.1 + 0.05 * z) + 0.35 * hang * math.sin(TAU * y / 1.45 + 1.0)
        return roll + f - 1.4 * hang + 0.15 * fbm(Vector((y * 0.3, z * 0.2, 3.0)), 2)

    def back(y, z, h):
        return 5.5 + 0.4 * math.sin(TAU * y / 3.1)

    def top_z(u, y, h):
        return h + 0.6 * math.sin(math.pi * u) ** 0.8 - 1.1 * u * u

    o = loft("side_duvet", -L / 2, L / 2, 0.5, height, front, back, zs, top_n=7, end=0.25, top_z=top_z,
             disp=lambda co, n: 0.06 * fbm(co * 0.7, 3))
    delete_faces(o, lambda c, n: c.x > 4.8 and n.x > 0.85)
    mesh.smooth(o, angle=None)
    mat.assign(o, m_linen("DuneLinen", tint="#4a5474", quilt=1.0, bright=0.95))
    return finish_piece(o, "wall", 15, 0.65, weight=3.0)


# ---------------------------------------------------------------- mid: pillow hill

@piece
def build_side_pillow():
    base = mound("pillow_mound", 20.0, 13.0, top=0.2, seed=1.0, puff=0.3)
    bm = bmesh.new()
    prism(bm, rounded_rect(-8.6, -3.0, 8.6, 3.0, 2.2, n=6), 0.0, 1.0, axis="X")
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    p = bm_obj("pillow_body", bm)
    # outline in Y-Z at x 0..1: scale into a pillow 17 x 12 x 5, lying flat
    warp(p, lambda co: Vector((1.2 + co.x * 11.0, co.y, 1.55 + co.z * 0.42)))
    remesh(p, 0.16, smooth_iter=12, smooth_factor=0.8)

    def inflate(co, n):
        u = clamp(abs(co.y) / 8.6)
        v = clamp(abs(co.x - 6.7) / 5.5)
        body = (1 - u ** 3) * (1 - v ** 3)
        crease = -0.12 * abs(math.sin(co.y * 0.55 + co.x * 0.9 + 1.5 * fbm(co * 0.15, 2))) * body * abs(n.z)
        return 1.3 * body * max(0.0, n.z) ** 0.5 * (1 if n.z > 0 else 0) + crease + 0.05 * fbm(co * 0.6, 3)
    displace(p, inflate)
    warp(p, lambda co: Matrix.Rotation(math.radians(8), 3, "Y") @ (co - Vector((1.2, 0, 0.4))) + Vector((1.2, 0, 0.4)))
    decimate_to(p, 2300)
    mesh.smooth(p, angle=None)
    mat.assign(p, m_linen("PillowLinen", tint="#8a95b4", scale=0.8, bright=1.1, stains=0.45))
    o = join([base, p], "side_pillow")
    return finish_piece(o, "mid", 42, 0.6, weight=2.0)


# ---------------------------------------------------------------- wall: a pile of socks

def sock_path(start, heading, leg=6.5, foot=5.5, lift=None, n_leg=9, n_foot=9):
    """Centre line of a lying sock: leg, heel bend, foot."""
    h = Vector(heading).normalized()
    side = Vector((-h.y, h.x, 0.0))
    pts = []
    for i in range(n_leg):
        pts.append(Vector(start) + h * (leg * i / (n_leg - 1)))
    corner = pts[-1]
    for i in range(1, 5):
        a = math.radians(90 * i / 4)
        pts.append(corner + h * (1.1 * math.sin(a)) + side * (1.1 * (1 - math.cos(a))))
    for i in range(1, n_foot):
        pts.append(pts[-1] + side * (foot / (n_foot - 1)))
    if lift:
        pts = [p + Vector((0, 0, lift(i / (len(pts) - 1)))) for i, p in enumerate(pts)]
    return pts


@piece
def build_side_socks():
    base = mound("sock_mound", 13.0, 9.0, top=0.1, seed=2.0, puff=0.4)
    parts = [base]
    specs = [((2.6, -5.4, 1.15), (0.15, 1.0, 0), "#2b2d33", "#8a8f99", None),
             ((6.6, -4.0, 1.5), (-0.1, 1.0, 0), "#d8d6d2", "#8a8f99", lambda t: 1.1 * math.sin(math.pi * min(1, t * 1.6))),
             ((1.8, 1.4, 1.3), (1.0, 0.35, 0), "#6b6f78", "#2b2d33", lambda t: 0.9 * math.sin(math.pi * t))]
    for i, (start, head, col, heel, lift) in enumerate(specs):
        pts = sock_path(start, head, lift=lift)
        n = len(pts)
        bm = bmesh.new()

        def rf(k, t, th, n=n):
            cuff = 1.0 + 0.05 * math.cos(20 * th) * (1 if t < 0.14 else 0)
            toe = math.sqrt(max(0.0, 1 - ((t - 0.86) / 0.14) ** 2)) if t > 0.86 else 1.0
            heel = 1.0 + 0.18 * math.exp(-((t - 0.52) / 0.07) ** 2)
            ell = 1.0 / math.sqrt((math.cos(th) / 0.7) ** 2 + (math.sin(th) / 1.75) ** 2)   # a lying sock, plump
            return max(0.05, cuff * heel * ell * (0.3 + 0.7 * toe))
        tube(bm, pts, 0.5, sides=14, rfun=rf, caps=True, start_normal=(0, 0, 1))
        so = bm_obj(f"sock{i}", bm)
        # heel and toe patches take the second colour (mask G)
        L = len(pts)
        heel_c, toe_c = pts[9], pts[-1]
        set_mask(so, lambda co, hc=heel_c, tc=toe_c: (0.0, 1.0 if ((co - hc).length < 1.3 or (co - tc).length < 1.1) else 0.0, 0.0))
        mesh.smooth(so, angle=None)
        mat.assign(so, m_fleece(f"SockKnit{i}", col, stripe=heel))
        parts.append(so)
    o = join(parts, "side_socks")
    return finish_piece(o, "wall", 55, 0.45, weight=3.0)


# ---------------------------------------------------------------- mid: SlopCola cans

CAN_R, CAN_H = 1.32, 6.7


def can_profile():
    R, H = CAN_R, CAN_H
    return [(0.0, 0.34), (0.55, 0.3), (0.86, 0.18), (1.04, 0.02), (1.16, 0.0), (1.27, 0.12), (1.31, 0.32),
            (R, 0.55), (R, 1.8), (R, 3.2), (R, 4.6), (R, 5.85), (1.27, 6.15), (1.12, 6.42), (1.03, 6.52),
            (1.06, 6.64), (1.02, H), (0.96, 6.66), (0.93, 6.58), (0.0, 6.56)]


def lathe(bm, prof, sides=32, cx=0.0, cy=0.0, cz=0.0):
    rings = []
    for r, z in prof:
        if r < 1e-4:
            rings.append([bm.verts.new((cx, cy, cz + z))])
        else:
            rings.append([bm.verts.new((cx + r * math.cos(TAU * k / sides), cy + r * math.sin(TAU * k / sides), cz + z))
                          for k in range(sides)])
    for a, b in zip(rings, rings[1:]):
        if len(a) == 1:
            for k in range(sides):
                bm.faces.new((a[0], b[(k + 1) % sides], b[k]))
        elif len(b) == 1:
            for k in range(sides):
                bm.faces.new((a[k], a[(k + 1) % sides], b[0]))
        else:
            quad_strip(bm, a, b)
    return rings


def wrap_text(o, R, z0, angle0=math.pi, vertical=True):
    """Bend a flat text mesh (XY, facing +Z, centred) round a cylinder of
    radius R at height z0, centred on angle0 (pi = facing -X, the track).
    Glyph faces are split first so they bend instead of sinking into the can."""
    split_long(o, 0.1, axis=1 if vertical else 0)

    def f(co):
        if vertical:   # reads upward, letter tops toward +Y (the viewer's left)
            z = z0 + co.x
            phi = angle0 - co.y / R
        else:
            z = z0 + co.y
            phi = angle0 + co.x / R
        r = R + 0.006 + co.z
        return Vector((r * math.cos(phi), r * math.sin(phi), z))
    return warp(o, f)


def slopcola(name, x, y, z, crushed=False, seed=0.0):
    red = m_paint("CanRed", "#b0161b", rough=0.28, metal=0.55, wear=0.7)
    cream = m_paint("CanCream", "#f2e8b8", rough=0.35, metal=0.3)
    alu = m_alu()
    bm = bmesh.new()
    rings = lathe(bm, can_profile(), sides=24)
    body = bm_obj(name, bm)
    mesh.clean(body)
    mat.assign(body, alu)
    mat.assign(body, red, faces=lambda p: 0.5 < p.center.z < 6.0 and math.hypot(p.center.x, p.center.y) > 1.2)
    parts = [hard(body, 50)]
    t = text_mesh(name + "_logo", "SlopCola", 1.1, extrude=0.012, offset=0.02, res=2)
    wrap_text(t, CAN_R, 3.25, vertical=True)
    mat.assign(t, cream)
    parts.append(hard(t, 60))
    if not crushed:
        t2 = text_mesh(name + "_line", "TASTE THE CONTENT", 0.2, extrude=0.006, offset=0.004, res=1)
        wrap_text(t2, CAN_R, 5.6, vertical=False)
        mat.assign(t2, cream)
        parts.append(hard(t2, 60))
    band = bmesh.new()
    lathe(band, [(CAN_R + 0.004, 0.62), (CAN_R + 0.004, 0.78)], sides=24)
    bnd = bm_obj(name + "_band", band)
    mat.assign(bnd, cream)
    parts.append(bnd)
    if not crushed:   # the pull tab, lifted
        tab = bmesh.new()
        tube(tab, [(0.15, -0.35, 6.6), (0.15, -0.95, 6.62), (-0.15, -0.95, 6.62), (-0.15, -0.35, 6.6)], 0.05, sides=4)
        tb = bm_obj(name + "_tab", tab)
        mat.assign(tb, alu)
        parts.append(tb)
    o = join(parts, name)
    if crushed:
        def crush(co):
            k = co.z / CAN_H
            a = math.atan2(co.y, co.x)
            squash = 1.0 - 0.3 * math.sin(math.pi * clamp(k * 1.1)) * (0.65 + 0.35 * math.sin(3 * a + seed))
            co.x *= squash
            co.y *= squash * 0.8
            co.z *= 0.86 + 0.03 * math.sin(5 * a) * math.sin(math.pi * k)
            return co
        warp(o, crush)
        place(o, Matrix.Translation((x, y, z)) @ Matrix.Rotation(math.radians(84), 4, "X") @ Matrix.Rotation(seed, 4, "Z"))
    else:
        place(o, Matrix.Translation((x, y, z)) @ Matrix.Rotation(math.radians(22), 4, "Z"))
    return o


@piece
def build_side_cans():
    base = mound("can_mound", 13.0, 9.0, top=0.25, seed=3.0, puff=0.35)
    c1 = slopcola("can_up", 2.7, 3.4, 0.45)
    c2 = slopcola("can_down", 4.9, 2.2, 0.45 + CAN_R * 0.8, crushed=True, seed=0.6)
    o = join([base, c1, c2], "side_cans")
    return finish_piece(o, "mid", 60, 0.5, weight=3.0)


# ---------------------------------------------------------------- mid: the alarm clock, 3:12

SEG = {"3": "abcdg", "1": "bc", "2": "abged"}


def seven_seg(bm, x0, zc, ch, h=1.45, w=0.78, t=0.17):
    """Segments of one digit on the plane x = x0 (facing -X), centred at y=0 (local u = -y)."""
    segs = {"a": (0.0, h / 2, w, t), "g": (0.0, 0.0, w, t), "d": (0.0, -h / 2, w, t),
            "b": (w / 2, h / 4, t, h / 2 - t), "c": (w / 2, -h / 4, t, h / 2 - t),
            "f": (-w / 2, h / 4, t, h / 2 - t), "e": (-w / 2, -h / 4, t, h / 2 - t)}
    quads = []
    for s in SEG[ch]:
        u, v, sw, sh = segs[s]
        quads.append((u, v, sw, sh))
    return quads


@piece
def build_side_clock():
    base = mound("clock_mound", 12.0, 9.0, top=0.2, seed=4.0, puff=0.3)
    plastic = m_plastic("ClockBody", "#1a1a1e", rough=0.35, grime=0.2)
    smoke = mat.flat("ClockGlassDark", "#040405", rough=0.08)
    red = m_glow("ClockDigits", "#ff2a1e", 6.0)
    W, D, H = 6.2, 3.0, 3.1
    z0 = 0.55
    bm = bmesh.new()
    # body: a wedge-ish rounded box, the display face tilted back 10 degrees
    prism(bm, rounded_rect(-W / 2, 0.0, W / 2, H, 0.45, n=4), 0.0, D, axis="X")
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    body = bm_obj("clock_body", bm)
    warp(body, lambda co: Vector((1.6 + co.x + 0.18 * co.z * (1 - co.x / D), co.y, z0 + co.z)))
    mesh.bevel(body, 0.08, segments=2, angle=35)
    mesh.apply_modifiers(body)
    mat.assign(body, plastic)
    parts = [hard(body, 35)]

    def on_face(u, v, off=0.0):
        """Point on the tilted display face: u along -Y (viewer's right), v up from its centre."""
        z = z0 + H * 0.5 + v
        x = 1.6 + 0.18 * (z - z0) - 0.012 - off
        return Vector((x, -u, z))

    # display window
    bm = bmesh.new()
    pw, ph = 5.1, 2.2
    vs = [bm.verts.new(on_face(u, v, 0.004)) for u, v in ((-pw / 2, -ph / 2), (pw / 2, -ph / 2), (pw / 2, ph / 2), (-pw / 2, ph / 2))]
    bm.faces.new(vs)
    win = bm_obj("clock_window", bm)
    bmesh_face_minus_x(win)
    mat.assign(win, smoke)
    parts.append(win)
    # 3:12 in red segments (a blank leading digit, like every bedside clock), colon, AM dot
    bm = bmesh.new()

    def seg_quad(u, v, sw, sh):
        bm.faces.new([bm.verts.new(on_face(u + du * sw / 2, v + dv * sh / 2, 0.012))
                      for du, dv in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
    for ch, uc in (("3", -1.55), ("1", 0.35), ("2", 1.5)):
        for u, v, sw, sh in seven_seg(bm, 0, 0, ch):
            seg_quad(uc + u, v, sw, sh)
    for v in (0.33, -0.33):
        seg_quad(-0.55, v, 0.18, 0.18)
    seg_quad(-2.3, 0.62, 0.14, 0.14)
    digits = bm_obj("clock_digits", bm)
    mesh.clean(digits, recalc_normals=False)
    bmesh_face_minus_x(digits)
    mat.assign(digits, red)
    parts.append(digits)
    # snooze bar and feet
    sn = mesh.box("snooze", (1.2, 3.6, 0.28), location=(2.9, 0, z0 + H + 0.1), bevel=0.08, segments=2)
    mat.assign(sn, plastic)
    parts.append(hard(sn))
    for y in (-2.4, 2.4):
        ft = mesh.box("foot", (2.2, 0.5, 0.3), location=(3.0, y, z0 - 0.1), bevel=0.05, segments=1)
        mat.assign(ft, plastic)
        parts.append(hard(ft))
    # its power cord, falling over the edge into the dark
    bm = bmesh.new()
    cord = [Vector((4.7, 1.8, z0 + 0.4)), Vector((5.6, 2.6, 0.5)), Vector((6.6, 3.8, 0.45)), Vector((7.4, 4.5, 0.2))]
    cord += [Vector((7.6 + 0.2 * t, 4.8 + 0.3 * t, 0.2 - 22.0 * t * t)) for t in [i / 8 for i in range(1, 9)]]
    tube(bm, cord, 0.07, sides=5, caps=True)
    cd = bm_obj("clock_cord", bm)
    mat.assign(cd, mat.flat("ClockCord", "#101012", rough=0.5))
    parts.append(cd)
    o = join([base] + parts, "side_clock")
    return finish_piece(o, "mid", 90, 0.55, weight=3.5)


# ---------------------------------------------------------------- wall: charging brick and its tangled cable

def wander(start, n, step, seed, z=0.0, spread=2.2, turn=1.2):
    import random
    rnd = random.Random(seed)
    p = Vector(start)
    a = rnd.uniform(0, TAU)
    out = [p.copy()]
    for i in range(n):
        a += rnd.uniform(-turn, turn)
        p = p + Vector((math.cos(a), math.sin(a), 0.0)) * step
        p.x = clamp(p.x, 0.6, 0.6 + spread * 2)
        out.append(Vector((p.x, p.y, z)))
    return out


@piece
def build_side_charger():
    base = mound("charger_mound", 12.0, 8.0, top=0.12, seed=5.0, puff=0.35)
    white = m_plastic("BrickWhite", "#e4e2dc", rough=0.32, grime=0.4)
    prong = m_alu("ProngMetal", "#d0d0d0", 0.25)
    cable = m_plastic("CableWhite", "#dcd9d2", rough=0.5, grime=0.45, scale=0.3)
    led = m_glow("BrickLed", "#bfe4ff", 8.0)
    ztop = 0.55
    br = mesh.box("brick", (2.0, 2.0, 1.1), location=(2.2, -2.0, ztop + 0.55), bevel=0.28, segments=4)
    br.rotation_euler = (0, 0, math.radians(18))
    mat.assign(br, white)
    parts = [hard(br, 30)]
    port = mesh.box("port", (0.1, 0.62, 0.22), location=(1.18, -2.3, ztop + 0.55), bevel=0.08, segments=2)
    port.rotation_euler = (0, 0, math.radians(18))
    mat.assign(port, mat.flat("PortDark", "#050505", rough=0.4))
    parts.append(port)
    for dy in (-0.4, 0.4):
        pr = mesh.box("prong", (0.9, 0.08, 0.32), location=(3.55, -2.0 + dy, ztop + 0.55))
        pr.rotation_euler = (0, 0, math.radians(18))
        mat.assign(pr, prong)
        parts.append(pr)
    ld = mesh.box("led", (0.04, 0.12, 0.12), location=(1.2, -1.7, ztop + 0.85))
    mat.assign(ld, led)
    parts.append(ld)
    # the cable: out of the port, a tangle on the duvet, then over the edge and down
    bm = bmesh.new()
    path = [Vector((1.0, -2.3, ztop + 0.55)), Vector((0.5, -1.6, ztop + 0.2))]
    path += wander((0.9, -0.8, ztop), 26, 0.55, seed=7, z=ztop + 0.08, spread=1.6, turn=1.3)
    for i, p in enumerate(path[2:], 2):
        p.z = ztop + 0.08 + 0.18 * math.sin(i * 1.7)   # over and under itself
    end = path[-1]
    path += [end + Vector((-0.6 * t - 0.2, 0.4 * t, -0.2 - 23.0 * t * t)) for t in [i / 9 for i in range(1, 10)]]
    tube(bm, path, 0.075, sides=6, caps=True)
    cb = bm_obj("cable", bm)
    mat.assign(cb, cable)
    parts.append(hard(cb, 80))
    # the USB-C plug at its other end, lying in the tangle
    plug = mesh.box("plug", (0.7, 0.28, 0.16), location=(3.6, 2.4, ztop + 0.12), bevel=0.06, segments=2)
    plug.rotation_euler = (0, 0, 0.7)
    mat.assign(plug, white)
    parts.append(hard(plug))
    o = join([base] + parts, "side_charger")
    return finish_piece(o, "wall", 58, 0.5, weight=4.0)


# ---------------------------------------------------------------- mid: a stack of unread books

@piece
def build_side_books():
    base = mound("book_mound", 13.0, 10.0, top=0.15, seed=6.0, puff=0.25)
    pages = m_pages()
    foil = m_paint("SpineFoil", "#d8c79a", rough=0.3, metal=0.6)
    titles = [("GO TO BED", "#233a44", 9.6, 6.6, 1.25, 0.05), ("BE PRESENT", "#5b2226", 9.0, 6.2, 1.1, -0.07),
              ("OFFLINE", "#6a5a28", 10.2, 7.0, 1.4, 0.04), ("TOUCH GRASS", "#2d3e2a", 8.6, 6.0, 1.0, 0.1),
              ("30 DAYS NO PHONE", "#3a3048", 9.4, 6.4, 1.2, -0.03), ("SLEEP", "#4a4d52", 8.2, 5.6, 0.95, 0.08)]
    parts = [base]
    z = 0.5
    for i, (title, colour, w, d, t, rot) in enumerate(titles):
        cover = m_cloth_cover(f"Cover{i}", colour)
        bk = book(f"book{i}", w, d, t, cover, pages)
        # spine title on the -X face (reads along the spine toward -Y)
        tx = text_mesh(f"title{i}", title, min(0.52 * t / 1.2, 0.5), extrude=0.006, offset=0.006, res=1)
        place(tx, Matrix.Translation((-w / 2 - 0.006, 0, t / 2)) @ FACE_TRACK)
        mat.assign(tx, foil)
        bk = join([bk, hard(tx, 60)], f"book{i}")
        place(bk, Matrix.Translation((1.2 + w / 2 + 0.4 * math.sin(i * 2.1), 0.3 * math.cos(i * 1.7), z)) @
              Matrix.Rotation(rot, 4, "Z"))
        parts.append(bk)
        z += t
    o = join(parts, "side_books")
    return finish_piece(o, "mid", 72, 0.5, weight=3.5)


# ---------------------------------------------------------------- far: the nightstand and the lamp (the sun)

@piece
def build_side_lamp():
    wood = m_wood()
    brass = m_alu("KnobBrass", "#c8a060", 0.3)
    ceramic = m_paint("LampCeramic", "#c9c3b6", rough=0.25, set_id="Plastic010", scale=2.0)
    shade_mat = m_linen("ShadeLinen", tint="#f0d2a0", scale=0.5, bright=1.2, stains=0.1)
    shade_glow = m_glow("ShadeGlow", "#ffb466", 3.2)
    bulb = m_glow("LampBulb", "#fff0d0", 12.0)
    glass = m_glass()
    parts = []
    # the nightstand stands on the floor (z -24); top at -4
    X0, W, D = 1.0, 20.0, 17.0
    body = mesh.box("stand", (D, W, 18.6), location=(X0 + D / 2, 0, BELOW + 0.9 + 9.3), bevel=0.25, segments=2)
    mat.assign(body, wood)
    parts.append(hard(body, 30))
    topb = mesh.box("top", (D + 1.2, W + 1.2, 1.1), location=(X0 + D / 2, 0, -4.55), bevel=0.35, segments=3)
    mat.assign(topb, wood)
    parts.append(hard(topb, 30))
    drawer = mesh.box("drawer", (0.5, W - 2.4, 6.0), location=(X0 - 0.1, 0, -9.0), bevel=0.2, segments=2)
    mat.assign(drawer, wood)
    parts.append(hard(drawer, 30))
    knob = mesh.cylinder("knob", 0.55, 0.9, verts=16, location=(X0 - 0.6, 0, -9.0), axis="X")
    mat.assign(knob, brass)
    parts.append(hard(knob, 40))
    for y in (-W / 2 + 1.2, W / 2 - 1.2):
        for x in (X0 + 1.2, X0 + D - 1.2):
            lg = mesh.box("leg", (1.4, 1.4, 1.6), location=(x, y, BELOW + 0.8), bevel=0.2, segments=1)
            mat.assign(lg, wood)
            parts.append(hard(lg))
    # the lamp: ceramic base, brass stem, drum shade glowing from inside
    lx, ly = X0 + 8.5, 3.0
    bm = bmesh.new()
    lathe(bm, [(0.0, 0.0), (3.2, 0.0), (3.6, 0.6), (4.2, 2.6), (4.0, 4.8), (3.1, 6.6), (1.4, 7.8), (0.7, 8.4),
               (0.55, 9.0), (0.0, 9.0)], sides=28, cx=lx, cy=ly, cz=-4.0)
    lb = bm_obj("lamp_base", bm)
    mesh.clean(lb)
    mat.assign(lb, ceramic)
    parts.append(hard(lb, 50))
    st = mesh.cylinder("stem", 0.28, 5.0, verts=12, location=(lx, ly, -4.0 + 9.0 + 2.5))
    mat.assign(st, brass)
    parts.append(hard(st, 40))
    bm = bmesh.new()
    zb, zt, rb, rt = 6.6, 14.8, 7.2, 5.6
    outer = lathe(bm, [(rb, zb), (lerp(rb, rt, 0.5), (zb + zt) / 2), (rt, zt)], sides=32, cx=lx, cy=ly)
    sh = bm_obj("shade", bm)
    mesh.clean(sh)
    for p in sh.data.polygons:
        if (p.center - Vector((lx, ly, p.center.z))).dot(p.normal) < 0:
            p.flip()
    mat.assign(sh, shade_mat)
    bm = bmesh.new()
    lathe(bm, [(rt - 0.1, zt), (lerp(rb, rt, 0.5) - 0.1, (zb + zt) / 2), (rb - 0.1, zb)], sides=32, cx=lx, cy=ly)
    shi = bm_obj("shade_in", bm)
    mesh.clean(shi)
    for p in shi.data.polygons:
        if (p.center - Vector((lx, ly, p.center.z))).dot(p.normal) > 0:
            p.flip()
    mat.assign(shi, shade_glow)
    parts += [hard(sh, 60), hard(shi, 60)]
    bb = bmesh.new()
    bmesh.ops.create_uvsphere(bb, u_segments=12, v_segments=8, radius=1.3, matrix=Matrix.Translation((lx, ly, 9.3)))
    bu = bm_obj("bulb", bb)
    mat.assign(bu, bulb)
    parts.append(bu)
    # the glass of water nobody drank
    gx, gy = X0 + 5.0, -6.2
    bm = bmesh.new()
    gprof_out = [(0.0, 0.0), (1.55, 0.0), (1.62, 0.3), (1.72, 4.9)]
    gprof_in = [(1.62, 4.9), (1.5, 0.55), (0.0, 0.5)]
    lathe(bm, gprof_out + gprof_in, sides=28, cx=gx, cy=gy, cz=-4.0)
    gl = bm_obj("glass", bm)
    mesh.clean(gl)
    bm = bmesh.new()
    lathe(bm, [(0.0, 3.35), (1.58, 3.35), (1.52, 0.56), (0.0, 0.56)], sides=28, cx=gx, cy=gy, cz=-4.0)
    wt = bm_obj("water", bm)
    mesh.clean(wt)
    g = join([gl, wt], "glass_water")
    mat.assign(g, glass)
    mesh.uv_box(g, 1.5)
    mesh.smooth(g, angle=60)
    parts.append(g)
    o = join(parts, "side_lamp")
    return finish_piece(o, "far", 120, 0.7, weight=1.2)


# ---------------------------------------------------------------- rails: a giant braided charger cable

@piece
def build_rail_bedroom():
    braid = m_braid()
    clip = m_plastic("ClipPlastic", "#e6e4de", rough=0.35, grime=0.2)
    bm = bmesh.new()
    tube(bm, [(0.0, y, 1.0) for y in (0.0, 0.25, 0.5, 0.75, 1.0)], 0.1, sides=8, caps=False)
    c = bm_obj("cable", bm)
    mat.assign(c, braid)
    post = mesh.box("post", (0.1, 0.1, 0.85), location=(0, 0.5, 0.425))
    delete_bottom(post)
    mat.assign(post, clip)
    bm = bmesh.new()
    tube(bm, [(0.125 * math.cos(a), 0.5, 1.0 + 0.125 * math.sin(a)) for a in [math.radians(v) for v in (-10, -55, -90, -125, -170)]],
         0.03, sides=4, caps=True)
    cl = bm_obj("clip", bm)
    mat.assign(cl, clip)
    o = join([c, post, cl], "rail_bedroom")
    mesh.smooth(o, angle=45)
    o["atlas_weight"] = 15.0
    return o


@piece
def build_rail_end():
    """The sloped start: a USB-C plug lying on the duvet, the cable rising to 1.0 m at y 0."""
    braid = m_braid()
    white = m_plastic("PlugWhite", "#e6e4de", rough=0.3, grime=0.25)
    steel = m_alu("PlugSteel", "#c8cad0", 0.2)
    bm = bmesh.new()
    pts = [Vector((0.0, -1.1 + 1.1 * t, 0.14 + 0.86 * t ** 0.9)) for t in [i / 5 for i in range(6)]]
    tube(bm, pts, 0.1, sides=8, caps=False)
    c = bm_obj("cable_up", bm)
    mat.assign(c, braid)
    boot = mesh.box("boot", (0.3, 0.55, 0.2), location=(0, -1.35, 0.12), bevel=0.06, segments=2)
    mat.assign(boot, white)
    shell = mesh.box("shell", (0.2, 0.3, 0.08), location=(0, -1.75, 0.1), bevel=0.035, segments=2)
    mat.assign(shell, steel)
    o = join([c, hard(boot), hard(shell)], "rail_end")
    mesh.smooth(o, angle=45)
    o["atlas_weight"] = 10.0
    return o


# ================================================================ sky: the far walls of the giant bedroom

def build_sky(path):
    """Cycles equirect from the bed (z 0 = the duvet, floor at -24, ceiling at
    +76): the far wall with a window, blinds and moonlight, posters, a shelf,
    the lamp's warm pool on the right, a crack of hallway light under the door."""
    lib.reset_scene()
    sc = bpy.context.scene
    w = bpy.data.worlds.new("RoomWorld")
    sc.world = w
    w.node_tree.nodes["Background"].inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
    w.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.0
    X0, X1, Y0, Y1, F, C = -95.0, 95.0, -70.0, 190.0, BELOW, 76.0
    paint = mat.new_material("WallPaint")
    g = G(paint)
    ob = g.coord("Object")
    wall_col = g.mixc(g.maprange(g.noise(ob, 0.04, 3), 0.3, 0.7), "#3d4452", "#4a4f5c")
    g.out(wall_col, 0.9, g.bump(g.noise(ob, 0.6, 4), 0.15, 0.2), 0.0)

    def quad(name, a, b, c, d, m):
        bm = bmesh.new()
        vs = [bm.verts.new(p) for p in (a, b, c, d)]
        bm.faces.new(vs)
        o = bm_obj(name, bm)
        o.data.materials.append(m)
        return o

    def boxo(name, size, loc, m, rot=0.0):
        o = mesh.box(name, size, location=loc)
        o.rotation_euler = (0, 0, rot)
        o.data.materials.append(m)
        return o

    # walls, floor, ceiling (inward facing)
    floor_m = mat.pbr("RoomFloor", "WoodFloor051", mapping="BOX", box_scale=40.0, value=0.5)
    quad("floor", (X0, Y0, F), (X1, Y0, F), (X1, Y1, F), (X0, Y1, F), floor_m)
    quad("ceiling", (X0, Y0, C), (X0, Y1, C), (X1, Y1, C), (X1, Y0, C), paint)
    # the far wall with a window hole: split into panels around it
    wx0, wx1, wz0, wz1 = -58.0, -14.0, 8.0, 50.0
    for a, b in (((X0, wz1), (X1, C)), ((X0, F), (X1, wz0)), ((X0, wz0), (wx0, wz1)), ((wx1, wz0), (X1, wz1))):
        quad("farwall", (a[0], Y1, a[1]), (a[0], Y1, b[1]), (b[0], Y1, b[1]), (b[0], Y1, a[1]), paint)
    quad("backwall", (X0, Y0, F), (X0, Y0, C), (X1, Y0, C), (X1, Y0, F), paint)
    quad("leftwall", (X0, Y0, F), (X0, Y1, F), (X0, Y1, C), (X0, Y0, C), paint)
    quad("rightwall", (X1, Y0, F), (X1, Y0, C), (X1, Y1, C), (X1, Y1, F), paint)
    for o in list(bpy.context.scene.objects):
        if o.type == "MESH" and o.name.startswith(("floor", "ceiling", "farwall", "backwall", "leftwall", "rightwall")):
            bm = bmesh.new()
            bm.from_mesh(o.data)
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
            bm.to_mesh(o.data)
            bm.free()
            c = sum((v.co for v in o.data.vertices), Vector()) / len(o.data.vertices)
            if o.data.polygons[0].normal.dot(Vector((0, 20, 3)) - c) < 0:
                o.data.polygons[0].flip()
    # the night outside: dark blue sky with the moon, behind the window
    night = mat.new_material("NightOutside")
    gn = G(night)
    em = gn.n("ShaderNodeEmission")
    tc = gn.coord("Object")
    zz = gn.sep(tc)[2]
    grad = gn.mixc(gn.maprange(zz, wz0, wz1), "#0b1430", "#1d2d5c")
    moon = gn.maprange(gn.vmath("DISTANCE", tc, Vector((-30.0, Y1 + 30.0, 40.0))), 4.0, 3.3)
    halo = gn.math("MULTIPLY", gn.maprange(gn.vmath("DISTANCE", tc, Vector((-30.0, Y1 + 30.0, 40.0))), 18.0, 3.3), 0.35)
    col = gn.mixc(gn.math("ADD", moon, halo), grad, "#dfe8ff")
    gn.ln(col, em.inputs["Color"])
    em.inputs["Strength"].default_value = 1.6
    outn = next(n for n in night.node_tree.nodes if n.type == "OUTPUT_MATERIAL")
    gn.ln(em.outputs[0], outn.inputs["Surface"])
    quad("outside", (wx0 - 20, Y1 + 30, wz0 - 20), (wx1 + 20, Y1 + 30, wz0 - 20), (wx1 + 20, Y1 + 30, wz1 + 20),
         (wx0 - 20, Y1 + 30, wz1 + 20), night)
    # moonlight coming in through the window (casts the blinds on the floor and the bed)
    ld = bpy.data.lights.new("moon", "AREA")
    ld.shape = "RECTANGLE"
    ld.size, ld.size_y = (wx1 - wx0) * 0.9, (wz1 - wz0) * 0.9
    ld.energy = 9.0e4
    ld.color = mat.rgb("#9fb4ff")
    lo = lib.link(bpy.data.objects.new("moon", ld))
    lo.location = ((wx0 + wx1) / 2, Y1 + 12, (wz0 + wz1) / 2 + 6)
    lo.rotation_euler = (Vector((-10.0, 40.0, -24.0)) - lo.location).to_track_quat("-Z", "Y").to_euler()
    # window frame and the blinds (slats, a little open, one hanging crooked)
    frame_m = m_paint("FrameWhite", "#b8bcc4", rough=0.5)
    slat_m = m_paint("SlatWhite", "#9aa0aa", rough=0.45, metal=0.2)
    fw = 1.6
    for (a, b) in (((wx0 - fw, wz0 - fw), (wx0, wz1 + fw)), ((wx1, wz0 - fw), (wx1 + fw, wz1 + fw)),
                   ((wx0, wz0 - fw), (wx1, wz0)), ((wx0, wz1), (wx1, wz1 + fw))):
        boxo("frame", (b[0] - a[0], 1.4, b[1] - a[1]), ((a[0] + b[0]) / 2, Y1 - 0.4, (a[1] + b[1]) / 2), frame_m)
    boxo("sill", (wx1 - wx0 + 6, 5.0, 1.2), ((wx0 + wx1) / 2, Y1 - 2.4, wz0 - 0.6), frame_m)
    z = wz1 - 0.8
    k = 0
    while z > wz0 + 1.0:
        sl = boxo("slat", (wx1 - wx0 - 1.0, 1.9, 0.18), ((wx0 + wx1) / 2, Y1 - 2.2, z), slat_m)
        tilt = math.radians(62 if k != 9 else 20)
        sl.rotation_euler = (tilt, math.radians(4) if k == 9 else 0.0, 0.0)
        z -= 1.75
        k += 1
    # posters on the right wall (abstract, invented) and a shelf on the left
    def poster(name, y, z, w_, h_, style):
        pm = mat.new_material(name)
        gp = G(pm)
        pc = gp.coord("Object")
        s = gp.sep(pc)
        if style == 0:   # a big circle
            d = gp.vmath("DISTANCE", pc, Vector((X1 - 0.3, y, z + 2)))
            c = gp.mixc(gp.maprange(d, w_ * 0.32, w_ * 0.3), "#2a1c3a", "#b04a3a")
        else:            # stripes
            c = gp.mixc(gp.math("GREATER_THAN", gp.math("SINE", gp.math("MULTIPLY", s[2], 0.5)), 0.2), "#1c2a30", "#5f8a86")
        gp.out(c, 0.4, None, 0.0)
        quad(name, (X1 - 0.3, y - w_ / 2, z - h_ / 2), (X1 - 0.3, y - w_ / 2, z + h_ / 2),
             (X1 - 0.3, y + w_ / 2, z + h_ / 2), (X1 - 0.3, y + w_ / 2, z - h_ / 2), pm)
    poster("poster_a", 60.0, 26.0, 26.0, 36.0, 0)
    poster("poster_b", 96.0, 30.0, 20.0, 28.0, 1)
    shelf_m = mat.pbr("ShelfWood", "WoodFloor051", mapping="BOX", box_scale=8.0, value=0.6)
    boxo("shelf", (7.0, 60.0, 1.2), (X0 + 3.5, 70.0, 22.0), shelf_m)
    import random
    rnd = random.Random(3)
    yy = 44.0
    while yy < 98:
        bw = rnd.uniform(1.4, 3.2)
        bh = rnd.uniform(6.0, 10.5)
        bmat = m_paint(f"ShelfBook{int(yy)}", rnd.choice(("#3a2a2a", "#2a3440", "#403a28", "#2c2c30")), rough=0.7)
        b = boxo("shelfbook", (5.2, bw, bh), (X0 + 3.2, yy, 22.6 + bh / 2), bmat, rot=rnd.uniform(-0.05, 0.05))
        if rnd.random() < 0.12:
            b.rotation_euler = (math.radians(20), 0, 0)
        yy += bw + 0.15
    pot = mesh.cylinder("pot", 3.0, 5.0, verts=20, location=(X0 + 4.0, 102.0, 25.1))
    pot.data.materials.append(m_paint("Pot", "#6a3a2a", rough=0.8))
    for i in range(9):
        lf = boxo("leaf", (0.4, 1.6, 9.0), (X0 + 4.0, 102.0, 29.0), m_paint("Leaf", "#1c2a1c", rough=0.7))
        lf.rotation_euler = (math.radians(rnd.uniform(-50, 50)), math.radians(rnd.uniform(-40, 40)), rnd.uniform(0, 3))
    # the lamp on the right, near: warm pool on the wall and ceiling
    lamp_m = m_glow("SkyLampShade", "#ffb466", 6.0)
    bm = bmesh.new()
    lathe(bm, [(7.2, 0.0), (5.6, 8.2)], sides=32, cx=70.0, cy=70.0, cz=6.0)
    sh = bm_obj("lampshade", bm)
    sh.data.materials.append(lamp_m)
    ll = bpy.data.lights.new("lamp", "POINT")
    ll.energy = 4.5e4
    ll.color = mat.rgb("#ffb070")
    ll.shadow_soft_size = 3.0
    lamp = lib.link(bpy.data.objects.new("lamp", ll))
    lamp.location = (70.0, 70.0, 9.0)
    stand_m = mat.pbr("StandWood", "WoodFloor051", mapping="BOX", box_scale=8.0, value=0.4)
    boxo("nightstand", (18.0, 20.0, 20.0), (70.0, 70.0, -14.0), stand_m)
    # the door behind, a line of hallway light under it
    door_m = m_paint("Door", "#2a2c32", rough=0.6)
    quad("door", (-20.0, Y0 + 0.3, F), (-20.0 + 38.0, Y0 + 0.3, F), (-20.0 + 38.0, Y0 + 0.3, F + 82.0),
         (-20.0, Y0 + 0.3, F + 82.0), door_m)
    hall = m_glow("HallLight", "#ffcf90", 20.0)
    quad("hallgap", (-20.0, Y0 + 0.5, F + 0.05), (18.0, Y0 + 0.5, F + 0.05), (18.0, Y0 + 0.5, F + 0.7),
         (-20.0, Y0 + 0.5, F + 0.7), hall)
    # a chair buried under clothes, left of the window
    cloth = m_linen("ChairClothes", tint="#3a3f52", scale=3.0, bright=0.9)
    for i in range(7):
        bm = bmesh.new()
        bmesh.ops.create_uvsphere(bm, u_segments=12, v_segments=8, radius=rnd.uniform(5, 9),
                                  matrix=Matrix.Translation((-72 + rnd.uniform(-6, 6), 150 + rnd.uniform(-6, 6),
                                                             -2 + rnd.uniform(-2, 8))) @ Matrix.Diagonal((1.2, 1.0, 0.55, 1)))
        heap = bm_obj("clothes", bm)
        heap.data.materials.append(cloth)
    for x_, y_ in ((-80, 142), (-64, 142), (-80, 158), (-64, 158)):
        boxo("chairleg", (1.2, 1.2, 22.0), (x_, y_, F + 11.0), stand_m)
    boxo("chairback", (18.0, 1.4, 26.0), (-72, 160, 12.0), stand_m)
    # the phone's own cold light from the bed
    pl = bpy.data.lights.new("phone", "POINT")
    pl.energy = 900.0
    pl.color = mat.rgb("#8fb0ff")
    pl.shadow_soft_size = 1.0
    ph = lib.link(bpy.data.objects.new("phone", pl))
    ph.location = (0.0, 2.0, 5.0)
    # the bed itself below the horizon (dark duvet), so the lower half reads as fabric then fog
    bed_m = m_linen("SkyDuvet", tint="#2a3044", scale=4.0, bright=0.8, quilt=0.6)
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=40, y_segments=40, size=60.0)
    bed = bm_obj("bed", bm)
    displace(bed, lambda co, n: -0.6 + 0.8 * noise.noise(co * 0.08))
    bed.data.materials.append(bed_m)
    sc.cycles.max_bounces = 4
    render_equirect(path, SKY_SAMPLES)


def feed_image(name, w=256, h=540, seed=3):
    """A stand-in for the renderer's late-night reels on the lane screens."""
    import random
    import numpy as np
    rnd = random.Random(seed)
    a = np.zeros((h, w, 4), dtype=np.float32)
    yy = np.linspace(0, 1, h)[:, None]
    a[..., 0] = 0.03 + 0.05 * yy
    a[..., 1] = 0.035 + 0.06 * yy
    a[..., 2] = 0.09 + 0.15 * yy
    a[..., 3] = 1.0
    for _ in range(5):
        x0, y0 = rnd.randint(20, 200), rnd.randint(80, 460)
        a[y0:y0 + rnd.randint(10, 22), x0:x0 + rnd.randint(40, 120), :3] = (0.55, 0.62, 0.95)
    a[40:120, 20:236, :3] = (0.15, 0.2, 0.45)
    img = bpy.data.images.new(name, w, h)
    img.pixels.foreach_set(a.ravel())
    img.pack()
    return img


# ================================================================ review, bake, export

def render_equirect(path, samples):
    sc = bpy.context.scene
    cam_d = bpy.data.cameras.new("pano")
    cam_d.type = "PANO"
    cam_d.panorama_type = "EQUIRECTANGULAR"
    cam_d.clip_end = 20000
    cam = lib.link(bpy.data.objects.new("pano", cam_d))
    cam.location = (0, 0, 4.0)
    cam.rotation_euler = (math.radians(90), 0, 0)   # forward = +Y = image centre
    sc.camera = cam
    bake.setup_cycles(samples)
    sc.cycles.use_denoising = True
    sc.render.resolution_x, sc.render.resolution_y = 2048, 1024
    sc.render.resolution_percentage = 100
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "None"
    sc.render.image_settings.file_format = "JPEG"
    sc.render.image_settings.quality = 88
    sc.render.filepath = path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bpy.ops.render.render(write_still=True)
    q = 88
    while os.path.getsize(path) > 600 * 1024 and q > 60:
        q -= 6
        sc.render.image_settings.quality = q
        bpy.ops.render.render(write_still=True)
    log(f"sky: {os.path.relpath(path, lib.ROOT)} {os.path.getsize(path) // 1024} KB (q{q})")


def fog_wrap(m, color, near, far):
    """three.js linear fog: mix the surface toward the fog colour with view distance."""
    nt = m.node_tree
    outn = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output), None)
    if outn is None or not outn.inputs["Surface"].is_linked or m.get("_fogged"):
        return
    src = outn.inputs["Surface"].links[0].from_socket
    cam = nt.nodes.new("ShaderNodeCameraData")
    mr = nt.nodes.new("ShaderNodeMapRange")
    nt.links.new(cam.outputs["View Distance"], mr.inputs["Value"])
    mr.inputs["From Min"].default_value = near
    mr.inputs["From Max"].default_value = far
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = mat.rgba(color)
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(mr.outputs["Result"], mix.inputs[0])
    nt.links.new(src, mix.inputs[1])
    nt.links.new(em.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], outn.inputs["Surface"])
    m["_fogged"] = True


def game_world(sky_path, look):
    w = bpy.data.worlds.new("GameWorld")
    nt = w.node_tree
    nt.nodes.clear()
    N, L = nt.nodes.new, nt.links.new
    tc = N("ShaderNodeTexCoord")
    mp = N("ShaderNodeMapping")
    mp.inputs["Rotation"].default_value = (0, 0, math.radians(-90))  # Blender puts +X mid-image; ours is +Y
    L(tc.outputs["Generated"], mp.inputs["Vector"])
    env = N("ShaderNodeTexEnvironment")
    if sky_path and os.path.exists(sky_path):
        env.image = bpy.data.images.load(sky_path, check_existing=True)
    L(mp.outputs[0], env.inputs["Vector"])
    sep = N("ShaderNodeSeparateXYZ")
    L(tc.outputs["Generated"], sep.inputs[0])
    below = N("ShaderNodeMapRange")
    L(sep.outputs[2], below.inputs["Value"])
    below.inputs["From Min"].default_value = 0.02
    below.inputs["From Max"].default_value = -0.25
    below.interpolation_type = "SMOOTHSTEP"
    fogmix = N("ShaderNodeMix")
    fogmix.data_type = "RGBA"
    L(below.outputs["Result"], fogmix.inputs[0])
    L(env.outputs["Color"], fogmix.inputs[6])
    fogmix.inputs[7].default_value = mat.rgba(look["fog"])
    # lighting rays: env x intensity + the hemisphere light (sky colour above, ground below) / pi
    hemi = N("ShaderNodeMix")
    hemi.data_type = "RGBA"
    hk = N("ShaderNodeMapRange")
    L(sep.outputs[2], hk.inputs["Value"])
    hk.inputs["From Min"].default_value = -1
    hk.inputs["From Max"].default_value = 1
    L(hk.outputs["Result"], hemi.inputs[0])
    hemi.inputs[6].default_value = mat.rgba(look["hemi_ground"])
    hemi.inputs[7].default_value = mat.rgba(look["hemi_sky"])
    hs = N("ShaderNodeMix")
    hs.data_type = "RGBA"
    hs.blend_type = "MULTIPLY"
    hs.inputs[0].default_value = 1.0
    L(hemi.outputs[2], hs.inputs[6])
    hs.inputs[7].default_value = (look["hemi"] / math.pi,) * 3 + (1,)
    es = N("ShaderNodeMix")
    es.data_type = "RGBA"
    es.blend_type = "MULTIPLY"
    es.inputs[0].default_value = 1.0
    L(env.outputs["Color"], es.inputs[6])
    es.inputs[7].default_value = (look["env"],) * 3 + (1,)
    add = N("ShaderNodeMix")
    add.data_type = "RGBA"
    add.blend_type = "ADD"
    add.inputs[0].default_value = 1.0
    L(es.outputs[2], add.inputs[6])
    L(hs.outputs[2], add.inputs[7])
    lp = N("ShaderNodeLightPath")
    sw = N("ShaderNodeMix")
    sw.data_type = "RGBA"
    L(lp.outputs["Is Camera Ray"], sw.inputs[0])
    L(add.outputs[2], sw.inputs[6])
    L(fogmix.outputs[2], sw.inputs[7])
    bg = N("ShaderNodeBackground")
    L(sw.outputs[2], bg.inputs["Color"])
    out = N("ShaderNodeOutputWorld")
    L(bg.outputs[0], out.inputs["Surface"])
    return w


def game_view(out_path, deck, seam, scenery, look, sky_path, extra=None, length=150.0, cam_y=-6.4, tunnel=None,
              tunnel_span=None, overhang=None, rail=None, rail_end=None, samples=48):
    """Camera 3.5 m up, 6.4 m behind the runner, looking down the track (renderer's
    chase view, 70 deg vertical fov, portrait), with scenery placed like
    src/render/biome.ts does, three.js-style linear fog and the biome light."""
    sc = bpy.context.scene
    col = lib.collection("_game")
    made = []

    def inst(src, loc, rot_z=0.0, scale=1.0):
        o = src.copy()
        o.data = src.data
        o.location = loc
        o.rotation_euler = (0, 0, rot_z)
        o.scale = (scale,) * 3
        o.hide_render = False
        col.objects.link(o)
        made.append(o)
        return o

    y0, y1 = -12.0, length + 20
    first, last = math.floor(y0 / ROW), math.ceil(y1 / ROW)
    screen_mat = mat.new_material("_screens")
    g = G(screen_mat)
    feed = feed_image("_feed")
    t = g.n("ShaderNodeTexImage")
    t.image = feed
    g.ln(g.coord("UV"), t.inputs["Vector"])
    em = g.n("ShaderNodeEmission")
    g.ln(t.outputs["Color"], em.inputs["Color"])
    em.inputs["Strength"].default_value = 0.55
    outn = next(n for n in screen_mat.node_tree.nodes if n.type == "OUTPUT_MATERIAL")
    g.ln(em.outputs[0], outn.inputs["Surface"])
    bm = bmesh.new()
    bm.loops.layers.uv.new("UVMap")
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=0.5, calc_uvs=True)
    scr = bm_obj("_screen", bm)
    scr.scale = (SCR_HW * 2, SCR_HL * 2, 1)
    mesh.apply_transform(scr)
    scr.data.materials.append(screen_mat)
    scr.hide_render = True
    for i in range(first, last + 1):
        yc = i * ROW + ROW / 2
        inst(deck, (0, yc, 0))
        if seam:
            inst(seam, (0, yc, 0))
        for lx in LANES:
            inst(scr, (lx, yc, 0.011))
    in_tunnel = (lambda s: tunnel_span[0] <= s <= tunnel_span[1]) if tunnel_span else (lambda s: False)
    slots = {"wall": (4.6, 7.0), "mid": (8.0, 20.0), "far": (20.0, 60.0)}
    for index, o in enumerate(scenery):
        every = max(2.0, float(o.get("every", 12)))
        chance = float(o.get("chance", 0.6))
        slot = slots.get(o.get("slot", "wall"), slots["wall"])
        jitter = o.get("slot", "wall") != "wall"
        side_s = o.get("side", "both")
        sides = [-1] if side_s == "left" else [1] if side_s == "right" else [-1, 1]
        for i in range(math.floor((y0 - 10) / every), math.floor(y1 / every) + 1):
            s0 = i * every
            if in_tunnel(s0):
                continue
            for side in sides:
                salt = index * 37 + side + 5
                if jhash(i, salt) >= chance:
                    continue
                s = s0 + (jhash(i, salt + 1) - 0.5) * every * 0.6
                x = side * lerp(slot[0], slot[1], jhash(i, salt + 2))
                yaw = (0 if side > 0 else math.pi) + ((jhash(i, salt + 3) - 0.5) * 0.5 if jitter else 0)
                k = 0.85 + 0.35 * jhash(i, salt + 4) if jitter else 1.0
                inst(o, (x, s, 0), yaw, k)
    if tunnel and tunnel_span:
        rows = max(1, round((tunnel_span[1] - tunnel_span[0]) / ROW))
        step = (tunnel_span[1] - tunnel_span[0]) / rows
        for i in range(rows):
            o = inst(tunnel, (0, tunnel_span[0] + (i + 0.5) * step, 0))
            o.scale = (1, step / ROW, 1)
    if overhang:
        inst(overhang, (0, 34.0, 0))
    if rail:
        for k in range(30):
            inst(rail, (2.2, 16.0 + k, 0))
        if rail_end:
            inst(rail_end, (2.2, 16.0, 0))
    for o in extra or []:
        made.append(o)
    # a stand-in runner for scale (faceless capsule with a lit phone)
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=12, v_segments=8, radius=0.3,
                              matrix=Matrix.Translation((0, 0, 1.05)) @ Matrix.Diagonal((1, 0.8, 2.1, 1)))
    bmesh.ops.create_uvsphere(bm, u_segments=12, v_segments=8, radius=0.22, matrix=Matrix.Translation((0, 0.02, 1.72)))
    runner = bm_obj("_runner", bm)
    runner.data.materials.append(mat.flat("_runner", "#2c2838", rough=0.7))
    col.objects.link(runner)
    sc.collection.objects.unlink(runner)
    made.append(runner)
    # camera
    cd = bpy.data.cameras.new("_gamecam")
    cd.sensor_fit = "VERTICAL"
    cd.angle_y = math.radians(70)
    cd.clip_start = 0.1
    cd.clip_end = 220
    cam = lib.link(bpy.data.objects.new("_gamecam", cd), col)
    cam.location = (0, cam_y, 3.5)
    cam.rotation_euler = (Vector((0, 9.0 + cam_y + 6.4, 1.1)) - cam.location).to_track_quat("-Z", "Y").to_euler()
    sc.camera = cam
    # sun: three.js DirectionalLight at (4, 10, 6) -> Blender (4, -6, 10)
    sd = bpy.data.lights.new("_sun", "SUN")
    sd.energy = look["sunI"]
    sd.color = mat.rgb(look["sun"])
    sd.angle = math.radians(2)
    sd.use_shadow = False  # the renderer has no shadow maps
    sun = lib.link(bpy.data.objects.new("_sun", sd), col)
    sun.rotation_euler = (Vector((0, 0, 0)) - Vector((4, -6, 10))).to_track_quat("-Z", "Y").to_euler()
    sc.world = game_world(sky_path, look)
    for m in bpy.data.materials:
        if m.users and m.node_tree and m.name != "_screens_x":
            fog_wrap(m, look["fog"], look["near"], look["far"])
    sc.render.engine = "BLENDER_EEVEE"
    sc.eevee.taa_render_samples = samples
    if hasattr(sc.eevee, "use_raytracing"):
        sc.eevee.use_raytracing = False
    sc.render.resolution_x, sc.render.resolution_y = 720, 1560
    sc.render.resolution_percentage = 100
    # three.js: ACESFilmicToneMapping scales by exposure / 0.6 (OutputPass, after fog and bloom)
    sc.view_settings.view_transform = "ACES 1.3"
    sc.view_settings.look = "None"
    sc.view_settings.exposure = math.log2(look["exposure"] / 0.6)
    sc.render.image_settings.file_format = "PNG"
    sc.render.filepath = out_path
    hidden = {}
    for o in sc.objects:
        if o.type == "MESH" and o.name not in col.objects:
            hidden[o] = o.hide_render
            o.hide_render = True
    bpy.ops.render.render(write_still=True)
    for o, h in hidden.items():
        o.hide_render = h
    for o in list(col.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    bpy.data.collections.remove(col)
    log(f"game view: {out_path}")


def halve_normal(res):
    """The baked normal map at half resolution (2x2 box filter): the phone can't
    resolve texel-level normal noise at these densities, and UASTC normals are the
    bulk of the glb. The albedo and ORM stay at full size."""
    import numpy as np
    src = res["normal"]
    a = bake.pixels(src)
    h, w = a.shape[0] // 2, a.shape[1] // 2
    b = a[: h * 2, : w * 2].reshape(h, 2, w, 2, 4).mean(axis=(1, 3))
    n = b[..., :3] * 2 - 1
    n /= np.maximum(np.linalg.norm(n, axis=-1, keepdims=True), 1e-6)
    b[..., :3] = n * 0.5 + 0.5
    b[..., 3] = 1.0
    img = bake.new_image(src.name + "_half", (w, h), "normal")
    bake.set_pixels(img, b)
    bake.save_png(img, src.filepath_raw.replace(".png", "_1024.png"))
    for node in res["material"].node_tree.nodes:
        if node.type == "TEX_IMAGE" and node.image == src:
            node.image = img
    res["normal"] = img
    return img


def review(out_dir, objs, zmin=-8.0, size=(640, 640), samples=24):
    """Each piece from the track side (as the runner sees it) and from the
    approach, cropped below zmin so the part you actually see fills the frame."""
    everything = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    saved = {o: o.hide_render for o in everything}
    try:
        for o in objs:
            tmp = o.copy()
            tmp.data = o.data.copy()
            bpy.context.scene.collection.objects.link(tmp)
            if mesh.bounds(o, world=False)[0].z < zmin:
                bm = bmesh.new()
                bm.from_mesh(tmp.data)
                bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], dist=1e-4,
                                       plane_co=(0, 0, zmin), plane_no=(0, 0, 1), clear_inner=True)
                bm.to_mesh(tmp.data)
                bm.free()
            for other in everything:
                other.hide_render = True
            tmp.hide_render = False
            preview.render_previews(out_dir, [tmp], views=((-1.0, -0.3, 0.22), (-0.5, -1.0, 0.3)), size=size,
                                    prefix=f"{o.name}_", samples=samples)
            me = tmp.data
            bpy.data.objects.remove(tmp)
            bpy.data.meshes.remove(me)
    finally:
        for o, h in saved.items():
            o.hide_render = h


def shrink_kept_uvs(objs, names):
    """Scale the UVs of faces on `names` materials to a speck (see main); returns the objects touched."""
    out = []
    for o in objs:
        me = o.data
        if not me.uv_layers:
            continue
        lay = me.uv_layers.active
        hit = False
        for p in me.polygons:
            m = me.materials[p.material_index] if p.material_index < len(me.materials) else None
            if m is not None and m.name in names:
                for li in p.loop_indices:
                    lay.data[li].uv = lay.data[li].uv * 0.001
                hit = True
        if hit:
            out.append(o)
    return out


def pack_atlas(objects, size=2048, margin_px=8, layer="Atlas", unwrap="keep", skip_materials=(), shape="CONCAVE",
               rotate="ANY"):
    """lib.mesh.pack_uvs_to_atlas with the island pack's shape/rotation exposed
    (the lib's CONCAVE/ANY pack leaves overlapping islands on this kit)."""
    skip = set(skip_materials)
    for o in objects:
        me = o.data
        src_name = next((l for l in me.uv_layers if l.active_render), me.uv_layers[0]).name
        if layer in me.uv_layers:
            me.uv_layers.remove(me.uv_layers[layer])
        me.uv_layers[src_name].active_render = True
        dst = me.uv_layers.new(name=layer)
        src = me.uv_layers[src_name]
        for i, d in enumerate(src.data):
            dst.data[i].uv = d.uv
        me.uv_layers[src_name].active_render = True
        o["_atlas_src"] = src_name

    def atlas_face(o, p):
        mats = o.data.materials
        m = mats[p.material_index] if p.material_index < len(mats) else None
        return (m.name if m else None) not in skip
    with mesh._EditMode(objects, layer, atlas_face):
        bpy.ops.uv.average_islands_scale()
    for o in objects:
        w = o.get("atlas_weight", 1.0)
        if w != 1.0:
            k = math.sqrt(w)
            lay = o.data.uv_layers[layer]
            for p in o.data.polygons:
                if atlas_face(o, p):
                    for li in p.loop_indices:
                        lay.data[li].uv = lay.data[li].uv * k
    probe = []
    for o in objects:
        if o.name == "side_pillow":
            for p in o.data.polygons:
                if p.center.x > 15.5 and -8 < p.center.z < -4:
                    probe.append((o, p.index, tuple(o.data.uv_layers[layer].data[p.loop_indices[0]].uv)))
                    if len(probe) > 3:
                        break
    with mesh._EditMode(objects, layer, atlas_face):
        sel = [(o.name, sum(1 for p in o.data.polygons if p.select), sum(1 for p in o.data.polygons if p.hide),
                len(o.data.polygons)) for o in objects if o.name in ("side_pillow", "side_clock")]
        bpy.ops.uv.pack_islands(udim_source="CLOSEST_UDIM", rotate=rotate != "NONE",
                                rotate_method=rotate if rotate != "NONE" else "ANY", scale=True,
                                merge_overlap=False, margin_method="FRACTION", margin=margin_px / size,
                                shape_method=shape)
    log("probe", sel, [(pi, uv0, tuple(o.data.uv_layers[layer].data[o.data.polygons[pi].loop_indices[0]].uv)) for o, pi, uv0 in probe])
    for o in objects:
        me = o.data
        src, dst = me.uv_layers[o["_atlas_src"]], me.uv_layers[layer]
        for p in me.polygons:
            if not atlas_face(o, p):
                for li in p.loop_indices:
                    dst.data[li].uv = src.data[li].uv
        me.uv_layers.active = dst
        me.uv_layers[o["_atlas_src"]].active_render = True
    return layer


def drop_degenerate(o, dist=1e-4):
    """Dissolve zero-area faces / zero-length edges (they give the island packer broken islands)."""
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bmesh.ops.dissolve_degenerate(bm, dist=dist, edges=bm.edges[:])
    dead = [f for f in bm.faces if f.calc_area() < 1e-9]
    if dead:
        bmesh.ops.delete(bm, geom=dead, context="FACES")
    bm.to_mesh(o.data)
    bm.free()
    o.data.update()
    return o


def unwrap_all(objs, angle=None):
    """Our own Smart UV Project per piece (a wider angle than the lib's: fewer,
    larger islands pack tighter and the packer stops tripping over thousands of
    slivers); the lib then packs it with unwrap="keep"."""
    for o in objs:
        drop_degenerate(o)
        me = o.data
        if "UVMap" not in me.uv_layers:
            me.uv_layers.new(name="UVMap")
        kept = me.attributes.get("uvk")
        flags = [0] * len(me.polygons)
        if kept is not None and kept.domain == "FACE":
            kept.data.foreach_get("value", flags)
        mesh.uv_smart(o, angle=angle or UV_ANGLE, margin=0.02, layer="UVMap",
                      faces=(lambda p, fl=flags: not fl[p.index]) if any(flags) else None)
        me.uv_layers["UVMap"].active_render = True
        me.uv_layers.active = me.uv_layers["UVMap"]
    return objs


def count_islands(objs):
    import bmesh as _bm
    total = 0
    for o in objs:
        b = _bm.new()
        b.from_mesh(o.data)
        uv = b.loops.layers.uv.active
        seen = set()
        for f in b.faces:
            if f.index in seen:
                continue
            total += 1
            stack = [f]
            seen.add(f.index)
            while stack:
                g = stack.pop()
                for l in g.loops:
                    for e in (l.edge,):
                        for h in e.link_faces:
                            if h.index in seen:
                                continue
                            # connected in UV if the shared edge has the same UVs on both sides
                            la = [x for x in g.loops if x.edge == e][0]
                            lb = [x for x in h.loops if x.edge == e][0]
                            ua = {tuple(round(c, 5) for c in la[uv].uv), tuple(round(c, 5) for c in la.link_loop_next[uv].uv)}
                            ub = {tuple(round(c, 5) for c in lb[uv].uv), tuple(round(c, 5) for c in lb.link_loop_next[uv].uv)}
                            if ua == ub:
                                seen.add(h.index)
                                stack.append(h)
        b.free()
    return total


def uv_area(objs, layer=None, skip=("Seam", "Glass")):
    """Fraction of the 0..1 UV square covered by atlas faces (packing efficiency)."""
    a = 0.0
    for o in objs:
        me = o.data
        lay = me.uv_layers[layer] if layer else me.uv_layers.active
        mats = [m.name if m else "" for m in me.materials]
        for p in me.polygons:
            if mats and mats[p.material_index] in skip:
                continue
            uvs = [lay.data[li].uv for li in p.loop_indices]
            for k in range(1, len(uvs) - 1):
                e1, e2 = uvs[k] - uvs[0], uvs[k + 1] - uvs[0]
                a += abs(e1.x * e2.y - e1.y * e2.x) / 2
    return a


def uv_overlaps(objs, n=1024, skip=("Seam", "Glass"), quiet=False):
    """QA: rasterise every atlas triangle; count texels claimed twice, by object
    pair (overlapping islands would bake one piece's colours onto another)."""
    import numpy as np
    owner = np.full((n, n), -1, np.int64)
    tri_obj = []
    clash = {}
    examples = []
    for oi, o in enumerate(objs):
        me = o.data
        uv = me.uv_layers.active
        me.calc_loop_triangles()
        mats = [m.name if m else "" for m in me.materials]
        for t in me.loop_triangles:
            if mats and mats[t.material_index] in skip:
                continue
            p = np.array([uv.data[li].uv[:] for li in t.loops]) * n
            x0, y0 = np.floor(p.min(0)).astype(int)
            x1, y1 = np.ceil(p.max(0)).astype(int)
            x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, n), min(y1, n)
            if x1 <= x0 or y1 <= y0:
                continue
            xs, ys = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
            (ax, ay), (bx, by), (cx, cy) = p
            d = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
            if abs(d) < 1e-9:
                continue
            l1 = ((by - cy) * (xs - cx) + (cx - bx) * (ys - cy)) / d
            l2 = ((cy - ay) * (xs - cx) + (ax - cx) * (ys - cy)) / d
            inside = (l1 > 0.02) & (l2 > 0.02) & (1 - l1 - l2 > 0.02)
            sub = owner[y0:y1, x0:x1]
            prev = sub[inside]
            for h in np.unique(prev[prev >= 0]):
                ho = tri_obj[h]
                if ho[0] == oi and ho[1] == (mats[t.material_index] if mats else "") and \
                        abs(ho[3].dot(t.normal)) > 0.98 and abs(ho[3].dot(Vector(ho[2])) - ho[3].dot(t.center)) < 0.1:
                    continue   # coplanar faces of one surface (a folded cap): same texels, same look
                if len(examples) < 6 and int((prev == h).sum()) > 3:
                    examples.append((objs[tri_obj[h][0]].name, tuple(round(c, 2) for c in tri_obj[h][2]), o.name,
                                     tuple(round(c, 2) for c in t.center), tuple(round(c, 3) for c in p.mean(0) / n)))
                a_ = f"{objs[tri_obj[h][0]].name}/{tri_obj[h][1]}"
                key = tuple(sorted((a_, f"{o.name}/{mats[t.material_index] if mats else ''}")))
                clash[key] = clash.get(key, 0) + int((prev == h).sum())
            sub[inside] = len(tri_obj)
            tri_obj.append((oi, mats[t.material_index] if mats else "", tuple(t.center), t.normal.copy()))
    worst = sorted(clash.items(), key=lambda kv: -kv[1])[:8]
    if not quiet:
        log(f"uv overlaps: {sum(clash.values())} texels ({n}px grid), atlas filled {100.0 * (owner >= 0).mean():.0f}%",
            worst)
        for e in examples:
            log("  overlap e.g.", e)
    return clash


def split_faces(o, pred, name, weight):
    """Move the faces where pred(centre, normal) holds into a new object (for a
    lower texel density in the atlas); join_back() merges them after the bake."""
    new = o.copy()
    new.data = o.data.copy()
    new.name = name
    for c in o.users_collection:
        c.objects.link(new)
    for k in ("slot", "every", "chance", "side"):
        if k in new:
            del new[k]
    new["atlas_weight"] = weight
    delete_faces(o, pred)
    delete_faces(new, lambda c, n: not pred(c, n))
    if not new.data.polygons:
        bpy.data.objects.remove(new)
        return None
    return new


def join_back(main, parts):
    parts = [p for p in parts if p is not None]
    if parts:
        mesh.join([main] + parts)
        mesh.clean(main, merge=1e-4, recalc_normals=False)
    return main


def texel_density(o):
    """Atlas px per metre (sqrt of UV area x size^2 / surface area)."""
    me = o.data
    lay = me.uv_layers.active
    if lay is None:
        return 0.0
    uv_area = 0.0
    area = 0.0
    names = [m.name if m else "" for m in me.materials]
    for p in me.polygons:
        if names and names[p.material_index] in ("Seam", "Glass"):
            continue
        uvs = [lay.data[li].uv for li in p.loop_indices]
        a = 0.0
        for k in range(1, len(uvs) - 1):
            e1, e2 = uvs[k] - uvs[0], uvs[k + 1] - uvs[0]
            a += abs(e1.x * e2.y - e1.y * e2.x) / 2
        uv_area += a
        area += p.area
    return math.sqrt(uv_area * SIZE * SIZE / area) if area else 0.0



def main():
    if not NO_SKY or SKY_ONLY:
        build_sky(SKY_OUT)
        if SKY_ONLY:
            return
    lib.reset_scene()
    names = list(PIECES)
    todo = [n for n in names if not ONLY or n in ONLY]
    objs = {}
    for name in todo:
        log(f"building {name}")
        objs[name] = PIECES[name]()
    pieces = list(objs.values())

    tris = {n: mesh.tri_count(o) for n, o in objs.items()}
    for n, o in objs.items():
        lo, hi = mesh.bounds(o, world=False)
        seg = max_span(o) if hi.y - lo.y > 2 else 0.0
        ex = {k: o[k] for k in ("slot", "every", "chance", "side") if k in o}
        log(f"  {n:18s} {tris[n]:6d} tris  y {lo.y:6.2f}..{hi.y:6.2f}  x {lo.x:6.2f}..{hi.x:6.2f}  "
            f"z {lo.z:6.2f}..{hi.z:6.2f}  max-y-edge {seg:.2f}  {ex}")
    visible = sum(200.0 / o["every"] * (2 if o.get("side", "both") == "both" else 1) * o["chance"] * tris[n]
                  for n, o in objs.items() if n.startswith("side_"))
    log(f"unique tris {sum(tris.values())}, visible scenery estimate {visible:.0f}")

    scenery = [objs[n] for n in names if n.startswith("side_") and n in objs]
    if FAST:
        if PREVIEW:
            os.makedirs(PREVIEW, exist_ok=True)
            review(PREVIEW, [o for n, o in objs.items() if n != "deck_seam"], samples=16)
            if "deck" in objs:
                game_view(os.path.join(PREVIEW, "game_src.png"), objs["deck"], objs.get("deck_seam"), scenery, LOOK,
                          SKY_OUT, overhang=objs.get("overhang"), rail=objs.get("rail_bedroom"),
                          rail_end=objs.get("rail_end"), samples=16)
        return

    # one atlas for everything but the seams and the glass; hidden parts get few texels
    splits = {}
    for n, o in objs.items():
        if n.startswith("side_") and not lib.flag("no-low"):
            w = o.get("atlas_weight", 1.0)
            splits[n] = [split_faces(o, lambda c, nn: c.z < -6.0, n + "_low", w * LOW_W)]
        elif n == "deck":
            splits[n] = [split_faces(o, lambda c, nn: c.z < -0.3, n + "_under", 5.0)]
        elif n == "tunnel":
            outer = lambda c, nn: abs(nn.y) > 0.9 or (c.x * nn.x + (c.z - 4.0) * nn.z) > 0.0  # noqa: E731
            splits[n] = [split_faces(o, outer, n + "_outside", 0.6)]
    atlas_objs = [o for n, o in objs.items() if n != "deck_seam"] + [p for v in splits.values() for p in v if p]
    # the glass keeps its own UVs out of the atlas; left full size they upset the island packer (islands of
    # other pieces end up overlapping), so they shrink to a speck here and get their box UVs back after the bake
    glassy = shrink_kept_uvs(atlas_objs, ("Glass",))
    if lib.flag("pack-test"):
        for o in atlas_objs:
            mesh.apply_modifiers(o, only=[m.name for m in o.modifiers if m.type != "ARMATURE"])
        unwrap_all(atlas_objs)
        log("raw unwrap, per object:")
        for o in atlas_objs:
            c = uv_overlaps([o], quiet=True)
            if sum(c.values()):
                log("   ", o.name, sum(c.values()), sorted(c.items(), key=lambda kv: -kv[1])[:3])
        import numpy as np
        for o in atlas_objs:
            lay = o.data.uv_layers["UVMap"]
            a = np.empty(len(lay.data) * 2, np.float32)
            lay.data.foreach_get("uv", a)
            bad = int((~np.isfinite(a)).sum())
            zero = sum(1 for p in o.data.polygons if p.area < 1e-8)
            big = float(np.abs(a[np.isfinite(a)]).max()) if a.size else 0.0
            if bad or zero or big > 50:
                log("  uv check", o.name, "non-finite", bad, "zero-area faces", zero, "max |uv|", round(big, 1))
        log(f"islands: {count_islands(atlas_objs)}", sorted(((count_islands([o]), o.name) for o in atlas_objs), reverse=True)[:6],
            "uv layers", sorted({l.name for o in atlas_objs for l in o.data.uv_layers}))
        pack_atlas(atlas_objs, size=SIZE, margin_px=MARGIN, layer="Atlas", unwrap="keep",
                   shape=lib.arg("shape", "CONCAVE"), rotate=lib.arg("rotate", "ANY"),
                               skip_materials=("Seam", "Glass"))
        uv_overlaps(atlas_objs)
        log(f"atlas coverage {100 * uv_area(atlas_objs):.0f}%")
        import numpy as np
        for o in atlas_objs:
            lay = o.data.uv_layers["Atlas"]
            a = np.empty(len(lay.data) * 2, np.float32)
            lay.data.foreach_get("uv", a)
            a = a.reshape(-1, 2)
            if a.size and (a.min() < -0.001 or a.max() > 1.001):
                log("  out of tile", o.name, a.min(0).round(3), a.max(0).round(3))
        return
    unwrap_all(atlas_objs)
    log(f"islands: {count_islands(atlas_objs)}")
    res = bake.bake_kit_atlas(atlas_objs, SIZE, TEX_DIR, unwrap="keep", margin_px=MARGIN, name="BedroomKit", keep_materials=("Seam", "Glass"),
                              ao_samples=48, ao_distance=1.2, samples=6)
    uv_overlaps(atlas_objs)
    for n, o in objs.items():
        if n != "deck_seam":
            log(f"  {n:18s} {texel_density(o):6.1f} px/m" + (
                f"  (low part {texel_density(splits[n][0]):.1f})" if splits.get(n) and splits[n][0] else ""))
    for n, parts in splits.items():
        join_back(objs[n], parts)
    halve_normal(res)
    for o in glassy:
        mesh.uv_box(o, 1.5, material="Glass")
    log("atlas", res["paths"], "emissive strength", round(res["emissive_strength"], 2))
    for o in pieces:
        for a in list(o.data.color_attributes):
            o.data.color_attributes.remove(a)
    path = export.export_glb(OUT, pieces)
    export.compress(path, max_texture=SIZE)
    log(f"glb {os.path.getsize(path) // 1024} KB")
    if PREVIEW:
        os.makedirs(PREVIEW, exist_ok=True)
        review(PREVIEW, [o for n, o in objs.items() if n != "deck_seam"])
        game_view(os.path.join(PREVIEW, "game.png"), objs["deck"], objs.get("deck_seam"), scenery, LOOK, SKY_OUT,
                  overhang=objs.get("overhang"), rail=objs.get("rail_bedroom"), rail_end=objs.get("rail_end"))
        game_view(os.path.join(PREVIEW, "game_tunnel.png"), objs["deck"], objs.get("deck_seam"), scenery, LOOK,
                  SKY_OUT, tunnel=objs.get("tunnel"), tunnel_span=(14.0, 120.0))
        game_view(os.path.join(PREVIEW, "game_inside.png"), objs["deck"], objs.get("deck_seam"), scenery, LOOK,
                  SKY_OUT, tunnel=objs.get("tunnel"), tunnel_span=(-30.0, 90.0))


main()
