# Group Chat Canyon (biome 1): the group chat as geology. A dusk desert, warm
# amber light, long shadows: carved sandstone slabs frame the lane screens,
# mesas and hoodoos stand in the haze, the rocks are shaped like chat bubbles
# and "..." typing dots, the road signs say "Seen 3:12 am", the cacti are
# double ticks. Contract: docs/assets-v2.md ("Biome kits").
#
#   blender -b -P assets/blender/kits/canyon.py -- [--preview <dir>] [--fast] [--no-sky] [--sky-only]
#                                                  [--only side_mesa,deck] [--tex <dir>] [--size 2048]
#
# Writes public/assets/kits/canyon.glb and canyon-sky.jpg. --fast skips the sky,
# the bake and the export and previews the procedural source materials (with
# --only, just those pieces). Baked textures go to --tex (default
# tools/cache/kits/canyon, gitignored).

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


BIOME = "canyon"
OUT = lib.arg("out", os.path.join(lib.PUBLIC, "kits", f"{BIOME}.glb"))
SKY_OUT = os.path.join(os.path.dirname(os.path.abspath(OUT)), f"{BIOME}-sky.jpg")
PREVIEW = lib.arg("preview")
SIZE = lib.arg("size", 2048, int)
FAST = lib.flag("fast")
NO_SKY = lib.flag("no-sky") or FAST
SKY_ONLY = lib.flag("sky-only")
ONLY = [s for s in (lib.arg("only") or "").split(",") if s]
TEX_DIR = lib.arg("tex", os.path.join(lib.TOOLS, "cache", "kits", BIOME))
MARGIN = lib.arg("margin", 8, int)   # atlas island margin (px)
UV_ANGLE = lib.arg("uv-angle", 80.0, float)   # our own smart-UV angle (fewer, larger islands than the lib's 66)
SKY_SAMPLES = lib.arg("sky-samples", 96, int)

# The look proposed for src/config/content.json zones[1].look (the game view uses it).
LOOK = dict(fog="#1c0b06", near=40, far=160, sun="#ffb27a", sunI=1.8, hemi=0.8, hemi_sky="#ffb070",
            hemi_ground="#150a24", exposure=1.0, env=0.8)

# ---------------------------------------------------------------- track constants (contract)
LANES = (-2.2, 0.0, 2.2)
SCR_HW, SCR_HL = 0.96, 2.03       # half size of a lane screen (1.92 x 4.06)
ROW = 4.4                          # one deck row along Y
HALF_W = 4.8                       # deck half width
SEAMS = (-3.3, -1.1, 1.1, 3.3)
BELOW = -24.0                      # scenery reaches down to here
TAU = math.tau


# ================================================================ helpers (shared shape with bedroom.py)

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


def finish(o, loops=1.0, sharp=None, weighted=False):
    """Bend loops along Y, then shading (smooth with optional sharp angle)."""
    lo, hi = mesh.bounds(o, world=False)
    if loops and hi.y - lo.y > loops:
        mesh.subdivide_along(o, "Y", loops)
    if weighted:
        mesh.weighted_normals(o, apply=True)
    else:
        mesh.smooth(o, angle=sharp)
    return o


def join(objs, name):
    for o in objs:
        mesh.apply_transform(o)
    o = mesh.join(objs, name)
    mesh.apply_transform(o)
    return o


def text_mesh(name, body, size, extrude=0.01, offset=0.0, align="CENTER", spacing=1.0):
    """Blender text -> mesh, lying in XY (reading +X, facing +Z), centred."""
    cu = bpy.data.curves.new(name, "FONT")
    cu.body = body
    cu.size = size
    cu.extrude = 0.0   # flat glyphs: the walls cost islands and triangles nobody sees
    cu.offset = offset
    cu.align_x = align
    cu.align_y = "CENTER"
    cu.space_character = spacing
    cu.resolution_u = 3
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


# Text on a face looking at the track: reading along -Y, facing -X, up +Z.
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


# ---------------------------------------------------------------- node graph helper

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


# ================================================================ materials

def m_sandstone(name, tint="#d9a877", scale=2.6, strata=0.75, band_scale=0.16, varnish=0.55, rock=0.4,
                normal=1.0, stops=None, rough=0.9, seed=0.0, flow=0.0, bright=1.0, sand=0.7):
    """Layered desert sandstone: CC0 sandstone_cracks + Rock051 box-mapped, strata
    bands by height (warped), desert-varnish streaks down vertical faces, worn
    edges. flow > 0: Antelope-style flowing laminations (slot canyon)."""
    m = mat.new_material(name)
    g = G(m)
    ob = g.coord("Object")
    v1 = g.mapping(ob, scale, loc=(seed, seed * 0.7, 0))
    v2 = g.mapping(ob, scale * 1.9, rot=(0.4, 0.3, 0.9))
    ss = g.tex("sandstone_cracks", v1)
    rk = g.tex("Rock051", v2)
    patches = g.maprange(g.noise(ob, 0.09, 3, distortion=0.4), 0.45, 0.62)
    pm = g.math("MULTIPLY", patches, rock)
    col = g.mixc(pm, ss["color"], g.hsv(rk["color"], s=0.9, v=1.1))
    col = g.mixc(1.0, col, tint, blend="MULTIPLY")
    col = g.hsv(col, s=0.72, v=1.05 * bright)
    # strata: bands along Z, warped by low-frequency noise
    wobble = g.math("MULTIPLY", g.math("SUBTRACT", g.noise(ob, 0.035, 2), 0.5), 5.0 + 6.0 * flow)
    zc = g.sep(ob)
    zv = g.comb(zc[0], zc[1], g.math("ADD", zc[2], wobble))
    band = g.wave(zv, band_scale, distortion=2.0 + 8.0 * flow, detail=3.0, direction="Z")
    band2 = g.wave(zv, band_scale * 3.7, distortion=1.5, detail=2.0, direction="Z", phase=1.3)
    b = g.math("ADD", g.math("MULTIPLY", band, 0.82), g.math("MULTIPLY", band2, 0.18))
    stops = stops or [(0.0, "#6a3a26"), (0.22, "#a8583a"), (0.4, "#d98c55"), (0.55, "#f0c08a"), (0.7, "#c46b3f"),
                      (0.85, "#8a4630"), (1.0, "#e3aa78")]
    strata_col = g.ramp(b, stops)
    col = g.mixc(g.math("MULTIPLY", strata, 0.75), col, g.mixc(1.0, col, strata_col, blend="MULTIPLY"))
    col = g.hsv(col, v=1.0 + 0.25 * strata)
    # desert varnish: dark streaks running down steep faces
    streak_v = g.mapping(ob, (2.2, 2.2, 28.0), loc=(seed * 3, 0, 0))
    streak = g.maprange(g.noise(streak_v, 1.0, 4, 0.6), 0.5, 0.72)
    steep = g.maprange(g.math("ABSOLUTE", g.sep(g.geo("Normal"))[2]), 0.6, 0.2)
    vm = g.math("MULTIPLY", g.math("MULTIPLY", streak, steep), varnish)
    col = g.mixc(vm, col, g.hsv(col, s=0.7, v=0.32))
    col = edge_wear(g, col)
    # normal: texture + strata ledges + fine grain
    n = g.normalmap(ss["normal"], normal)
    n = g.bump(g.math("ADD", band, g.math("MULTIPLY", g.noise(ob, 3.0, 3), 0.25)), 0.22 + 0.2 * flow, 0.05, n)
    r = g.math("MULTIPLY_ADD", ss["rough"], 0.25, rough - 0.12, clamp=True)
    r = g.mixf(vm, r, 0.55)
    if sand > 0:
        # wind-blown sand settles on ledges and tops
        up = g.maprange(g.sep(g.geo("Normal"))[2], 0.62, 0.9)
        patchy = g.maprange(g.noise(ob, 0.7, 4, distortion=0.3), 0.3, 0.55)
        sm = g.math("MULTIPLY", g.math("MULTIPLY", up, patchy), sand)
        sd = g.tex("dense_sand", g.mapping(ob, 1.2))
        scol = g.hsv(g.mixc(1.0, sd["color"], "#e6ae7a", blend="MULTIPLY"), s=0.85, v=1.2 * bright)
        col = g.mixc(sm, col, scol)
        r = g.mixf(sm, r, 0.95)
        n = g.mixv(sm, n, g.normalmap(sd["normal"], 0.7))
    return g.out(col, r, n, 0.0, ao=ss.get("ao"))


def m_deck(name="CanyonDeck"):
    """Deck slabs: carved lips (fine, lighter, smoother) between rough slab margins
    with joints, sand drifts and a rocky underside, split by the 'mask' attribute
    (R sand, G carved, B underside)."""
    m = mat.new_material(name)
    g = G(m)
    ob = g.coord("Object")
    mask = g.rgb_split(g.attr("mask"))
    sand_m, carve_m, under_m = mask[0], mask[1], mask[2]
    v1 = g.mapping(ob, 2.2, loc=(0.3, 0.1, 0))
    v2 = g.mapping(ob, 1.1, rot=(0, 0, 0.6))
    vs = g.mapping(ob, 0.9)
    ss = g.tex("sandstone_cracks", v1)
    fine = g.tex("sandstone_cracks", v2)
    rk = g.tex("Rock051", g.mapping(ob, 1.8))
    sd = g.tex("dense_sand", vs)
    # slab margins: sandstone with strata tint and joints
    slab = g.mixc(1.0, ss["color"], "#e2a878", blend="MULTIPLY")
    slab = g.hsv(slab, s=0.85, v=1.25)
    tone = g.noise(ob, 0.6, 3)
    slab = g.mixc(g.maprange(tone, 0.35, 0.7), g.hsv(slab, v=0.78), g.hsv(slab, s=0.85, v=1.12))
    xyz = g.sep(ob)
    # joints between slabs: across at y = -1.25 / 0.95, along at |x| = 4.1 (margins only)
    ya = g.math("ABSOLUTE", g.math("SUBTRACT", xyz[1], -1.25))
    yb = g.math("ABSOLUTE", g.math("SUBTRACT", xyz[1], 0.95))
    xa = g.math("ABSOLUTE", g.math("SUBTRACT", g.math("ABSOLUTE", xyz[0]), 4.1))
    jy = g.math("MINIMUM", ya, yb)
    jwob = g.math("MULTIPLY", g.noise(ob, 4.0, 2), 0.012)
    joint = g.maprange(g.math("ADD", g.math("MINIMUM", jy, xa), jwob), 0.022, 0.006)
    joint = g.math("MULTIPLY", joint, g.math("SUBTRACT", 1.0, carve_m))
    slab = g.mixc(g.math("MULTIPLY", joint, 0.8), slab, g.hsv(slab, v=0.25))
    # carved lips: finer grain, paler, polished by feet
    lip = g.mixc(1.0, fine["color"], "#f0c9a0", blend="MULTIPLY")
    lip = g.hsv(lip, s=0.75, v=1.35)
    col = g.mixc(carve_m, slab, lip)
    # underside rock
    und = g.hsv(g.mixc(1.0, rk["color"], "#a0674a", blend="MULTIPLY"), v=0.9)
    col = g.mixc(under_m, col, und)
    col = edge_wear(g, col, 0.3, 0.45)
    # sand drifts with ripples, soft edge by noise
    rip = g.wave(g.mapping(ob, 1.0, rot=(0, 0, 0.25)), 2.4, distortion=1.2, detail=1.0, direction="X")
    sandcol = g.mixc(1.0, sd["color"], "#f1be86", blend="MULTIPLY")
    sandcol = g.hsv(sandcol, s=0.85, v=1.3)
    sandcol = g.mixc(g.math("MULTIPLY", rip, 0.25), sandcol, g.hsv(sandcol, v=1.25))
    sedge = g.maprange(g.math("ADD", sand_m, g.math("MULTIPLY", g.math("SUBTRACT", g.noise(ob, 5.0, 3), 0.5), 0.6)),
                       0.35, 0.6)
    col = g.mixc(sedge, col, sandcol)
    # normals
    n_slab = g.normalmap(ss["normal"], 1.2)
    n_lip = g.normalmap(fine["normal"], 0.5)
    n_sand = g.normalmap(sd["normal"], 0.8)
    nrm = g.mixv(carve_m, n_slab, n_lip)
    nrm = g.mixv(sedge, nrm, n_sand)
    nrm = g.bump(g.math("ADD", g.math("MULTIPLY", joint, -1.0), g.math("MULTIPLY", g.math("MULTIPLY", rip, sedge), 0.4)),
                 0.35, 0.02, nrm)
    r = g.math("MULTIPLY_ADD", ss["rough"], 0.2, 0.74, clamp=True)
    r = g.mixf(carve_m, r, 0.58)
    r = g.mixf(sedge, r, 0.93)
    return g.out(col, r, nrm, 0.0)


def m_sand(name="CanyonSand"):
    m = mat.new_material(name)
    g = G(m)
    ob = g.coord("Object")
    sd = g.tex("dense_sand", g.mapping(ob, 1.4))
    rip = g.wave(g.mapping(ob, 1.0, rot=(0, 0, 0.4)), 1.3, distortion=1.5, detail=1.0, direction="X")
    col = g.hsv(g.mixc(1.0, sd["color"], "#eab07a", blend="MULTIPLY"), s=0.9, v=1.55)
    col = g.mixc(g.math("MULTIPLY", rip, 0.2), col, g.hsv(col, v=1.3))
    n = g.bump(rip, 0.3, 0.05, g.normalmap(sd["normal"], 0.8))
    return g.out(col, 0.94, n, 0.0)


def m_wood(name="CanyonWood", tint="#b8a48e", scale=1.2):
    m = mat.new_material(name)
    g = G(m)
    ob = g.coord("Object")
    # the plank texture's grain runs along V: map it along Z for poles
    wd = g.tex("weathered_planks", g.mapping(ob, (scale * 0.35, scale * 0.35, scale), rot=(0, 0, 0)))
    col = g.hsv(g.mixc(1.0, wd["color"], tint, blend="MULTIPLY"), s=0.55, v=1.35)
    col = edge_wear(g, col, 0.3, 0.3)
    return g.out(col, g.math("MULTIPLY_ADD", wd["rough"], 0.2, 0.72, clamp=True), g.normalmap(wd["normal"], 1.2), 0.0)


def m_sign_green(name="SignGreen"):
    """Highway-sign green paint, chipped, sun-bleached, a little rust."""
    m = mat.new_material(name)
    g = G(m)
    ob = g.coord("Object")
    pm = g.tex("PaintedMetal006", g.mapping(ob, 1.6))
    base = g.mixc(1.0, g.hsv(pm["color"], s=0.0, v=1.6), "#0f5a3a", blend="MULTIPLY")
    fade = g.maprange(g.noise(ob, 0.5, 3), 0.3, 0.75)
    base = g.mixc(g.math("MULTIPLY", fade, 0.45), base, "#5f8a6c")
    rust = g.maprange(g.noise(ob, 2.2, 5, 0.7), 0.64, 0.74)
    base = g.mixc(rust, base, "#6b3a22")
    return g.out(base, g.mixf(rust, 0.42, 0.85), g.normalmap(pm["normal"], 0.6), 0.0)


def m_paint(name, color, rough=0.45, grime=0.35, set_id="PaintedMetal006", scale=1.4):
    """Reflective sign paint (white letters, borders) with grime and chips."""
    m = mat.new_material(name)
    g = G(m)
    ob = g.coord("Object")
    pm = g.tex(set_id, g.mapping(ob, scale))
    dirt = g.maprange(g.noise(ob, 1.2, 4), 0.45, 0.8)
    col = g.mixc(g.math("MULTIPLY", dirt, grime), color, "#6d5540")
    return g.out(col, rough, g.normalmap(pm["normal"], 0.3), 0.0)


def m_metal(name="CanyonMetal", tint="#8a8a88", rough_add=0.0):
    m = mat.new_material(name)
    g = G(m)
    ob = g.coord("Object")
    t = g.tex("Metal009", g.mapping(ob, 0.8))
    col = g.mixc(1.0, t["color"], tint, blend="MULTIPLY")
    rust = g.maprange(g.noise(ob, 3.0, 5, 0.7), 0.6, 0.72)
    col = g.mixc(rust, col, "#5a3320")
    return g.out(col, g.math("ADD", g.mixf(rust, 0.45, 0.9), rough_add, clamp=True), g.normalmap(t["normal"], 0.5),
                 g.mixf(rust, 0.9, 0.1))


def m_rubber(name="CanyonCable", color="#1a1714"):
    m = mat.new_material(name)
    g = G(m)
    ob = g.coord("Object")
    t = g.tex("Rubber004", g.mapping(ob, 0.5))
    dust = g.maprange(g.sep(g.geo("Normal"))[2], 0.2, 0.9)
    col = g.mixc(g.math("MULTIPLY", dust, 0.45), color, "#8a6446")
    return g.out(col, 0.62, g.normalmap(t["normal"], 0.4), 0.0)


def m_plastic(name="EarbudPlastic", color="#e8e4dc"):
    m = mat.new_material(name)
    g = G(m)
    ob = g.coord("Object")
    t = g.tex("Plastic010", g.mapping(ob, 0.4))
    dirt = g.maprange(g.noise(ob, 3.0, 4), 0.45, 0.75)
    col = g.mixc(g.math("MULTIPLY", dirt, 0.55), color, "#8d6a4a")
    return g.out(col, g.mixf(dirt, 0.3, 0.7), g.normalmap(t["normal"], 0.3), 0.0)


def m_cactus(name="Saguaro"):
    """Waxy grey-green saguaro skin: darker rib grooves, pale spine dots on the ribs."""
    m = mat.new_material(name)
    g = G(m)
    ob = g.coord("Object")
    rk = g.tex("Rock051", g.mapping(ob, 1.5))
    base = g.mixc(1.0, g.hsv(rk["color"], s=0.0, v=1.4), "#5e7446", blend="MULTIPLY")
    tone = g.maprange(g.noise(ob, 0.4, 3), 0.3, 0.7)
    base = g.mixc(tone, g.hsv(base, v=0.75), g.hsv(base, h=0.46, v=1.1))
    # rib grooves are cavities: darker (pointiness)
    base = edge_wear(g, base, 0.35, 0.6)
    # spines: tiny pale dots in clusters (areoles)
    dots = g.maprange(g.voronoi(g.mapping(ob, 0.09), 1.0), 0.16, 0.08)
    base = g.mixc(g.math("MULTIPLY", dots, 0.85), base, "#e8dcc0")
    # vertical scarring toward the base
    zc = g.sep(ob)[2]
    scar = g.math("MULTIPLY", g.maprange(zc, 2.5, 0.0), g.maprange(g.noise(g.mapping(ob, (0.5, 0.5, 3.0)), 1.0, 4), 0.45, 0.65))
    base = g.mixc(g.math("MULTIPLY", scar, 0.8), base, "#8a7a5e")
    n = g.bump(dots, 0.4, 0.02, g.normalmap(rk["normal"], 0.3))
    return g.out(base, g.mixf(dots, 0.5, 0.8), n, 0.0)


def m_glass_insulator(name="Insulator"):
    return mat.flat(name, "#3f7f76", rough=0.12, metal=0.0, **{"Coat Weight": 0.6})


def m_glow(name="CanyonGlow", color="#ff9a2e", strength=5.0):
    """Amber inlays (baked into the atlas emissive map)."""
    return mat.flat(name, "#3a2008", rough=0.3, emission=color, strength=strength)


def m_seam():
    return mat.flat("Seam", "#ff9a2e", rough=0.3, emission="#ff9a2e", strength=4.0)


# ================================================================ pieces

PIECES = {}


def piece(fn):
    PIECES[fn.__name__.replace("build_", "", 1)] = fn
    return fn


# ---------------------------------------------------------------- deck

DECK_XS_HALF = [0.96, 0.985, 1.07, 1.075, 1.125, 1.13, 1.215, 1.24,
                3.16, 3.185, 3.27, 3.275, 3.325, 3.33, 3.62, 3.92, 4.22, 4.46, 4.63, 4.73, 4.8]


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


def sand_height(x, y):
    ax = abs(x)
    if ax < 3.34 or ax > 4.5:
        return 0.0
    ph = 1.3 if x > 0 else 4.1
    a = 0.03 + 0.09 * (0.5 + 0.5 * math.sin(TAU * y / ROW + ph)) + 0.03 * pnoise(x, y, scale=0.9, seed=7)
    f = clamp(1 - (ax - 3.36) / 1.12) ** 1.6
    return max(0.0, a * f)


def edge_jitter(x, y):
    ax = abs(x)
    if ax < 4.6:
        return x
    k = smoothstep(4.6, 4.8, ax)
    return x + math.copysign(0.09 * pnoise(3.0 * math.copysign(1, x), y, scale=1.3, seed=2) * k, x)


def deck_top_z(x, y):
    ax = abs(x)
    d = opening_dist(x, y)
    if d <= 1e-4:
        return -0.02
    if d <= 0.0251:
        return 0.045
    for s in SEAMS:
        if abs(x - s) < 0.0251:
            return 0.015
    wear = 0.004 * pnoise(x, y, scale=3.0, seed=1)
    if ax <= 3.335:
        return 0.05 + wear
    z = 0.044 + 0.012 * pnoise(x, y, scale=0.8, seed=3) + wear + sand_height(x, y)
    if ax >= 4.62:
        z = lerp(z, -0.1, smoothstep(4.62, 4.8, ax) ** 0.8)
    return z


@piece
def build_deck():
    xs = sorted({-x for x in DECK_XS_HALF} | set(DECK_XS_HALF))
    ys = deck_ys()
    bm = bmesh.new()

    def keep(cx, cy):
        return opening_dist(cx, cy) > 0

    top = heightfield(bm, xs, ys, deck_top_z, keep, xf=edge_jitter)
    # the rocky underside (hangs down <= 1.3 m) and the slab sides
    xu = [-4.8, -4.0, -2.8, -1.4, 0.0, 1.4, 2.8, 4.0, 4.8]

    def under_z(x, y):
        k = 1 - (abs(x) / 4.8) ** 2
        return -0.42 - 0.75 * k + 0.2 * pnoise(x, y, scale=0.6, seed=5) * (0.3 + k)

    under = heightfield(bm, xu, ys, under_z, flip=True, xf=edge_jitter)
    for j in range(len(ys) - 1):
        for side, ti, ui in ((-1, 0, 0), (1, -1, -1)):
            a, b = top[j][ti], top[j + 1][ti]
            c, d = under[j + 1][ui], under[j][ui]
            q = (a, d, c, b) if side > 0 else (a, b, c, d)
            bm.faces.new(q)
    o = bm_obj("deck", bm)
    mesh.clean(o, recalc_normals=False)

    def mask(co):
        ax = abs(co.x)
        sand = smoothstep(0.004, 0.03, sand_height(co.x, co.y)) if co.z > 0 else 0.0
        carve = 1.0 if ax < 3.34 and co.z > -0.05 else 0.0
        under = 1.0 if co.z < -0.12 else 0.0
        return sand, carve, under
    set_mask(o, mask)
    mesh.smooth(o, angle=50)
    mat.assign(o, m_deck())
    o["atlas_weight"] = 60.0
    return o


@piece
def build_deck_seam():
    bm = bmesh.new()
    ys = [-ROW / 2 + ROW * k / 10 for k in range(11)]
    for s in SEAMS:
        x0, x1, z0, z1 = s - 0.025, s + 0.025, 0.012, 0.034
        prof = [(x0, z0), (x0, z1), (x1, z1), (x1, z0)]
        rings = [[bm.verts.new((px, y, pz)) for px, pz in prof] for y in ys]
        for j in range(len(ys) - 1):
            quad_strip(bm, rings[j], rings[j + 1], closed=False)
    o = bm_obj("deck_seam", bm)
    bmesh_fix_normals_up(o)
    mat.assign(o, m_seam())
    mesh.uv_box(o, 0.5)
    return o


def bmesh_fix_normals_up(o):
    """Open strips: make faces point away from the strip's centre line / up."""
    bm = bmesh.new()
    bm.from_mesh(o.data)
    for f in bm.faces:
        c = f.calc_center_median()
        n = f.normal
        s = min(SEAMS, key=lambda v: abs(v - c.x))
        want = Vector((c.x - s, 0, 0)) if abs(n.z) < 0.5 else Vector((0, 0, 1))
        if n.dot(want) < 0:
            f.normal_flip()
    bm.to_mesh(o.data)
    bm.free()


# ---------------------------------------------------------------- tunnel: a slot-canyon vault

def tunnel_profile(y):
    """Closed cross-section loop (x, z) at station y: inner left wall up to the
    slit, the slit lip, the outer shell, back. Periodic in y."""
    ph = TAU * y / ROW

    def W(z):
        pts = [(-7.2, 4.4), (-5.6, 5.7), (-3.5, 6.35), (-1.0, 6.7), (2.0, 6.75), (5.0, 6.65), (7.5, 6.35), (8.4, 5.7),
               (9.3, 4.8), (10.2, 3.6), (11.0, 2.4), (11.7, 1.35), (12.3, 0.62)]
        if z <= pts[0][0]:
            return pts[0][1]
        for (z0, w0), (z1, w1) in zip(pts, pts[1:]):
            if z <= z1:
                return lerp(w0, w1, (z - z0) / (z1 - z0))
        return pts[-1][1]

    zl = [-7.2, -6.2, -5.2, -4.2, -3.2, -2.2, -1.2, -0.3, 0.6, 1.5, 2.4, 3.3, 4.2, 5.1, 6.0, 6.9, 7.7, 8.4, 9.0,
          9.6, 10.2, 10.8, 11.3, 11.8, 12.3]

    def wall(z, side):
        top = smoothstep(12.4, 9.0, z)
        amp = 0.42 * top
        s = side * 1.7
        mod = 1.0 + 0.3 * math.sin(ph + s)
        w = (amp * mod * math.sin(1.05 * z + 0.55 * math.sin(ph + s)) +
             0.5 * amp * math.sin(2.6 * z + 1.0 + s + 0.4 * math.cos(ph)) +
             0.25 * amp * pnoise(z * 0.7, y, scale=0.9, seed=11 + side))
        return W(z) + w - (0.1 if side < 0 else 0.0) * top

    inner_l = [(-wall(z, -1), z) for z in reversed(zl)]           # slit -> bottom
    bottom = [(-3.2, -7.9), (-1.1, -8.25), (1.1, -8.25), (3.2, -7.9)]
    inner_r = [(wall(z, 1), z) for z in zl]                        # bottom -> slit

    def outer(p, side):
        x, z = p
        return (x + side * 0.45 * pnoise(z * 0.3, y, scale=0.8, seed=21 + side), z)

    out_r = [(1.3, 13.3), (3.4, 14.0), (6.2, 13.7), (8.6, 12.4), (9.9, 9.0), (10.5, 4.0), (10.6, -1.0),
             (10.4, -7.0), (10.1, -15.0), (9.9, BELOW)]
    out_r = [outer(p, 1) for p in out_r]
    out_b = [(4.0, BELOW - 0.3), (-4.0, BELOW - 0.3)]
    out_l = [outer((-x, z), -1) for x, z in reversed(out_r)]
    return inner_l + bottom + inner_r + out_r + out_b + out_l, len(inner_l) + len(bottom) + len(inner_r)


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


@piece
def build_tunnel():
    ys = [-ROW / 2 + ROW * k / 10 for k in range(11)]
    bm = bmesh.new()
    rings = []
    for y in ys:
        loop, n_in = tunnel_profile(y)
        rings.append([bm.verts.new((x, y, z)) for x, z in loop])
    for j in range(len(ys) - 1):
        quad_strip(bm, rings[j], rings[j + 1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    # portal faces: the C-shaped strip between the inner arc and the outer shell
    for ring, want in ((rings[0], -1.0), (rings[-1], 1.0)):
        zipper(bm, ring[:n_in], list(reversed(ring[n_in:])), want, centre=(0.0, 2.5))
    o = bm_obj("tunnel", bm)
    # the inner walls must face the cavity: check one inner-wall face points to +x on the left
    me = o.data
    me.update()
    left = [p for p in me.polygons if p.center.x < -5 and abs(p.center.z - 2) < 1.5 and abs(p.center.x) < 7.6
            and abs(p.normal.y) < 0.5]
    if left and sum(p.normal.x for p in left) < 0:
        for p in me.polygons:
            if abs(p.normal.y) < 0.9:
                p.flip()
        me.update()
    mesh.smooth(o, angle=None)
    mat.assign(o, m_sandstone("SlotRock", tint="#e0935c", scale=3.2, strata=0.9, band_scale=0.33, varnish=0.25,
                              rock=0.25, flow=1.0, seed=3.0,
                              stops=[(0.0, "#7a3424"), (0.2, "#c2572f"), (0.38, "#f08a4a"), (0.52, "#ffc58a"),
                                     (0.68, "#d9683a"), (0.84, "#8c3a3a"), (1.0, "#e89a6a")]))
    o["atlas_weight"] = 6.0
    return o


# ---------------------------------------------------------------- overhang: a chat-bubble arch

@piece
def build_overhang():
    bm = bmesh.new()
    # bubble body: rounded rect in X-Z, 0.52 deep, underside just above the 1.05 hitbox
    prism(bm, rounded_rect(-3.7, 1.04, 3.7, 3.22, 0.85, n=8), -0.26, 0.26)
    # the tail: off the bottom-right corner, pointing down and out, clear of the lanes
    tail = [(2.75, 1.25), (3.55, 1.4), (3.95, 0.5), (3.7, 0.45), (3.17, 1.03)]
    prism(bm, tail, -0.2, 0.2)
    # pillars (outside x +-3.6) with capitals the bubble rests on
    for sx in (-1, 1):
        x0 = 4.0 if sx < 0 else 4.15
        pts = [(sx * x0, -0.3), (sx * (x0 + 0.72), -0.3), (sx * (x0 + 0.7), 3.3), (sx * (x0 + 0.02), 3.35)]
        prism(bm, pts[::sx], -0.4, 0.4)
        cap = [(sx * 3.5, 2.4), (sx * 4.95, 2.32), (sx * 5.0, 3.55), (sx * 3.45, 3.5)]
        prism(bm, cap[::sx], -0.34, 0.34)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    o = bm_obj("overhang", bm)
    remesh(o, 0.035, smooth_iter=4, smooth_factor=0.5)

    def disp(co, n):
        pillar = smoothstep(3.9, 4.2, abs(co.x)) * (1 - smoothstep(2.3, 2.5, co.z) * 0.5)
        big = fbm(co * 0.9 + Vector((3, 1, 0)), 3) * (0.015 + 0.08 * pillar)
        grain = fbm(co * 6.0, 2) * 0.008
        zz = co.z + 0.15 * fbm(co * 0.7, 2)
        bed = -0.022 * smoothstep(0.75, 0.95, abs(math.sin(zz * 5.2))) * (1 - abs(n.z))   # weathered bedding grooves
        chip = -0.03 * smoothstep(0.55, 0.75, noise.noise(co * 2.3 + Vector((7, 0, 0))))
        return big + grain + bed + chip
    displace(o, disp)

    def clampz(co):  # keep the underside at >= 1.05 over the lanes (the hitbox)
        if abs(co.x) < 3.2 and 0.5 < co.z < 1.06:
            co.z = 1.06
        return co
    warp(o, clampz)
    decimate_to(o, 2300)
    mesh.smooth(o, angle=None)
    mat.assign(o, m_sandstone("BubbleStone", tint="#f2c99a", scale=1.4, strata=0.6, band_scale=0.75, varnish=0.35,
                              rock=0.3, seed=5.0, bright=1.35, sand=0.4,
                              stops=[(0.0, "#b97a52"), (0.35, "#f3d2ae"), (0.6, "#dca77a"), (1.0, "#f6dcbc")]))
    # "..." typing dots, both faces, and a glowing line along the clearance edge
    glow = m_glow()
    parts = [o]
    for fy in (-1, 1):
        for x in (-1.15, 0.0, 1.15):
            d = mesh.cylinder("dot", 0.33, 0.05, verts=16, location=(x, fy * 0.262, 2.13), axis="Y")
            mat.assign(d, glow)
            mesh.smooth(d, angle=30)
            parts.append(d)
    strip = mesh.box("strip", (6.3, 0.18, 0.035), location=(0, 0, 1.055))
    mat.assign(strip, glow)
    parts.append(strip)
    o = join(parts, "overhang")
    o["atlas_weight"] = 14.0
    return o


# ---------------------------------------------------------------- rock helpers

def canyon_disp(amp=0.5, freq=0.09, strata=0.1, layer=2.4, flute=0.25, flute_f=0.35, grain=0.05, seed=0.0,
                top_flat=True):
    """Weathered sandstone: big lumps, soft bedding (harder layers stand out a
    little more), vertical fluting where rain runs down, fine grain; flat tops."""
    off = Vector((seed * 13.1, seed * 7.7, seed * 3.3))

    def f(co, n):
        vert = 1.0 - abs(n.z)
        big = amp * fbm(co * freq + off, 3)
        zz = co.z + 1.6 * fbm(co * 0.05 + off, 2)
        hard = 0.35 + smoothstep(0.0, 0.5, noise.noise(Vector((0.0, seed, zz * 0.23))))
        bed = strata * math.sin(TAU * zz / layer) * hard * vert
        q = Vector((co.x * flute_f, co.y * flute_f, co.z * flute_f * 0.1)) + off
        fl = flute * (0.5 - abs(noise.noise(q))) * 2.0 * vert
        g = grain * fbm(co * 1.1 + off, 2)
        k = 0.3 if (top_flat and n.z > 0.75) else 1.0
        return (big + g) * k + bed + fl
    return f


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


def rock_blob(parts_fn, voxel, disp, target, name, smooth_iter=2, loops=1.0):
    """parts_fn(bm) adds closed primitives; voxel-remeshed into one rock,
    displaced, decimated, hidden bottoms deleted, bend loops split in, smooth."""
    bm = bmesh.new()
    parts_fn(bm)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    o = bm_obj(name, bm)
    remesh(o, voxel, smooth_iter=smooth_iter, smooth_factor=0.5)
    displace(o, disp)
    delete_faces(o, lambda c, n: c.z < BELOW + 1.2 and n.z < -0.5)
    fit_tris(o, target, loops)
    mesh.smooth(o, angle=None)
    return o


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


def pillar(bm, x, y, rx, ry, top, flare=0.7, seed=0.0, sides=16, step=1.6, bottom=BELOW, lump=0.2):
    """A rock tower rising out of the canyon: elliptical, irregular plan,
    flaring toward its hidden foot."""
    def rf(th, z):
        c, s = math.cos(th), math.sin(th)
        base = rx * ry / math.sqrt((ry * c) ** 2 + (rx * s) ** 2)
        plan = 1.0 + lump * noise.noise(Vector((c * 1.4 + seed, s * 1.4 + seed * 0.3, z * 0.05)))
        k = max(0.0, (top - z) / (top - bottom))
        return base * plan * (1.0 + flare * k ** 1.3)
    column(bm, x, y, bottom, top, rf, sides=sides, step=step)


def canyon_rock_mat(name="CanyonRock", **kw):
    return m_sandstone(name, **kw)


def rock_pillar(name, specs, target=800, seed=0.0, mat_kw=None):
    """One or more pillars (x, y, rx, ry, top) merged into a rock base for props."""
    def parts(bm):
        for i, (x, y, rx, ry, top) in enumerate(specs):
            pillar(bm, x, y, rx, ry, top, flare=0.55, seed=seed + i * 3.1)
            # a slightly overhanging flat cap rock
            column(bm, x, y, top - 0.9, top, lambda th, z, rx=rx, ry=ry: rx * ry / math.sqrt(
                (ry * math.cos(th)) ** 2 + (rx * math.sin(th)) ** 2) * (1.08 + 0.08 * math.sin(3 * th + seed)),
                sides=14, step=0.45)
    o = rock_blob(parts, 0.26, canyon_disp(amp=0.3, freq=0.2, strata=0.06, layer=1.6, flute=0.22, flute_f=0.7,
                                           seed=seed), target, name, smooth_iter=3)
    mat.assign(o, canyon_rock_mat(name + "Mat", seed=seed, **(mat_kw or {})))
    return o


def loft_rock(name, y0, y1, step, height, front, back, zs, top_n=6, end=0.18, disp=None):
    """A rock built from vertical sections every `step` along Y (so the bend
    loops come for free): each section is the front face (x = front(y, z, h) for
    z in zs(h)), the top, and the back (x = back(y, z, h)), h = height(y). The
    ends round off in plan over the last `end` fraction of the length."""
    n = max(2, int(math.ceil((y1 - y0) / step)) + 1)
    ys = [y0 + (y1 - y0) * i / (n - 1) for i in range(n)]
    bm = bmesh.new()
    rings = []
    for y in ys:
        t = 2 * (y - y0) / (y1 - y0) - 1
        k = smoothstep(1 - end, 1.0, abs(t))
        pull = 0.82 * (1 - math.sqrt(max(0.0, 1 - k * k)))
        h = height(y)
        zl = zs(h)
        fr = [(min(front(y, z, h), back(y, z, h) - 0.8), z) for z in zl]   # never through the back
        bk = [(back(y, z, h), z) for z in reversed(zl[:: max(1, len(zl) // 5)])]
        if bk[-1][1] != zl[0]:
            bk.append((back(y, zl[0], h), zl[0]))
        top = []
        xa, xb = fr[-1][0], bk[0][0]
        for i in range(1, top_n):
            u = i / top_n
            top.append((lerp(xa, xb, u), h + 0.25 * fbm(Vector((u * 3.0, y * 0.2, 7.0)), 2)))
        sec = fr + top + bk
        mid = sum(x for x, _ in sec) / len(sec)
        sec = [(lerp(x, mid, pull), z) for x, z in sec]
        rings.append([bm.verts.new((x, y, z)) for x, z in sec])
    for a, b in zip(rings, rings[1:]):
        quad_strip(bm, a, b)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    # sides face outward: check against the section centroid, flip all if needed
    f0 = bm.faces[len(rings[0]) // 3]
    c0 = f0.calc_center_median()
    ring_mid = sum((v.co for v in rings[len(rings) // 2]), Vector()) / len(rings[0])
    if f0.normal.dot(Vector((c0.x - ring_mid.x, 0.0, c0.z - ring_mid.z))) < 0:
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


def gully(y, z, seed, amp, fy=0.35, fz=0.045):
    """Vertical rain gullies: ridged noise, fast along the face, slow down it."""
    return amp * abs(noise.noise(Vector((y * fy + seed, z * fz, seed * 0.37))))


def bench_profile(z, benches):
    """Horizontal offset of a stepped cliff: `benches` = [(z_step, dx)] where
    above z_step the face sits dx further back (sharp-ish ledges)."""
    x = 0.0
    for zb, dx in benches:
        x += dx * smoothstep(zb - 0.25, zb + 0.25, z)
    return x


# ---------------------------------------------------------------- wall: canyon cliff

@piece
def build_side_cliff():
    L = 16.0

    def height(y):
        return 8.5 + 3.2 * smoothstep(-2.5, -0.5, y) - 1.8 * smoothstep(4.5, 6.5, y) + 0.8 * fbm(Vector((y * 0.15, 3.0, 0)), 2)

    def zs(h):
        return [BELOW, -18.0, -13.0, -9.0, -6.0, -4.2, -3.6, -2.0, -0.5, 1.0, 2.2, 3.2, 3.8, 5.0, 6.2, 7.1, 7.7] + \
               [h - 2.4, h - 1.6, h - 1.1, h - 0.5, h] if True else []

    def front(y, z, h):
        x = bench_profile(z, [(-4.0, 0.9), (3.5, 0.6), (7.4, 0.5), (h - 1.3, -0.45)])
        x += 0.018 * max(0.0, -4.0 - z) * -1.0            # lower body leans out a little
        x += 0.9 * math.exp(-((z - 2.2) / 1.4) ** 2) * smoothstep(-3.0, -1.0, y) * (1 - smoothstep(1.5, 3.0, y))  # alcove
        x -= 0.8 * math.exp(-((y + 5.2) / 1.2) ** 2) + 0.7 * math.exp(-((y - 3.8) / 1.1) ** 2)   # buttresses
        x += gully(y, z, 1.0, 1.0, fy=0.45, fz=0.06) + 0.35 * fbm(Vector((y * 0.2, z * 0.15, 1.0)), 3)
        return x

    def back(y, z, h):
        return 4.6 + 0.3 * fbm(Vector((y * 0.2, z * 0.1, 9.0)), 2)

    zs_fn = lambda h: sorted({min(v, h) for v in zs(h)})  # noqa: E731
    o = loft_rock("side_cliff", -L / 2, L / 2, 0.5, height, front, back, zs_fn, top_n=5, end=0.16,
                  disp=lambda co, n: 0.08 * fbm(co * 0.9, 3))
    delete_faces(o, lambda c, n: c.x > 3.6 and n.x > 0.85)   # the back, never seen from the track
    mesh.smooth(o, angle=55)
    mat.assign(o, canyon_rock_mat("CliffRock", seed=1.0))
    lo, hi = mesh.bounds(o, world=False)
    origin_to(o, (lo.x, 0.0, 0.0))
    o["atlas_weight"] = 2.0
    return extras(o, "wall", 17, 0.5)


# ---------------------------------------------------------------- wall: "..." typing-dots boulders on a bubble ledge

@piece
def build_side_typing():
    def parts(bm):
        # the ledge: a thick, pillowy typing bubble (rounded rect, a little tail toward the track)
        outline = rounded_rect(-4.4, 0.2, 4.4, 3.8, 1.6, n=6)          # (u = y, v = x)
        top = [bm.verts.new((v, u, 0.45)) for u, v in outline]
        bot = [bm.verts.new((v, u, -1.0)) for u, v in outline]
        quad_strip(bm, bot, top)
        bm.faces.new(top)
        bm.faces.new(list(reversed(bot)))
        tail = [(-3.0, 0.5), (-4.7, -0.35), (-3.9, 1.3)]
        t_top = [bm.verts.new((v, u, 0.4)) for u, v in tail]
        t_bot = [bm.verts.new((v, u, -0.7)) for u, v in tail]
        quad_strip(bm, t_bot, t_top)
        bm.faces.new(t_top)
        bm.faces.new(list(reversed(t_bot)))
        # the rock tower under it
        pillar(bm, 2.4, 0.3, 2.0, 3.4, -0.4, flare=0.8, seed=2.0)
    ledge = rock_blob(parts, 0.2, canyon_disp(amp=0.18, freq=0.25, strata=0.04, layer=1.3, flute=0.18, flute_f=0.6,
                                              seed=2.0), 1700, "typing_ledge", smooth_iter=5)
    mat.assign(ledge, canyon_rock_mat("TypingRock", tint="#e6b48a", scale=2.0, strata=0.45, band_scale=0.5,
                                      varnish=0.3, seed=2.0))
    parts_list = [ledge]
    # the three dots: round, equal, evenly spaced, weathered
    dots = m_sandstone("DotRock", tint="#efc59c", scale=1.2, strata=0.2, band_scale=1.2, varnish=0.1, rock=0.5,
                       seed=9.0, bright=1.2)
    for i, y in enumerate((-2.6, 0.0, 2.6)):
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=4, radius=1.08)
        b = bm_obj(f"dot{i}", bm)

        def dd(co, n, i=i):
            return 0.05 * fbm(co * 1.4 + Vector((i * 5.0, 0, 0)), 3) + 0.018 * fbm(co * 5.0, 2)
        displace(b, dd)
        decimate_to(b, 440)
        b.location = (1.9, y, 0.45 + 1.0)
        mesh.apply_transform(b)
        mesh.smooth(b, angle=None)
        mat.assign(b, dots)
        parts_list.append(b)
    o = join(parts_list, "side_typing")
    split_long(o)
    lo, hi = mesh.bounds(o, world=False)
    origin_to(o, (lo.x, 0.0, 0.0))
    o["atlas_weight"] = 3.0
    return extras(o, "wall", 70, 0.45)


def bmesh_face_minus_x(o):
    for p in o.data.polygons:
        if p.normal.x > 0:
            p.flip()
    o.data.update()


def hard(o, angle=40):
    mesh.smooth(o, angle=angle)
    return o


# ---------------------------------------------------------------- wall: green road sign "Seen 3:12 am"

@piece
def build_side_sign_seen():
    parts = []
    base = rock_pillar("sign_base", [(1.7, 0.0, 1.9, 3.3, 0.0)], target=600, seed=4.0)
    parts.append(base)
    wood = m_wood()
    green = m_sign_green()
    white = m_paint("SignWhite", "#ece7da", rough=0.35, grime=0.4)
    galv = m_metal("Galvanised", "#9a9c98")
    for y in (-1.9, 1.9):
        p = hard(mesh.box("post", (0.24, 0.3, 6.4), location=(1.25, y, 3.0), bevel=0.02, segments=1))
        mat.assign(p, wood)
        parts.append(p)
    W, H, zc = 6.2, 2.7, 4.45
    panel = hard(mesh.box("panel", (0.08, W, H), location=(1.06, 0, zc), bevel=0.05, segments=2), 30)
    mat.assign(panel, galv)
    mat.assign(panel, green, faces=lambda f: f.normal.x < -0.9)
    parts.append(panel)
    bm = bmesh.new()
    outer = rounded_rect(-W / 2 + 0.1, zc - H / 2 + 0.1, W / 2 - 0.1, zc + H / 2 - 0.1, 0.22, n=4)
    inner = rounded_rect(-W / 2 + 0.18, zc - H / 2 + 0.18, W / 2 - 0.18, zc + H / 2 - 0.18, 0.15, n=4)
    vo = [bm.verts.new((1.013, -u, v)) for u, v in outer]
    vi = [bm.verts.new((1.013, -u, v)) for u, v in inner]
    quad_strip(bm, vo, vi)
    frame = bm_obj("frame", bm)
    bmesh_face_minus_x(frame)
    mat.assign(frame, white)
    parts.append(hard(frame))
    t1 = text_mesh("t1", "Seen", 0.95, extrude=0.012, offset=0.012)
    place(t1, Matrix.Translation((1.014, 0, zc + 0.52)) @ FACE_TRACK)
    t2 = text_mesh("t2", "3:12 am", 0.95, extrude=0.012, offset=0.012)
    place(t2, Matrix.Translation((1.014, 0, zc - 0.58)) @ FACE_TRACK)
    for z in (zc - 0.7, zc + 0.7):
        b = hard(mesh.box("brace", (0.06, W - 0.4, 0.12), location=(1.14, 0, z)))
        mat.assign(b, galv)
        parts.append(b)
    plate = hard(mesh.box("plate", (0.06, 4.1, 0.8), location=(1.08, 0, 2.55), bevel=0.03, segments=1))
    mat.assign(plate, galv)
    mat.assign(plate, green, faces=lambda f: f.normal.x < -0.9)
    parts.append(plate)
    t3 = text_mesh("t3", "NO REPLY  NEXT 400 mi", 0.27, extrude=0.008, offset=0.004)
    place(t3, Matrix.Translation((1.056, 0, 2.55)) @ FACE_TRACK)
    for t in (t1, t2, t3):
        mat.assign(t, white)
        parts.append(hard(t, 60))
    o = join(parts, "side_sign_seen")
    split_long(o)
    origin_to(o, (mesh.bounds(o, world=False)[0].x, 0.0, 0.0))
    o["atlas_weight"] = 7.0
    return extras(o, "wall", 110, 0.5)


# ---------------------------------------------------------------- wall: signpost "Delivered" / "Read"

@piece
def build_side_signpost():
    parts = []
    base = rock_pillar("post_base", [(1.5, 0.0, 1.7, 2.1, 0.0)], target=750, seed=6.0)
    parts.append(base)
    wood = m_wood("PostWood", "#a8927a")
    board = m_wood("BoardWood", "#e2d6c0", scale=0.9)
    ink = m_paint("SignInk", "#241812", rough=0.6, grime=0.15)
    post = hard(mesh.box("post", (0.34, 0.34, 8.4), location=(1.4, 0, 3.9), bevel=0.03, segments=1))
    mat.assign(post, wood)
    parts.append(post)
    cap = hard(mesh.box("cap", (0.46, 0.46, 0.14), location=(1.4, 0, 8.15), bevel=0.02, segments=1))
    mat.assign(cap, wood)
    parts.append(cap)
    # arrow boards: (text, z, +1 points to the viewer's right (-Y), tilt, length, height, text size)
    boards = [("DELIVERED", 6.9, 1, 0.03, 4.6, 0.95, 0.56), ("READ", 5.7, -1, -0.05, 3.4, 0.95, 0.62),
              ("typing...", 4.55, 1, 0.1, 3.6, 0.8, 0.5)]
    for i, (word, z, dirn, tilt, L, H, ts) in enumerate(boards):
        tip = 0.6
        u0 = -0.3 if dirn > 0 else -(L - 0.3)
        u1 = u0 + L
        if dirn > 0:
            outline = [(u0, -H / 2), (u1 - tip, -H / 2), (u1, 0), (u1 - tip, H / 2), (u0, H / 2)]
        else:
            outline = [(u0 + tip, -H / 2), (u1, -H / 2), (u1, H / 2), (u0 + tip, H / 2), (u0, 0)]
        bm = bmesh.new()
        prism(bm, outline, -0.09, 0.0, axis="X")
        b = bm_obj(f"board{i}", bm)
        warp(b, lambda co: Vector((co.x, -co.y, co.z)))   # outline u ran along +Y: +dirn now points to -Y
        mesh.clean(b)
        rot = Matrix.Translation((1.23, 0, z)) @ Matrix.Rotation(tilt, 4, "X")
        place(b, rot)
        mat.assign(b, board)
        parts.append(hard(b))
        t = text_mesh(f"w{i}", word, ts, extrude=0.008, offset=0.012)
        centre = -(u0 + u1) / 2 + (0.25 if dirn > 0 else -0.25)
        place(t, rot @ Matrix.Translation((-0.096, centre, -0.02)) @ FACE_TRACK)
        mat.assign(t, ink)
        parts.append(hard(t, 60))
    o = join(parts, "side_signpost")
    split_long(o)
    origin_to(o, (mesh.bounds(o, world=False)[0].x, 0.0, 0.0))
    o["atlas_weight"] = 7.0
    return extras(o, "wall", 80, 0.45)


# ---------------------------------------------------------------- wall: telegraph poles, sagging wires, an earbud tumbleweed

def wire_pts(a, b, sag, n):
    a, b = Vector(a), Vector(b)
    return [a.lerp(b, i / (n - 1)) - Vector((0, 0, sag * 4 * (i / (n - 1)) * (1 - i / (n - 1)))) for i in range(n)]


def earbud_tumbleweed(radius=1.2, wires=6, seed=3):
    """A tangle of wired earbuds: wandering loops on a noisy shell, two bud
    heads and a jack plug. Returns (wire_obj, bud_obj)."""
    import random
    rnd = random.Random(seed)
    bm = bmesh.new()
    for w in range(wires):
        axis = Vector((rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.uniform(-1, 1))).normalized()
        ref = axis.orthogonal().normalized()
        other = axis.cross(ref)
        pts = []
        n = 28
        ph = rnd.uniform(0, TAU)
        for i in range(n + 1):
            a = TAU * i / n * 1.15 + ph
            r = radius * (0.75 + 0.25 * math.sin(3 * a + w) + 0.12 * rnd.uniform(-1, 1))
            pts.append((ref * math.cos(a) + other * math.sin(a)) * r + axis * (0.35 * radius * math.sin(2 * a + w * 1.3)))
        tube(bm, pts, 0.035, sides=4, caps=True)
    wire = bm_obj("tumble_wire", bm)
    bm = bmesh.new()
    for k in range(2):
        d = Vector((rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.uniform(0.2, 1))).normalized() * radius * 0.95
        bmesh.ops.create_uvsphere(bm, u_segments=10, v_segments=7, radius=0.16,
                                  matrix=Matrix.Translation(d) @ Matrix.Diagonal((1, 1, 0.85, 1)))
        tube(bm, [d - d.normalized() * 0.05, d + d.normalized() * 0.2], 0.07, sides=8, caps=True)
    j = Vector((0.0, -radius * 1.05, -0.2))
    tube(bm, [j, j + Vector((0, -0.28, 0.05))], 0.06, sides=8)
    tube(bm, [j + Vector((0, -0.28, 0.05)), j + Vector((0, -0.52, 0.09))], 0.022, sides=6)
    bud = bm_obj("tumble_buds", bm)
    return wire, bud


@piece
def build_side_telegraph():
    parts = []
    base = rock_pillar("tele_base", [(1.5, -6.0, 1.4, 1.6, -0.4), (2.7, 6.0, 2.4, 2.3, -0.2)], target=1000, seed=8.0)
    parts.append(base)
    wood = m_wood("PoleWood", "#9e8a76")
    glass = m_glass_insulator()
    cable = m_rubber()
    tops = []
    for i, (x, y, lean) in enumerate(((1.5, -6.0, 0.02), (2.3, 6.0, -0.06))):
        bm = bmesh.new()
        tube(bm, [(x, y, -1.5), (x + lean * 9, y, 8.6)], 0.17, sides=8, rfun=lambda i_, t, th: 0.19 - 0.05 * t)
        pole = bm_obj(f"pole{i}", bm)
        mat.assign(pole, wood)
        parts.append(hard(pole, 60))
        top = Vector((x + lean * 8.2, y, 7.9))
        arm = hard(mesh.box("arm", (2.6, 0.14, 0.16), location=top, bevel=0.01, segments=1))
        mat.assign(arm, wood)
        parts.append(arm)
        ins = []
        for dx in (-1.1, -0.2, 1.1):
            c = mesh.cylinder("ins", 0.07, 0.2, verts=8, location=top + Vector((dx, 0, 0.17)))
            mat.assign(c, glass)
            parts.append(hard(c, 50))
            ins.append(top + Vector((dx, 0, 0.27)))
        tops.append(ins)
    bm = bmesh.new()
    for a, b in zip(tops[0], tops[1]):
        tube(bm, wire_pts(a, b, 1.1, 26), 0.03, sides=4, caps=False)
    for k, a in enumerate(tops[0]):  # cut wires dangling off both ends into the canyon
        tube(bm, [a + Vector((0.1 * k, -3.0 * t - 0.8 * t * t, -9.0 * t * t - 0.3 * t)) for t in [i / 11 for i in range(12)]],
             0.03, sides=4, caps=True)
    for k, a in enumerate(tops[1]):
        if k == 1:
            continue
        tube(bm, [a + Vector((-0.2 * k, 2.6 * t + 0.5 * t * t, -12.0 * t * t)) for t in [i / 11 for i in range(12)]],
             0.03, sides=4, caps=True)
    wires = bm_obj("wires", bm)
    mat.assign(wires, cable)
    parts.append(hard(wires, 80))
    wire, buds = earbud_tumbleweed(1.25, 5, seed=5)
    plastic = m_plastic()
    for t in (wire, buds):
        t.location = (1.9, 4.7, -0.2 + 1.2)
        mat.assign(t, plastic)
        parts.append(hard(t, 80))
    o = join(parts, "side_telegraph")
    split_long(o)
    origin_to(o, (mesh.bounds(o, world=False)[0].x, 0.0, 0.0))
    o["atlas_weight"] = 3.0
    return extras(o, "wall", 46, 0.55)


# ---------------------------------------------------------------- mid: hoodoos

@piece
def build_side_hoodoo():
    def hoodoo(bm, x, y, top, r0, seed):
        def rf(th, z):
            layer = math.sin(z * 1.7 + seed) * 0.16 + math.sin(z * 3.9 + seed * 2) * 0.06
            neck = 0.32 * smoothstep(top - 3.0, top - 1.4, z) * (1 - smoothstep(top - 1.2, top - 0.9, z))
            taper = 1.0 + 0.05 * max(0.0, 6.0 - z)
            return max(0.35, r0 * (taper + layer - neck) * (1 + 0.1 * math.sin(3 * th + seed)))
        column(bm, x, y, 1.0, top - 0.9, rf, sides=14, step=0.7)
        column(bm, x + 0.1, y, top - 1.05, top, lambda th, z: r0 * 1.45 * (1 + 0.14 * math.sin(2 * th + seed)),
               sides=12, step=0.5)

    def parts(bm):
        hoodoo(bm, 3.2, -4.5, 13.0, 1.25, 1.0)
        hoodoo(bm, 5.4, 0.8, 18.5, 1.55, 2.0)
        hoodoo(bm, 2.8, 5.2, 10.0, 1.05, 3.0)
        hoodoo(bm, 7.6, 4.0, 15.0, 1.2, 4.0)
        # badland skirt the spires grow out of, down into the canyon
        pillar(bm, 5.0, 0.3, 4.2, 6.8, 3.2, flare=0.9, seed=3.0, sides=18, step=2.0)
        column(bm, 5.0, 0.3, 1.0, 4.4, lambda th, z: (3.2 + 1.2 * smoothstep(4.4, 1.0, z)) *
               (1 + 0.18 * math.sin(3 * th) + 0.08 * math.sin(5 * th + 1)), sides=16, step=0.8)
    o = rock_blob(parts, 0.26, canyon_disp(amp=0.28, freq=0.25, strata=0.07, layer=0.9, flute=0.2, flute_f=0.8,
                                           seed=3.0), 4000, "side_hoodoo", smooth_iter=2)
    mat.assign(o, canyon_rock_mat("HoodooRock", tint="#e89a66", band_scale=0.42, strata=0.8, seed=3.0,
                                  stops=[(0.0, "#8a4a2e"), (0.3, "#d77c4a"), (0.5, "#f7d0a8"), (0.7, "#c9653c"),
                                         (0.85, "#f0b88a"), (1.0, "#9a5a3a")]))
    lo, hi = mesh.bounds(o, world=False)
    origin_to(o, (lo.x, 0.0, 0.0))
    o["atlas_weight"] = 1.5
    return extras(o, "mid", 26, 0.55)


# ---------------------------------------------------------------- mid: chat-bubble rock formation

def bubble_outline(w, h, r, tail_side=-1, tail=1.6, n=6):
    """Rounded rect (u along the bubble width, v up) and a tail off one bottom corner."""
    pts = rounded_rect(-w / 2, 0.0, w / 2, h, r, n)
    s = tail_side
    tp = [(s * (w / 2 - r * 0.6), 0.35), (s * (w / 2 + tail * 0.35), -tail), (s * (w / 2 - r * 1.6), 0.25)]
    if s > 0:
        tp = tp[::-1]
    return pts, tp


@piece
def build_side_bubble():
    def parts(bm):
        # the message: a big bubble, tail to the viewer's left (+Y), on a hoodoo neck
        body, tail = bubble_outline(11.0, 6.6, 2.4, tail_side=-1, tail=2.2)
        prism(bm, [(-u, 7.2 + v) for u, v in body][::-1], 0.3, 3.5, axis="X")
        prism(bm, [(-u, 7.2 + v) for u, v in tail][::-1], 0.8, 3.0, axis="X")
        # the reply: smaller, cantilevered off its top-right, tail the other way
        body2, tail2 = bubble_outline(7.2, 4.2, 1.7, tail_side=1, tail=1.4)
        prism(bm, [(-u - 4.5, 13.5 + v) for u, v in body2][::-1], 0.8, 3.4, axis="X")
        prism(bm, [(-u - 4.5, 13.5 + v) for u, v in tail2][::-1], 1.1, 3.0, axis="X")
        # neck and the rock tower
        column(bm, 2.2, 0.8, 2.0, 8.0, lambda th, z: 1.5 + 0.9 * smoothstep(5.0, 2.0, z) + 0.2 * math.sin(3 * th),
               sides=14, step=0.8)
        pillar(bm, 2.3, 0.6, 2.6, 4.2, 2.6, flare=0.8, seed=4.0)
    o = rock_blob(parts, 0.15, canyon_disp(amp=0.32, freq=0.3, strata=0.13, layer=0.8, flute=0.2, flute_f=1.0,
                                           grain=0.08, seed=4.0, top_flat=False), 4100, "side_bubble", smooth_iter=2)
    mat.assign(o, canyon_rock_mat("BubbleRock", tint="#e6aa7e", band_scale=0.3, strata=0.95, varnish=0.7, seed=4.0,
                                  stops=[(0.0, "#7a3a24"), (0.25, "#c46a3e"), (0.45, "#f0b98a"), (0.62, "#d98a58"),
                                         (0.8, "#9a4c30"), (1.0, "#eab08a")]))
    lo, hi = mesh.bounds(o, world=False)
    origin_to(o, (lo.x, 0.0, 0.0))
    o["atlas_weight"] = 2.0
    return extras(o, "mid", 50, 0.5)


# ---------------------------------------------------------------- mid: double-tick saguaros on a rock tower

def saguaro(bm, base, height, lean, arm_len, r=0.55):
    """A saguaro shaped like a tick (seen from its -X face, right = -Y): the
    trunk is the long stroke leaning to the right, the arm the short stroke
    rising to the upper left from low on the trunk."""
    ribs = 10
    base = Vector(base)
    n = int(height / 0.5) + 1
    trunk = [base + Vector((0.0, -lean * (i / (n - 1)) ** 1.15, height * i / (n - 1))) for i in range(n)]

    def rtrunk(i, t, th):
        tipk = math.sqrt(max(0.0, 1 - ((t - 0.9) / 0.1) ** 2)) if t > 0.9 else 1.0
        return max(0.03, r * (1.0 + 0.12 * math.cos(ribs * th)) * (0.2 + 0.8 * tipk) * (1.0 + 0.05 * math.sin(math.pi * t)))
    tube(bm, trunk, r, sides=24, rfun=rtrunk, caps=True)
    # arm: from just above the base, straight up-left at ~50 deg, the tip bending up
    a0 = base + Vector((0.0, 0.0, 0.9))
    m = 10
    arm = []
    for i in range(m):
        t = i / (m - 1)
        d = Vector((0.0, math.cos(math.radians(48 + 25 * t * t)), math.sin(math.radians(48 + 25 * t * t))))
        arm.append((arm[-1] if arm else a0) + d * (arm_len / (m - 1) if i else 0.0))

    def rarm(i, t, th):
        tipk = math.sqrt(max(0.0, 1 - ((t - 0.85) / 0.15) ** 2)) if t > 0.85 else 1.0
        return max(0.03, r * 0.78 * (1.0 + 0.12 * math.cos(ribs * th)) * (0.2 + 0.8 * tipk))
    tube(bm, arm, r, sides=20, rfun=rarm, caps=True)


@piece
def build_side_saguaro():
    base = rock_pillar("sag_base", [(3.4, 0.0, 3.2, 5.8, 0.4)], target=950, seed=9.0, mat_kw=dict(sand=1.0))
    bm = bmesh.new()
    saguaro(bm, (0.0, 2.5, -0.2), 9.8, 4.6, 3.2, r=0.74)
    saguaro(bm, (0.9, -2.1, -0.2), 8.6, 4.0, 2.8, r=0.68)
    cac = bm_obj("cacti", bm)
    # turn the pair 40 deg to face both the track and the approaching camera
    warp(cac, lambda co: Matrix.Rotation(math.radians(40), 3, "Z") @ co + Vector((3.2, 0.3, 0.0)))
    mesh.clean(cac, recalc_normals=False)
    mesh.smooth(cac, angle=None)
    mat.assign(cac, m_cactus())
    o = join([base, cac], "side_saguaro")
    split_long(o)
    origin_to(o, (mesh.bounds(o, world=False)[0].x, 0.0, 0.0))
    o["atlas_weight"] = 3.0
    return extras(o, "mid", 34, 0.6, side="right")


# ---------------------------------------------------------------- far: mesa and butte

MESA_ZS = [BELOW, -17.0, -11.0, -6.0, -2.0, 1.5, 4.5, 7.0, 8.6, 9.4, 11.5, 13.5, 15.5, 17.2, 18.6, 19.6, 20.2,
           20.9, 22.5, 24.2, 25.8, 27.2, 28.4, 29.4]


@piece
def build_side_mesa():
    L = 40.0

    def height(y):
        return 32.5 + 1.6 * fbm(Vector((y * 0.05, 1.3, 0.0)), 2)

    def zs(h):
        return [z for z in MESA_ZS if z < h - 2.6] + [h - 2.6, h - 2.0, h - 1.3, h - 0.6, h]

    def front(y, z, h):
        if z < 9.0:   # talus skirt
            x = -1.6 - 0.42 * (9.0 - z) - 1.2 * smoothstep(-24, 9, z) * fbm(Vector((y * 0.07, z * 0.1, 2.0)), 2)
        else:
            x = bench_profile(z, [(20.0, 2.0), (h - 2.4, 0.4), (h - 1.9, -0.9)]) - 1.8 + 0.05 * (20.0 - min(z, 20.0))
        x += 4.5 * fbm(Vector((y * 0.05, 0.5, 3.3)), 3)                  # bays and promontories
        x += gully(y, z, 5.0, 2.6 if z > 9 else 1.2, fy=0.18, fz=0.03) + 0.7 * fbm(Vector((y * 0.08, z * 0.08, 3.0)), 3)
        return x

    def back(y, z, h):
        return 24.0 + 1.5 * fbm(Vector((y * 0.06, z * 0.05, 4.0)), 2)

    o = loft_rock("side_mesa_body", -L / 2, L / 2, 1.0, height, front, back, zs, top_n=7, end=0.22,
                  disp=lambda co, n: 0.2 * fbm(co * 0.35, 3))
    # a detached pinnacle in front of one end
    bm = bmesh.new()
    pillar(bm, 1.5, 17.0, 2.1, 2.5, 21.0, flare=1.6, seed=7.0, sides=12, step=1.5)
    column(bm, 1.6, 17.0, 20.2, 22.4, lambda th, z: 2.6 * (1 + 0.1 * math.sin(3 * th)), sides=12, step=0.7)
    spire = bm_obj("pinnacle", bm)
    displace(spire, canyon_disp(amp=0.3, freq=0.2, strata=0.12, layer=2.2, flute=0.3, flute_f=0.5, seed=7.0))
    split_long(spire)
    o = join([o, spire], "side_mesa")
    mesh.smooth(o, angle=58)
    mat.assign(o, canyon_rock_mat("MesaRock", scale=6.0, band_scale=0.09, strata=0.9, varnish=0.75, seed=5.0))
    lo, hi = mesh.bounds(o, world=False)
    origin_to(o, (lo.x, 0.0, 0.0))
    o["atlas_weight"] = 0.45
    return extras(o, "far", 80, 0.75)


@piece
def build_side_butte():
    L = 17.0

    def height(y):
        return 37.0 + 1.2 * fbm(Vector((y * 0.08, 2.1, 0.0)), 2)

    def zs(h):
        return [BELOW, -16.0, -9.0, -3.0, 2.0, 6.5, 10.0, 12.5, 13.6, 15.5, 18.0, 20.5, 23.0, 25.5, 27.6, 29.2,
                30.2, 31.5, 33.0, h - 2.2, h - 1.5, h - 0.7, h]

    def front(y, z, h):
        if z < 13.0:
            x = -0.8 - 0.5 * (13.0 - z) - 1.0 * fbm(Vector((y * 0.1, z * 0.1, 6.0)), 2)
        else:
            x = bench_profile(z, [(29.5, 0.7), (h - 1.6, -0.7)]) + 0.03 * (29.5 - min(z, 29.5))
        x += 1.6 * fbm(Vector((y * 0.07, 0.5, 6.6)), 2)
        x += gully(y, z, 6.0, 2.0 if z > 13 else 0.9, fy=0.25, fz=0.035) + 0.5 * fbm(Vector((y * 0.1, z * 0.08, 8.0)), 3)
        return x

    def back(y, z, h):
        return 12.0 + (0.5 * (13.0 - z) if z < 13.0 else 0.0) + fbm(Vector((y * 0.1, z * 0.05, 5.0)), 2)

    o = loft_rock("side_butte_body", -L / 2, L / 2, 1.0, height, front, back, zs, top_n=6, end=0.3,
                  disp=lambda co, n: 0.18 * fbm(co * 0.4, 3))
    # the thumb spire on its own talus cone
    bm = bmesh.new()
    pillar(bm, 5.0, -12.5, 1.9, 2.2, 29.0, flare=4.2, seed=6.5, sides=16, step=1.6)
    column(bm, 5.1, -12.5, 28.2, 30.0, lambda th, z: 2.3 * (1 + 0.12 * math.sin(3 * th)), sides=12, step=0.6)
    thumb = bm_obj("thumb", bm)
    displace(thumb, canyon_disp(amp=0.35, freq=0.15, strata=0.15, layer=2.6, flute=0.35, flute_f=0.4, seed=6.5))
    split_long(thumb)
    o = join([o, thumb], "side_butte")
    mesh.smooth(o, angle=58)
    mat.assign(o, canyon_rock_mat("ButteRock", scale=5.0, band_scale=0.11, strata=0.9, varnish=0.8, seed=6.0,
                                  tint="#e0925e"))
    lo, hi = mesh.bounds(o, world=False)
    origin_to(o, (lo.x, 0.0, 0.0))
    o["atlas_weight"] = 0.45
    return extras(o, "far", 110, 0.6)


# ---------------------------------------------------------------- rails: cable on weathered posts

@piece
def build_rail_canyon():
    wood = m_wood("RailPost", "#9a8672")
    cable = m_rubber("RailCable", "#221c18")
    glass = m_glass_insulator("RailInsulator")
    bm = bmesh.new()
    pts = [Vector((0.0, y, 1.0 - 0.025 * math.sin(math.pi * y))) for y in (0.0, 0.25, 0.5, 0.75, 1.0)]
    tube(bm, pts, 0.1, sides=8, caps=False)
    c = bm_obj("cable", bm)
    mat.assign(c, cable)
    post = mesh.box("post", (0.11, 0.11, 0.86), location=(0, 0.5, 0.43))
    delete_bottom(post)
    mat.assign(post, wood)
    ins = mesh.cylinder("ins", 0.06, 0.08, verts=6, location=(0, 0.5, 0.9))
    mat.assign(ins, glass)
    o = join([c, post, ins], "rail_canyon")
    mesh.smooth(o, angle=40)
    o["atlas_weight"] = 15.0
    return o


def delete_bottom(o):
    delete_faces(o, lambda c, n: n.z < -0.9)


@piece
def build_rail_end():
    """The sloped start: the cable rises out of an anchor stake from z 0 at y -1.5 to 1.0 at y 0."""
    wood = m_wood("RailPost", "#9a8672")
    cable = m_rubber("RailCable", "#221c18")
    bm = bmesh.new()
    pts = [Vector((0.0, -1.5 + 1.5 * t, 0.12 + 0.88 * (t ** 0.8))) for t in [i / 6 for i in range(7)]]
    tube(bm, pts, 0.1, sides=8, caps=False)
    c = bm_obj("cable_up", bm)
    mat.assign(c, cable)
    stake = mesh.box("stake", (0.16, 0.16, 0.5), location=(0, -1.55, 0.2), bevel=0.02, segments=1)
    stake.rotation_euler = (0.35, 0, 0)
    mat.assign(stake, wood)
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=1, radius=0.28, matrix=Matrix.Translation((0.05, -1.7, 0.02)))
    rock = bm_obj("anchor_rock", bm)
    displace(rock, lambda co, n: 0.05 * noise.noise(co * 4))
    mat.assign(rock, canyon_rock_mat("AnchorRock", seed=7.0))
    o = join([c, stake, rock], "rail_end")
    mesh.smooth(o, angle=40)
    o["atlas_weight"] = 10.0
    return o


# ================================================================ sky panorama (Cycles, equirectangular)

def build_sky(path):
    lib.reset_scene()
    sc = bpy.context.scene
    w = bpy.data.worlds.new("SkyWorld")
    sc.world = w
    nt = w.node_tree
    nt.nodes.clear()
    N = nt.nodes.new
    L = nt.links.new
    tc = N("ShaderNodeTexCoord")
    d = tc.outputs["Generated"]  # view direction in world shaders
    sep = N("ShaderNodeSeparateXYZ")
    L(d, sep.inputs[0])
    # gradient by elevation
    ramp = N("ShaderNodeValToRGB")
    L(sep.outputs[2], ramp.inputs[0])
    cr = ramp.color_ramp
    stops = [(0.0, "#ff8c3c"), (0.035, "#f06a3a"), (0.09, "#c9465a"), (0.18, "#7c3468"), (0.32, "#3b2560"),
             (0.55, "#17143a"), (1.0, "#080a1c")]
    for i, (pos, col) in enumerate(stops):
        e = cr.elements[i] if i < 2 else cr.elements.new(pos)
        e.position = pos
        e.color = mat.rgba(col)
    # sun glow just below the horizon, a little left of forward
    sun_dir = Vector((math.sin(math.radians(-24)), math.cos(math.radians(-24)), -0.03)).normalized()
    dot = N("ShaderNodeVectorMath")
    dot.operation = "DOT_PRODUCT"
    L(d, dot.inputs[0])
    dot.inputs[1].default_value = sun_dir
    mx = N("ShaderNodeMath")
    mx.operation = "MAXIMUM"
    L(dot.outputs["Value"], mx.inputs[0])
    mx.inputs[1].default_value = 0.0
    pw = N("ShaderNodeMath")
    pw.operation = "POWER"
    L(mx.outputs[0], pw.inputs[0])
    pw.inputs[1].default_value = 6.0
    pw2 = N("ShaderNodeMath")
    pw2.operation = "POWER"
    L(mx.outputs[0], pw2.inputs[0])
    pw2.inputs[1].default_value = 60.0
    # elevation mask: the glow hugs the horizon
    el = N("ShaderNodeMapRange")
    L(sep.outputs[2], el.inputs["Value"])
    el.inputs["From Min"].default_value = 0.35
    el.inputs["From Max"].default_value = -0.02
    glow_m = N("ShaderNodeMath")
    glow_m.operation = "MULTIPLY"
    L(pw.outputs[0], glow_m.inputs[0])
    L(el.outputs["Result"], glow_m.inputs[1])
    add = N("ShaderNodeMath")
    add.operation = "MULTIPLY_ADD"
    L(glow_m.outputs[0], add.inputs[0])
    add.inputs[1].default_value = 1.4
    L(pw2.outputs[0], add.inputs[2])
    glow_col = N("ShaderNodeMix")
    glow_col.data_type = "RGBA"
    glow_col.blend_type = "ADD"
    L(add.outputs[0], glow_col.inputs[0])
    L(ramp.outputs["Color"], glow_col.inputs[6])
    glow_col.inputs[7].default_value = mat.rgba("#ffb45a")
    # thin high clouds catching the last light
    cl_map = N("ShaderNodeMapping")
    L(d, cl_map.inputs["Vector"])
    cl_map.inputs["Scale"].default_value = (2.0, 2.0, 11.0)
    cl = N("ShaderNodeTexNoise")
    L(cl_map.outputs[0], cl.inputs["Vector"])
    cl.inputs["Scale"].default_value = 3.0
    cl.inputs["Detail"].default_value = 6.0
    cl.inputs["Roughness"].default_value = 0.6
    cl_r = N("ShaderNodeMapRange")
    L(cl.outputs["Fac"], cl_r.inputs["Value"])
    cl_r.inputs["From Min"].default_value = 0.56
    cl_r.inputs["From Max"].default_value = 0.72
    cl_el = N("ShaderNodeMapRange")
    L(sep.outputs[2], cl_el.inputs["Value"])
    cl_el.inputs["From Min"].default_value = 0.03
    cl_el.inputs["From Max"].default_value = 0.16
    cl_el2 = N("ShaderNodeMapRange")
    L(sep.outputs[2], cl_el2.inputs["Value"])
    cl_el2.inputs["From Min"].default_value = 0.4
    cl_el2.inputs["From Max"].default_value = 0.2
    cm = N("ShaderNodeMath")
    cm.operation = "MULTIPLY"
    L(cl_r.outputs["Result"], cm.inputs[0])
    L(cl_el.outputs["Result"], cm.inputs[1])
    cm2 = N("ShaderNodeMath")
    cm2.operation = "MULTIPLY"
    L(cm.outputs[0], cm2.inputs[0])
    L(cl_el2.outputs["Result"], cm2.inputs[1])
    cm3 = N("ShaderNodeMath")
    cm3.operation = "MULTIPLY"
    L(cm2.outputs[0], cm3.inputs[0])
    cm3.inputs[1].default_value = 0.55
    cloud = N("ShaderNodeMix")
    cloud.data_type = "RGBA"
    L(cm3.outputs[0], cloud.inputs[0])
    L(glow_col.outputs[2], cloud.inputs[6])
    cloud.inputs[7].default_value = mat.rgba("#e0706a")
    # stars: sparse voronoi points, fading toward the horizon
    vor = N("ShaderNodeTexVoronoi")
    L(d, vor.inputs["Vector"])
    vor.inputs["Scale"].default_value = 140.0
    st = N("ShaderNodeMapRange")
    L(vor.outputs["Distance"], st.inputs["Value"])
    st.inputs["From Min"].default_value = 0.1
    st.inputs["From Max"].default_value = 0.02
    pick = N("ShaderNodeSeparateColor")
    L(vor.outputs["Color"], pick.inputs[0])
    gate = N("ShaderNodeMath")
    gate.operation = "GREATER_THAN"
    L(pick.outputs[0], gate.inputs[0])
    gate.inputs[1].default_value = 0.93
    sel = N("ShaderNodeMath")
    sel.operation = "MULTIPLY"
    L(st.outputs["Result"], sel.inputs[0])
    L(gate.outputs[0], sel.inputs[1])
    s_el = N("ShaderNodeMapRange")
    L(sep.outputs[2], s_el.inputs["Value"])
    s_el.inputs["From Min"].default_value = 0.12
    s_el.inputs["From Max"].default_value = 0.6
    s2 = N("ShaderNodeMath")
    s2.operation = "MULTIPLY"
    L(sel.outputs[0], s2.inputs[0])
    L(s_el.outputs["Result"], s2.inputs[1])
    s3 = N("ShaderNodeMath")
    s3.operation = "MULTIPLY"
    L(s2.outputs[0], s3.inputs[0])
    L(pick.outputs[1], s3.inputs[1])
    s4 = N("ShaderNodeMath")
    s4.operation = "MULTIPLY"
    L(s3.outputs[0], s4.inputs[0])
    s4.inputs[1].default_value = 3.5
    star = N("ShaderNodeMix")
    star.data_type = "RGBA"
    star.blend_type = "ADD"
    L(s4.outputs[0], star.inputs[0])
    L(cloud.outputs[2], star.inputs[6])
    star.inputs[7].default_value = (0.9, 0.92, 1.0, 1.0)
    bg = N("ShaderNodeBackground")
    L(star.outputs[2], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = 1.0
    out = N("ShaderNodeOutputWorld")
    L(bg.outputs[0], out.inputs["Surface"])

    sun_flat = Vector((sun_dir.x, sun_dir.y, 0.0)).normalized()

    def hazed(name, color, rough=0.9, haze=(150.0, 2600.0), far_k=0.94):
        """Principled mixed toward a haze colour with camera distance (aerial
        perspective); the haze is warm toward the afterglow, violet away from it."""
        m = mat.new_material(name)
        g = G(m)
        g.out(color, rough, None, 0.0)
        ntm = m.node_tree
        outn = next(n for n in ntm.nodes if n.type == "OUTPUT_MATERIAL")
        cam = g.n("ShaderNodeCameraData")
        f = g.maprange(cam.outputs["View Distance"], haze[0], haze[1], 0.0, far_k)
        f = g.math("POWER", f, 0.75)
        toward = g.maprange(g.vmath("DOT_PRODUCT", g.vmath("SCALE", g.geo("Incoming"), scale=-1.0), sun_flat), 0.2, 1.0)
        hc = g.mixc(g.math("POWER", toward, 2.0), "#3c2240", "#c8604a")
        em = g.n("ShaderNodeEmission")
        g.ln(hc, em.inputs["Color"])
        em.inputs["Strength"].default_value = 1.0
        mix = g.n("ShaderNodeMixShader")
        g.ln(f, mix.inputs[0])
        g.ln(g.p.outputs[0], mix.inputs[1])
        g.ln(em.outputs[0], mix.inputs[2])
        g.ln(mix.outputs[0], outn.inputs["Surface"])
        return m

    # desert floor (flat: the camera is 4 m up, the horizon sits on the middle row)
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=120, y_segments=120, size=9000)
    ground = bm_obj("ground", bm)
    ground.data.materials.append(hazed("Floor", "#2a130b", 0.95, haze=(30, 2200), far_k=0.9))
    import random
    rnd = random.Random(11)

    def sky_rock(k, cx, cy, width, h, kind, elong, rot, tier=True):
        """Mesa / butte / spire: cap rock, fluted cliff, talus skirt; mesas may
        carry a second, narrower tier."""
        seed = rnd.uniform(0, 100)
        sides = 48
        zs = [-6.0] + [h * t for t in (0.04, 0.1, 0.17, 0.25, 0.33, 0.42, 0.52, 0.62, 0.72, 0.8, 0.86, 0.9, 0.94,
                                       0.975, 1.0)]
        talus = {"mesa": 0.34, "butte": 0.42, "spire": 0.3}[kind]
        skirt = {"mesa": 0.8, "butte": 1.5, "spire": 2.6}[kind]
        bm = bmesh.new()
        rings = []
        for z in zs:
            ring = []
            t = z / h
            for i in range(sides):
                th = TAU * i / sides
                c, s_ = math.cos(th), math.sin(th)
                plan = 1.0 + 0.3 * noise.noise(Vector((c * 1.2 + seed, s_ * 1.2, 0.0))) \
                    + 0.12 * noise.noise(Vector((c * 3.1 + seed, s_ * 3.1, 1.0)))
                base = width * plan
                prof = 1.0 + skirt * smoothstep(talus, -0.05, t) ** 1.7
                if t > 0.84:
                    prof *= 1.0 - 0.07 * smoothstep(0.84, 0.9, t) + 0.08 * smoothstep(0.9, 0.95, t)
                flute = abs(noise.noise(Vector((c * 11 + seed, s_ * 11, t * 1.5))))
                gully = -0.16 * flute * (0.3 + 0.7 * smoothstep(0.1, 0.8, t))
                r = base * (prof + gully)
                x, y = c * r * elong ** 0.5, s_ * r / elong ** 0.5
                xr = x * math.cos(rot) - y * math.sin(rot)
                yr = x * math.sin(rot) + y * math.cos(rot)
                top = z
                if z >= h:
                    top = h * (1.0 + 0.015 * noise.noise(Vector((c * 3 + seed, s_ * 3, 5.0))))
                ring.append(bm.verts.new((cx + xr, cy + yr, top)))
            rings.append(ring)
        for a, b in zip(rings, rings[1:]):
            quad_strip(bm, a, b)
        bm.faces.new(rings[-1])
        o = bm_obj(f"rock{k}", bm)
        shade = rnd.choice(("#2e140c", "#26100b", "#341710"))
        o.data.materials.append(hazed(f"Far{k}", shade, 0.9))
        mesh.smooth(o, angle=35)
        if tier and kind == "mesa" and rnd.random() < 0.55:
            ang = rnd.uniform(0, TAU)
            off = width * 0.25
            sky_rock(k + 1000, cx + math.cos(ang) * off, cy + math.sin(ang) * off, width * rnd.uniform(0.35, 0.6),
                     h * rnd.uniform(1.25, 1.5), "butte", elong, rot, tier=False)

    # three distance bands; keep the view straight down the track fairly open
    k = 0
    glow_az = math.degrees(math.atan2(sun_dir.x, sun_dir.y))
    for band, (d0, d1, n, hmin, hmax) in enumerate(((420, 900, 12, 45, 95), (1000, 2000, 22, 70, 170),
                                                     (2200, 5200, 34, 120, 320))):
        placed = 0
        while placed < n:
            az = rnd.uniform(-math.pi, math.pi)
            dist = rnd.uniform(d0, d1)
            a = math.degrees(az)
            if band < 2 and (abs(a) < 18 or abs(a - glow_az) < 26):
                continue  # a clear window down the track and toward the afterglow
            kind = rnd.choices(("mesa", "butte", "spire"), (0.55, 0.33, 0.12))[0]
            h = rnd.uniform(hmin, hmax) * (0.65 if kind == "mesa" else 1.0)
            width = h * {"mesa": rnd.uniform(1.2, 2.6), "butte": rnd.uniform(0.45, 0.8), "spire": rnd.uniform(0.1, 0.18)}[kind]
            sky_rock(k, math.sin(az) * dist, math.cos(az) * dist, width, h, kind, rnd.uniform(1.0, 2.4),
                     rnd.uniform(0, math.pi))
            k += 1
            placed += 1
    # double-tick saguaro silhouettes and a telegraph line near the camera
    for k in range(7):
        az = math.radians(rnd.choice([-1, 1]) * rnd.uniform(30, 150))
        dist = rnd.uniform(90, 260)
        bm = bmesh.new()
        base = Vector((math.sin(az) * dist, math.cos(az) * dist, -4.0))
        for off in (0.0, 4.0):
            b = base + Vector((math.cos(az) * off, -math.sin(az) * off, 0))
            tube(bm, [b, b + Vector((math.cos(az) * 2.0, -math.sin(az) * 2.0, 10))], 0.6, sides=8)
            tube(bm, [b + Vector((0, 0, 2)), b + Vector((-math.cos(az) * 2.0, math.sin(az) * 2.0, 5.5))], 0.45, sides=8)
        o = bm_obj(f"cactus{k}", bm)
        o.data.materials.append(hazed(f"Cactus{k}", "#12140c", 0.8, haze=(60, 1500)))
    bm = bmesh.new()
    for i in range(40):
        y = 40 + i * 55
        x = -70 - i * 3.0
        tube(bm, [(x, y, -4), (x, y, 7)], 0.25, sides=6)
        tube(bm, [(x - 1.2, y, 6.5), (x + 1.2, y, 6.5)], 0.12, sides=4)
    for i in range(39):
        a = Vector((-70 - i * 3.0, 40 + i * 55, 6.6))
        b = Vector((-70 - (i + 1) * 3.0, 40 + (i + 1) * 55, 6.6))
        tube(bm, wire_pts(a, b, 1.5, 8), 0.05, sides=3, caps=False)
    o = bm_obj("poles", bm)
    o.data.materials.append(hazed("Poles", "#140c08", 0.8, haze=(60, 1500)))

    # low sun from the glow direction for warm rims on the mesas
    sd = bpy.data.lights.new("sun", "SUN")
    sd.energy = 2.5
    sd.color = mat.rgb("#ff9a50")
    sd.angle = math.radians(3)
    sun = lib.link(bpy.data.objects.new("sun", sd))
    light_from = Vector((sun_dir.x, sun_dir.y, 0.07)).normalized()
    sun.rotation_euler = (-light_from).to_track_quat("-Z", "Y").to_euler()
    render_equirect(path, SKY_SAMPLES)


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


# ================================================================ game view (review)

def feed_image(name, w=256, h=540, seed=1):
    """A stand-in for the renderer's chat feed on the lane screens."""
    import random
    import numpy as np
    rnd = random.Random(seed)
    a = np.zeros((h, w, 4), dtype=np.float32)
    a[..., 0], a[..., 1], a[..., 2], a[..., 3] = 0.07, 0.043, 0.031, 1
    a[h - 58:, :, :3] = (0.165, 0.10, 0.07)
    y = h - 80
    while y > 60:
        mine = rnd.random() < 0.45
        bw = rnd.randint(90, 180)
        bh = rnd.randint(28, 60)
        x0 = w - 14 - bw if mine else 14
        col = (0.95, 0.55, 0.22) if mine else (0.28, 0.2, 0.16)
        a[y - bh:y, x0:x0 + bw, :3] = col
        y -= bh + rnd.randint(10, 24)
    img = bpy.data.images.new(name, w, h)
    img.pixels.foreach_set(a.ravel())
    img.pack()
    return img


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


def soften_normal(img, k=0.5):
    """Blend the baked normal map toward a 3x3 blur: texel-level noise the phone
    can't show anyway, and it keeps the UASTC normal map (and the glb) small."""
    import numpy as np
    a = bake.pixels(img)
    b = a.copy()
    acc = np.zeros_like(a[..., :3])
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            acc += np.roll(np.roll(a[..., :3], dy, 0), dx, 1)
    b[..., :3] = a[..., :3] * (1 - k) + acc / 9.0 * k
    bake.set_pixels(img, b)
    img.save()
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


# ================================================================ main

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

    # report
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
            show = [o for n, o in objs.items() if n not in ("deck_seam",)]
            review(PREVIEW, show, samples=16)
            if "deck" in objs:
                game_view(os.path.join(PREVIEW, "game_src.png"), objs["deck"], objs.get("deck_seam"), scenery, LOOK,
                          SKY_OUT, overhang=objs.get("overhang"), rail=objs.get("rail_canyon"),
                          rail_end=objs.get("rail_end"), samples=16)
        return

    # bake everything but the seams (the renderer draws them) into one atlas; the
    # hidden rock bases (below -6 m), the tunnel's outer shell and portal get few texels
    splits = {}
    for n, o in objs.items():
        if n.startswith("side_"):
            w = o.get("atlas_weight", 1.0)
            splits[n] = [split_faces(o, lambda c, nn: c.z < -6.0, n + "_low", w * 0.12)]
        elif n == "deck":
            splits[n] = [split_faces(o, lambda c, nn: c.z < -0.12, n + "_under", 5.0)]
        elif n == "tunnel":
            inner = lambda c, nn: abs(c.x) < 8.3 and c.z > -8.6 and c.z < 12.6 and abs(nn.y) < 0.6  # noqa: E731
            splits[n] = [split_faces(o, lambda c, nn: not inner(c, nn), n + "_shell", 0.25)]
    atlas_objs = [o for n, o in objs.items() if n != "deck_seam"] + [p for v in splits.values() for p in v if p]
    if lib.flag("pack-test"):
        for o in atlas_objs:
            mesh.apply_modifiers(o, only=[m.name for m in o.modifiers if m.type != "ARMATURE"])
        unwrap_all(atlas_objs)
        log(f"islands: {count_islands(atlas_objs)}", sorted(((count_islands([o]), o.name) for o in atlas_objs), reverse=True)[:6],
            "uv layers", sorted({l.name for o in atlas_objs for l in o.data.uv_layers}))
        mesh.pack_uvs_to_atlas(atlas_objs, size=SIZE, margin_px=MARGIN, layer="Atlas", unwrap="keep",
                               skip_materials=("Seam",))
        uv_overlaps(atlas_objs)
        log(f"atlas coverage {100 * uv_area(atlas_objs):.0f}%")
        return
    unwrap_all(atlas_objs)
    log(f"islands: {count_islands(atlas_objs)}")
    res = bake.bake_kit_atlas(atlas_objs, SIZE, TEX_DIR, unwrap="keep", margin_px=MARGIN, name="CanyonKit", keep_materials=("Seam",), ao_samples=48,
                              ao_distance=1.2, samples=6)
    uv_overlaps(atlas_objs)
    for n, o in objs.items():
        if n != "deck_seam":
            log(f"  {n:18s} {texel_density(o):6.1f} px/m" + (
                f"  (low part {texel_density(splits[n][0]):.1f})" if splits.get(n) and splits[n][0] else ""))
    for n, parts in splits.items():
        join_back(objs[n], parts)
    halve_normal(res)
    log("atlas", res["paths"], "emissive strength", round(res["emissive_strength"], 2))
    for o in pieces:
        me = o.data
        for a in list(me.color_attributes):
            me.color_attributes.remove(a)
    path = export.export_glb(OUT, pieces)
    export.compress(path, max_texture=SIZE, inspect=True)
    log(f"glb {os.path.getsize(path) // 1024} KB")
    if PREVIEW:
        os.makedirs(PREVIEW, exist_ok=True)
        show = [o for n, o in objs.items() if n not in ("deck_seam",)]
        review(PREVIEW, show)
        game_view(os.path.join(PREVIEW, "game.png"), objs["deck"], objs.get("deck_seam"), scenery, LOOK, SKY_OUT,
                  overhang=objs.get("overhang"), rail=objs.get("rail_canyon"), rail_end=objs.get("rail_end"))
        game_view(os.path.join(PREVIEW, "game_tunnel.png"), objs["deck"], objs.get("deck_seam"), scenery, LOOK,
                  SKY_OUT, tunnel=objs.get("tunnel"), tunnel_span=(14.0, 120.0))
        game_view(os.path.join(PREVIEW, "game_inside.png"), objs["deck"], objs.get("deck_seam"), scenery, LOOK,
                  SKY_OUT, tunnel=objs.get("tunnel"), tunnel_span=(-30.0, 90.0))


main()
