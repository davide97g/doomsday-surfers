# Common prop kit (docs/assets-v2.md "Common prop kit"): the reel train
# modules and its stairs, barriers, healthy habits, the Thumb, pads, pickups,
# power-ups, the jetpack and the grind rails. Everything is modelled
# procedurally here (bmesh), textured with CC0 sets + procedural shaders,
# baked into one 2048 atlas (albedo/normal/ORM/emissive) and exported to
# public/assets/kits/common.glb (meshopt + KTX2).
#
#   blender -b -P assets/blender/kits/common.py -- [--preview <dir>] [--game]
#       [--only train_front,thumb,...] [--no-bake] [--out path.glb] [--size 2048]
#
# --only builds a subset (for review); --no-bake skips bake + export and
# previews the procedural source materials. Runtime faces (ReelScreen,
# ReelFront, NotifFace, AdFace, MumFace, RampFace, AutoplayBelt, Warn, Glass)
# keep their own material and a clean 0..1 UV; previews paint placeholder
# canvases on them, the export never does.
#
# Frames (Blender, Z up, +Y forward = down the track):
#   train_front  front face at y 0, body y 0..1, 2.0 wide, roof at z 2.8
#   train_mid    y 0..2 seamless module          train_back  y 0..1 (rear face at y 1)
#   train_stairs z 0 at y -7 up to z 2.8 at y 0 (origin: top end, ground)
#   train_warn   in train_front's frame (sits on the roof near the front)
#   barriers/habits: origin at the ground, centre of depth
#   thumb        y 0 (near end, origin) .. 8, nail at the far end facing up
#   pads         origin at the near edge (y 0), extending +Y. pad_bouncer (base),
#                pad_bouncer_spring (z 0.08..0.36) and pad_bouncer_top (z 0.36..0.49)
#                share that origin: squash the spring with scale.y, lower the top
#   pickups / power-ups centred at the origin (faces toward -Y, readable from both sides)
#   att_jetpack  origin = attach point on the spine, pack behind it (-Y), straps forward
#   rails        1 m capped modules y 0..1, top at z 1.1; rail_end y -1.5..0 (USB-C plug
#                plugged into the track); extra rail_pipe_end, the same for rail_pipe
#
# The CC0 diamond plate (DiamondPlate008A, ambientCG) is not in the texture
# manifest yet; without it the walkway falls back to a procedural plate.

import math
import os
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

OUT = lib.arg("out", os.path.join(lib.PUBLIC, "kits", "common.glb"))
PREVIEW = lib.arg("preview")
SIZE = lib.arg("size", 2048, int)
ONLY = [s for s in (lib.arg("only") or "").split(",") if s]
NO_BAKE = lib.flag("no-bake")
GAME = lib.flag("game")
VIEWS = tuple((lib.arg("views") or "back_three_quarter,back,side,three_quarter").split(","))
TEX_DIR = os.path.join(lib.TOOLS, "cache", "common", "textures")
RUNTIME = ("ReelScreen", "ReelFront", "NotifFace", "AdFace", "MumFace", "RampFace", "AutoplayBelt", "Warn", "Glass")
TAU = math.tau

lib.reset_scene()


# ============================================================== geometry helpers

def V(x, y, z):
    return Vector((x, y, z))


def rrect(w, h, r, seg=4, cx=0.0, cy=0.0):
    """Rounded-rectangle outline, CCW in (u right, v up). r: float or
    (bl, br, tr, tl); seg: int or per corner. Always (seg+1) points per corner
    (a zero radius repeats the corner point), so outlines of different sizes
    loft together."""
    rs = r if isinstance(r, (tuple, list)) else (r, r, r, r)
    ss = seg if isinstance(seg, (tuple, list)) else (seg, seg, seg, seg)
    hw, hh = w / 2, h / 2
    spec = [((cx + hw, cy - hh), (-1, 1), -90, rs[1], ss[1]), ((cx + hw, cy + hh), (-1, -1), 0, rs[2], ss[2]),
            ((cx - hw, cy + hh), (1, -1), 90, rs[3], ss[3]), ((cx - hw, cy - hh), (1, 1), 180, rs[0], ss[0])]
    pts = []
    for (px, py), (sx, sy), a0, rc, sc in spec:
        rc = max(rc, 0.0)
        ccx, ccy = px + sx * rc, py + sy * rc
        for k in range(sc + 1):
            a = math.radians(a0 + 90 * k / sc)
            pts.append((ccx + rc * math.cos(a), ccy + rc * math.sin(a)))
    return pts


def stadium(w, h, seg=6, cx=0.0, cy=0.0):
    r = min(w, h) / 2 - 1e-5
    return rrect(w, h, r, seg, cx, cy)


def circle(r, n, cx=0.0, cy=0.0, a0=0.0):
    return [(cx + r * math.cos(a0 + TAU * i / n), cy + r * math.sin(a0 + TAU * i / n)) for i in range(n)]


def heart_outline(w, h, n=24):
    """Heart, CCW, width w, height h, centred on its bounding box."""
    pts = []
    for i in range(n):
        t = TAU * i / n
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append((x, y))
    pts = pts[::-1] if _area(pts) < 0 else pts
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    sx, sy = w / (max(xs) - min(xs)), h / (max(ys) - min(ys))
    mx, my = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    return [((x - mx) * sx, (y - my) * sy) for x, y in pts]


def _area(pts):
    return 0.5 * sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
                     for i in range(len(pts)))


def ccw(pts):
    return pts if _area(pts) > 0 else pts[::-1]


def to3(uv, axis="Y", d=0.0):
    """(u, v) outline point + depth d along `axis` -> xyz. Y: (u, d, v); Z: (u, v, d); X: (d, u, v)."""
    u, v = uv
    return {"Y": V(u, d, v), "Z": V(u, v, d), "X": V(d, u, v)}[axis]


def new_bm():
    bm = bmesh.new()
    bm.loops.layers.uv.new("UVMap")
    return bm


def finish(name, bm, material=None, recalc=True, merge=1e-5, smooth=None):
    if merge:
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=merge)
    bad = [f for f in bm.faces if f.calc_area() < 1e-10]
    if bad:
        bmesh.ops.delete(bm, geom=bad, context="FACES")
    if recalc:
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    o = mesh.new_object(name, bm)
    if material is not None:
        mat.assign(o, material)
    if smooth is not None:
        mesh.smooth(o, smooth)
    return o


def loft_bm(bm, rings, closed=True, cap0=False, cap1=False):
    vs = [[bm.verts.new(Vector(p)) for p in r] for r in rings]
    n = len(rings[0])
    for j in range(len(vs) - 1):
        for i in range(n if closed else n - 1):
            i2 = (i + 1) % n
            try:
                bm.faces.new((vs[j][i], vs[j][i2], vs[j + 1][i2], vs[j + 1][i]))
            except ValueError:
                pass
    caps = []
    if cap0:
        caps.append(bm.faces.new(list(reversed(vs[0]))))
    if cap1:
        caps.append(bm.faces.new(vs[-1]))
    return vs, caps


def loft(name, rings, material=None, closed=True, cap0=False, cap1=False, smooth=None, recalc=True):
    bm = new_bm()
    loft_bm(bm, rings, closed, cap0, cap1)
    return finish(name, bm, material, recalc=recalc, smooth=smooth)


def prism(name, outline, d0, d1, axis="Y", material=None, bevel=0.0, bseg=2, angle=30.0, smooth=None,
          cuts=None):
    """Outline (u, v) extruded from d0 to d1 along axis, capped. Optional
    bevel of the sharp edges (bmesh, real geometry). cuts: extra rings at
    these depths (edge loops for the bend)."""
    outline = ccw(outline)
    depths = sorted(set([d0, d1] + list(cuts or [])))
    rings = [[to3(p, axis, d) for p in outline] for d in depths]
    bm = new_bm()
    loft_bm(bm, rings, True, True, True)
    if bevel > 0:
        bevel_bm(bm, bevel, bseg, angle)
    return finish(name, bm, material, smooth=smooth)


def bevel_bm(bm, width, seg=2, angle=30.0):
    bm.normal_update()
    edges = [e for e in bm.edges if len(e.link_faces) == 2 and e.calc_face_angle(0) > math.radians(angle)]
    if edges:
        bmesh.ops.bevel(bm, geom=edges, offset=width, segments=seg, profile=0.5, affect="EDGES", clamp_overlap=True)


def lathe(name, prof, segs=16, axis="Z", material=None, a0=0.0, a1=TAU, smooth=None, center=(0, 0, 0), recalc=True):
    """Revolve a (radius, height) profile around `axis` through `center`."""
    full = abs(a1 - a0 - TAU) < 1e-6
    n = segs if full else segs + 1
    rings = []
    for r, h in prof:
        ring = []
        for i in range(n):
            a = a0 + (a1 - a0) * i / segs
            c, s = math.cos(a) * r, math.sin(a) * r
            p = {"Z": V(c, s, h), "Y": V(c, h, s), "X": V(h, c, s)}[axis]
            ring.append(p + Vector(center))
        rings.append(ring)
    bm = new_bm()
    loft_bm(bm, rings, closed=full)
    return finish(name, bm, material, smooth=smooth, recalc=recalc)


def frames(pts, closed=False, up=None):
    """Parallel-transport frames (T, N, B) along a polyline."""
    P = [Vector(p) for p in pts]
    n = len(P)
    T = []
    for i in range(n):
        if closed:
            t = P[(i + 1) % n] - P[i - 1]
        elif i == 0:
            t = P[1] - P[0]
        elif i == n - 1:
            t = P[-1] - P[-2]
        else:
            t = P[i + 1] - P[i - 1]
        T.append(t.normalized())
    ref = Vector(up) if up else (V(0, 0, 1) if abs(T[0].z) < 0.9 else V(1, 0, 0))
    N0 = (ref - T[0] * ref.dot(T[0])).normalized()
    N = [N0]
    for i in range(1, n):
        v = N[-1] - T[i] * N[-1].dot(T[i])
        N.append(v.normalized() if v.length > 1e-9 else N[-1])
    B = [T[i].cross(N[i]) for i in range(n)]
    return P, T, N, B


def tube(name, pts, r, sides=8, material=None, closed=False, caps=True, smooth=40.0, up=None, section=None,
         twist=0.0):
    """Tube along a polyline. r: float or list per point. section: optional
    list of (u, v) unit-ish points replacing the circle (scaled by r)."""
    P, T, N, B = frames(pts, closed, up)
    rs = r if isinstance(r, (list, tuple)) else [r] * len(P)
    sec = section or [(math.cos(TAU * k / sides), math.sin(TAU * k / sides)) for k in range(sides)]
    rings = []
    for i, p in enumerate(P):
        a = twist * i
        ca, sa = math.cos(a), math.sin(a)
        ring = []
        for u, v in sec:
            uu, vv = u * ca - v * sa, u * sa + v * ca
            ring.append(p + (N[i] * uu + B[i] * vv) * rs[i])
        rings.append(ring)
    if closed:
        rings.append(rings[0])
        P = P + [P[0]]
    bm = new_bm()
    vs, capf = loft_bm(bm, rings, True, caps and not closed, caps and not closed)
    # orient each wall face away from its path segment, caps along the path
    bm.normal_update()
    ring_of = {}
    for j, r in enumerate(vs):
        for v in r:
            ring_of[v] = j
    for f in bm.faces:
        c = f.calc_center_median()
        js = sorted({ring_of[v] for v in f.verts})
        if len(js) >= 2:
            mid = (P[js[0]] + P[js[-1]]) / 2
            d = c - mid
        else:
            j = js[0]
            d = -T[0] if j == 0 else T[-1]
        if f.normal.dot(d) < 0:
            f.normal_flip()
    return finish(name, bm, material, smooth=smooth, recalc=False)


def helix(r, height, turns, n_per_turn=12, z0=0.0, cx=0.0, cy=0.0, wire=0.03, end_turns=0.8):
    """Compression spring centreline: closed end coils (pitch = wire
    diameter) and an open middle, from z0 to z0 + height."""
    n = int(turns * n_per_turn)
    p_end = 2 * wire * 1.05
    mid_turns = turns - 2 * end_turns
    p_mid = (height - 2 * wire - 2 * end_turns * p_end) / max(mid_turns, 1e-3)
    pts, z = [], z0 + wire
    for i in range(n + 1):
        t = i / n_per_turn
        a = TAU * t
        pts.append(V(cx + r * math.cos(a), cy + r * math.sin(a), z))
        tm = t + 0.5 / n_per_turn
        z += (p_end if (tm < end_turns or tm > turns - end_turns) else p_mid) / n_per_turn
    return pts


def frame_ring(name, outer, inner, d_front, d_back, axis="Y", material=None, inside=None):
    """A lip/bezel: flat ring between two outlines at depth d_front plus the
    inner wall back to d_back. Faces are oriented away from `inside`."""
    bm = new_bm()
    ro = [bm.verts.new(to3(p, axis, d_front)) for p in ccw(outer)]
    ri = [bm.verts.new(to3(p, axis, d_front)) for p in ccw(inner)]
    rb = [bm.verts.new(to3(p, axis, d_back)) for p in ccw(inner)]
    n = len(ro)
    assert len(ri) == n
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((ro[i], ro[j], ri[j], ri[i]))
        bm.faces.new((ri[i], ri[j], rb[j], rb[i]))
    o = finish(name, bm, material, recalc=False)
    # front ring faces along the depth axis, inner wall toward the middle
    ax = {"X": 0, "Y": 1, "Z": 2}[axis]
    sgn = 1 if d_front > d_back else -1
    bm = bmesh.new()
    bm.from_mesh(o.data)
    cen = sum((v.co for v in bm.verts), Vector()) / len(bm.verts)
    for f in bm.faces:
        c = f.calc_center_median()
        if abs(f.normal[ax]) > 0.7 or abs(c[ax] - d_front) < 1e-6 and all(abs(v.co[ax] - d_front) < 1e-6 for v in f.verts):
            d = Vector((0, 0, 0))
            d[ax] = sgn
        else:
            d = cen - c
            d[ax] = 0
        if f.normal.dot(d) < 0:
            f.normal_flip()
    bm.to_mesh(o.data)
    bm.free()
    return o


def box(name, x0, x1, y0, y1, z0, z1, material=None, bevel=0.0, seg=2):
    o = mesh.box(name, (x1 - x0, y1 - y0, z1 - z0), ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2), bevel=bevel,
                 segments=seg)
    mesh.apply_transform(o)
    if material is not None:
        mat.assign(o, material)
    return o


def quad(name, corners, material=None):
    bm = new_bm()
    bm.faces.new([bm.verts.new(Vector(c)) for c in corners])
    return finish(name, bm, material, recalc=False)


def strip(name, pts_a, pts_b, material=None):
    """Quad strip between two point rows (a -> b is the face's 'up')."""
    bm = new_bm()
    loft_bm(bm, [pts_a, pts_b], closed=False)
    return finish(name, bm, material, recalc=False)


def xform(o, loc=(0, 0, 0), rot=(0, 0, 0), scale=(1, 1, 1)):
    """Bake a transform into the mesh (rotation XYZ Euler, radians)."""
    from mathutils import Euler
    m = Matrix.Translation(Vector(loc)) @ Euler(rot).to_matrix().to_4x4() @ Matrix.Diagonal((*scale, 1.0))
    o.data.transform(m)
    o.data.update()
    return o


def mirror_x(o, name=None):
    c = mesh.duplicate(o, name or o.name + "_mx")
    c.data.transform(Matrix.Diagonal((-1, 1, 1, 1)))
    c.data.flip_normals()
    c.data.update()
    return c


def join(objs, name):
    objs = [o for o in objs if o is not None]
    return mesh.join(objs, name=name)


def orient(o, inside=None, direction=None):
    """Flip faces so they point away from `inside` (a point, or f(center) ->
    point) or along `direction` (open strips, where recalc can't know)."""
    bm = bmesh.new()
    bm.from_mesh(o.data)
    for f in bm.faces:
        c = f.calc_center_median()
        if direction is not None:
            d = Vector(direction)
        else:
            d = c - Vector(inside(c) if callable(inside) else inside)
        if f.normal.dot(d) < 0:
            f.normal_flip()
    bm.to_mesh(o.data)
    bm.free()
    o.data.update()
    return o


def set_faces(o, material, test):
    """Put faces whose centre passes test(center, normal) on `material`."""
    mat.assign(o, material, faces=lambda p: test(p.center, p.normal))


def uv_box_fit(o, material, size=0.5):
    """Box-project the faces on `material` (size m per tile) and squeeze the
    result into 0..1 (keeps texcoords quantizable), aspect preserved."""
    mesh.uv_box(o, size, material=material)
    lay = o.data.uv_layers.active
    names = [m.name if m else None for m in o.data.materials]
    loops = [li for p in o.data.polygons if names[p.material_index] == material for li in p.loop_indices]
    if not loops:
        return
    us = [lay.data[li].uv[0] for li in loops]
    vs = [lay.data[li].uv[1] for li in loops]
    u0, v0 = min(us), min(vs)
    k = 1.0 / max(max(us) - u0, max(vs) - v0, 1e-6)
    for li in loops:
        u, v = lay.data[li].uv
        lay.data[li].uv = ((u - u0) * k, (v - v0) * k)


def cuts_y(y0, y1, step=1.0):
    n = max(1, math.ceil((y1 - y0) / step - 1e-6))
    return [y0 + (y1 - y0) * k / n for k in range(1, n)]


def finalize(o, smooth=None, weighted=False, origin=None, loops=None):
    """Apply transforms, bend loops, normals, origin."""
    mesh.apply_transform(o)
    if loops:
        mesh.subdivide_along(o, "Y", loops)
    if weighted:
        mesh.weighted_normals(o)
        mesh.apply_modifiers(o)
    elif smooth is not None:
        mesh.smooth(o, smooth)
    if origin is not None:
        mesh.set_origin(o, point=origin)
    return o


# ============================================================== materials

def _rgba(v):
    if isinstance(v, str):
        return mat.rgba(v)
    v = tuple(v)
    return v if len(v) == 4 else (*v, 1.0)


class Sh:
    """Procedural Principled material builder (source for the atlas bake)."""

    def __init__(self, name, base=(0.5, 0.5, 0.5), rough=0.5, metal=0.0, **inputs):
        self.mt = mat.flat(name, base, rough=rough, metal=metal, **inputs)
        self.nt = self.mt.node_tree
        self.p = mat.principled(self.mt)
        self._co = {}

    # -- plumbing
    def set(self, sock, v):
        if isinstance(v, bpy.types.NodeSocket):
            self.nt.links.new(v, sock)
        elif sock.type == "RGBA":
            sock.default_value = _rgba(v)
        elif sock.type == "VECTOR":
            sock.default_value = tuple(v)
        else:
            sock.default_value = float(v)

    def node(self, kind, inputs=None, **attrs):
        n = self.nt.nodes.new(kind)
        for k, v in attrs.items():
            setattr(n, k, v)
        for k, v in (inputs or {}).items():
            self.set(n.inputs[k], v)
        return n

    def co(self, kind="Object"):
        if kind not in self._co:
            self._co[kind] = self.node("ShaderNodeTexCoord").outputs[kind]
        return self._co[kind]

    def vec(self, scale=1.0, loc=(0, 0, 0), rot=(0, 0, 0), src=None):
        s = scale if isinstance(scale, (tuple, list)) else (scale, scale, scale)
        mp = self.node("ShaderNodeMapping")
        self.set(mp.inputs["Vector"], src if src is not None else self.co())
        mp.inputs["Scale"].default_value = s
        mp.inputs["Location"].default_value = loc
        mp.inputs["Rotation"].default_value = rot
        return mp.outputs["Vector"]

    def xyz(self, vec=None):
        n = self.node("ShaderNodeSeparateXYZ")
        self.set(n.inputs[0], vec if vec is not None else self.co())
        return n.outputs[0], n.outputs[1], n.outputs[2]

    def comb(self, x=0.0, y=0.0, z=0.0):
        n = self.node("ShaderNodeCombineXYZ")
        for i, v in enumerate((x, y, z)):
            self.set(n.inputs[i], v)
        return n.outputs[0]

    # -- textures
    def noise(self, vec=None, scale=5.0, detail=3.0, rough=0.5, distortion=0.0, color=False, dim="3D"):
        n = self.node("ShaderNodeTexNoise", {"Scale": scale, "Detail": detail, "Roughness": rough,
                                            "Distortion": distortion}, noise_dimensions=dim)
        self.set(n.inputs["Vector"], vec if vec is not None else self.co())
        return n.outputs[1 if color else 0]

    def voronoi(self, vec=None, scale=5.0, feature="F1", dist="EUCLIDEAN", out="Distance", rand=1.0, dim="3D"):
        n = self.node("ShaderNodeTexVoronoi", {"Scale": scale, "Randomness": rand}, feature=feature, distance=dist,
                      voronoi_dimensions=dim)
        self.set(n.inputs["Vector"], vec if vec is not None else self.co())
        return n.outputs[out]

    def wave(self, vec=None, scale=1.0, kind="BANDS", direction="X", profile="SIN", distortion=0.0, detail=0.0,
             phase=0.0):
        n = self.node("ShaderNodeTexWave", {"Scale": scale, "Distortion": distortion, "Detail": detail,
                                           "Phase Offset": phase}, wave_type=kind, wave_profile=profile)
        if kind == "BANDS":
            n.bands_direction = direction
        else:
            n.rings_direction = direction if direction in ("X", "Y", "Z", "SPHERICAL") else "SPHERICAL"
        self.set(n.inputs["Vector"], vec if vec is not None else self.co())
        return n.outputs[1]

    def image(self, img, vec=None, box=False, blend=0.2, color=True, interp="Linear"):
        if isinstance(img, str):
            img = mat.image(img, data=not color)
        n = self.node("ShaderNodeTexImage")
        n.image = img
        n.interpolation = interp
        if box:
            n.projection = "BOX"
            n.projection_blend = blend
        self.set(n.inputs["Vector"], vec if vec is not None else self.co("UV"))
        return n

    def texset(self, tid, scale=1.0, blend=0.25, vec=None):
        """Box-mapped CC0 set -> dict of sockets (color, rough, metal, normal_col, ao, disp)."""
        maps = mat.find_maps(tid)
        v = vec if vec is not None else self.vec(1.0 / scale)
        out = {}
        for kind, key, data in (("color", "color", False), ("roughness", "rough", True), ("metalness", "metal", True),
                                ("normal", "normal_col", True), ("ao", "ao", True), ("displacement", "disp", True)):
            if kind in maps:
                out[key] = self.image(maps[kind], v, box=True, blend=blend, color=not data).outputs["Color"]
        return out

    def normal_map(self, col, strength=1.0):
        n = self.node("ShaderNodeNormalMap", {"Strength": strength})
        self.set(n.inputs["Color"], col)
        return n.outputs[0]

    # -- maths
    def m(self, op, a, b=None, c=None, clamp=False):
        n = self.node("ShaderNodeMath", operation=op, use_clamp=clamp)
        for i, v in enumerate((a, b, c)):
            if v is not None:
                self.set(n.inputs[i], v)
        return n.outputs[0]

    def mix(self, fac, a, b, blend="MIX", clamp=True):
        n = self.node("ShaderNodeMix", data_type="RGBA", blend_type=blend, clamp_result=clamp)
        self.set(n.inputs[0], fac)
        self.set(n.inputs[6], a)
        self.set(n.inputs[7], b)
        return n.outputs[2]

    def mixf(self, fac, a, b):
        n = self.node("ShaderNodeMix", data_type="FLOAT")
        self.set(n.inputs[0], fac)
        self.set(n.inputs[2], a)
        self.set(n.inputs[3], b)
        return n.outputs[0]

    def ramp(self, fac, stops, interp="LINEAR"):
        n = self.node("ShaderNodeValToRGB")
        cr = n.color_ramp
        cr.interpolation = interp
        while len(cr.elements) < len(stops):
            cr.elements.new(0.5)
        for el, (pos, col) in zip(cr.elements, stops):
            el.position = pos
            el.color = _rgba(col) if not isinstance(col, (int, float)) else (col, col, col, 1.0)
        self.set(n.inputs[0], fac)
        return n.outputs[0]

    def mr(self, v, a, b, c=0.0, d=1.0, clamp=True, interp="LINEAR"):
        n = self.node("ShaderNodeMapRange", {"From Min": a, "From Max": b, "To Min": c, "To Max": d},
                      clamp=clamp, interpolation_type=interp)
        self.set(n.inputs[0], v)
        return n.outputs[0]

    def smooth(self, v, a, b):
        return self.mr(v, a, b, 0.0, 1.0, True, "SMOOTHSTEP")

    def bump(self, h, strength=0.5, dist=0.01, normal=None, invert=False):
        n = self.node("ShaderNodeBump", {"Strength": strength, "Distance": dist}, invert=invert)
        self.set(n.inputs["Height"], h)
        if normal is not None:
            self.set(n.inputs["Normal"], normal)
        return n.outputs[0]

    def bevel(self, radius=0.01, normal=None):
        n = self.node("ShaderNodeBevel", {"Radius": radius})
        n.samples = 8
        if normal is not None:
            self.set(n.inputs["Normal"], normal)
        return n.outputs[0]

    def ao(self, dist=0.3, samples=8, inside=False):
        n = self.node("ShaderNodeAmbientOcclusion", {"Distance": dist}, samples=samples, inside=inside)
        return n.outputs["AO"]

    def geo(self, out="Normal"):
        if ("geo", out) not in self._co:
            self._co[("geo", out)] = self.node("ShaderNodeNewGeometry").outputs[out]
        return self._co[("geo", out)]

    # -- output
    def out(self, base=None, rough=None, metal=None, normal=None, emission=None, strength=None, ao=None,
            **inputs):
        p = self.p
        for sock, v in (("Base Color", base), ("Roughness", rough), ("Metallic", metal), ("Normal", normal),
                        ("Emission Color", emission), ("Emission Strength", strength)):
            if v is not None:
                self.set(p.inputs[sock], v)
        if ao is not None:
            self.set(mat.gltf_output(self.mt).inputs["Occlusion"], ao)
        for k, v in inputs.items():
            self.set(p.inputs[k], v)
        return self.mt


def cc0(name, tid, scale=1.0, tint=None, rough_mul=1.0, rough_add=0.0, metal=None, nstr=1.0, emission=None,
        estr=0.0, grime=None, value=1.0):
    """CC0 texture set, box mapped at `scale` m per tile, with optional tint,
    roughness remap and procedural grime (dict(amount, scale, color))."""
    s = Sh(name)
    t = s.texset(tid, scale)
    col = t.get("color", (0.5, 0.5, 0.5, 1))
    if tint is not None:
        col = s.mix(1.0, col, tint, "MULTIPLY")
    if value != 1.0:
        col = s.mix(1.0, col, (value, value, value), "MULTIPLY")
    r = t.get("rough", 0.5)
    r = s.m("MULTIPLY_ADD", r, rough_mul, rough_add, clamp=True)
    if grime:
        g = s.m("MULTIPLY", s.smooth(s.noise(scale=grime.get("scale", 2.0), detail=6, rough=0.6), 0.45, 0.8),
                grime.get("amount", 0.5))
        col = s.mix(g, col, grime.get("color", "#2a241c"))
        r = s.mixf(g, r, 0.85)
    nrm = s.normal_map(t["normal_col"], nstr) if "normal_col" in t and nstr > 0 else None
    s.out(base=col, rough=r, metal=metal if metal is not None else t.get("metal", 0.0), normal=nrm,
          ao=t.get("ao"))
    if emission is not None:
        s.out(emission=emission, strength=estr)
    return s.mt


def flat(name, color, rough=0.5, metal=0.0, emission=None, strength=0.0, **kw):
    return mat.flat(name, color, rough=rough, metal=metal, emission=emission, strength=strength, **kw)



def floral_image(size=512, seed=7):
    """Tileable pastel floral print (numpy), for the case material."""
    img = bpy.data.images.get("_floral")
    if img is not None:
        return img
    rng = np.random.default_rng(seed)
    c = Canvas(size, size, "#f3c9d2")
    Y, X = c.Y, c.X
    cols = ["#ffffff", "#f7e27a", "#e8657a", "#b79ae0", "#ff9e7a"]
    for _ in range(38):
        cx, cy = rng.uniform(0, size, 2)
        r = rng.uniform(14, 30)
        col = cols[rng.integers(len(cols))]
        for dx in (-size, 0, size):
            for dy in (-size, 0, size):
                x0, y0 = cx + dx, cy + dy
                if -60 < x0 < size + 60 and -60 < y0 < size + 60:
                    a0 = rng.uniform(0, TAU)
                    for k in range(2):  # leaves
                        a = a0 + k * 2.4
                        lx, ly = x0 + math.cos(a) * r * 1.3, y0 + math.sin(a) * r * 1.3
                        d = np.hypot((X - lx) * 1.0, (Y - ly) * 1.0)
                        ca, sa = math.cos(a), math.sin(a)
                        u = (X - lx) * ca + (Y - ly) * sa
                        v = -(X - lx) * sa + (Y - ly) * ca
                        c.fill(np.hypot(u / 1.0, v / 0.45) - r * 0.55, "#7fb58a")
                    for k in range(5):
                        a = a0 + TAU * k / 5
                        c.circle(x0 + math.cos(a) * r * 0.55, y0 + math.sin(a) * r * 0.55, r * 0.5, col)
                    c.circle(x0, y0, r * 0.28, "#f2b33d" if col != "#f7e27a" else "#e07b39")
    return c.image("_floral")


SEG7 = {"0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc", "5": "afgcd", "6": "afgedc", "7": "abc",
        "8": "abcdefg", "9": "abcdfg", "M": "M"}


def counter_image(text="1.2M"):
    """Little LED view counter: an eye icon and seven-segment digits (numpy)."""
    img = bpy.data.images.get("_counter")
    if img is not None:
        return img
    c = Canvas(256, 128, "#050505")
    on = "#ffcf33"
    # eye icon
    c.fill(np.maximum(np.hypot((c.X - 38) / 26, (c.Y - 64) / 13) - 1.0, -np.inf), on)
    c.circle(38, 64, 8, "#050505")
    c.circle(38, 64, 4, on)
    x0 = 76
    for ch in text:
        if ch == ".":
            c.circle(x0 + 2, 96, 5, on)
            x0 += 14
            continue
        segs = SEG7.get(ch, "")
        w, h, t = 30, 64, 8
        top, mid, bot = 32, 64, 96
        if ch == "M":
            for xx in (x0, x0 + w):
                c.rrect(xx - t / 2, top, t, h, 2, on)
            c.chevron(x0 + w / 2, top + 22, w, -40, t, on)
            x0 += w + 18
            continue
        R = {"a": (x0, top - t / 2, w, t), "g": (x0, mid - t / 2, w, t), "d": (x0, bot - t / 2, w, t),
             "f": (x0 - t / 2, top, t, h / 2), "b": (x0 + w - t / 2, top, t, h / 2),
             "e": (x0 - t / 2, mid, t, h / 2), "c": (x0 + w - t / 2, mid, t, h / 2)}
        for sg in segs:
            c.rrect(*R[sg], 3, on)
        x0 += w + 18
    return c.image("_counter")

class Mats:
    """Lazily built source materials (only the ones the chosen pieces use)."""

    def __init__(self):
        self._c = {}

    def __getattr__(self, key):
        if key.startswith("_"):
            raise AttributeError(key)
        if key not in self._c:
            self._c[key] = getattr(self, "_" + key)()
        return self._c[key]

    # ---- runtime (kept, renderer overrides the map). Each differs a little so
    # gltf-transform's dedup never merges two of them.
    def _ReelScreen(self):
        return mat.emissive_screen("ReelScreen", (0.55, 0.8, 1.0), 3.0, rough=0.12)

    def _ReelFront(self):
        return mat.emissive_screen("ReelFront", (0.6, 0.82, 1.0), 3.0, rough=0.13)

    def _NotifFace(self):
        return mat.emissive_screen("NotifFace", (0.92, 0.92, 0.96), 1.6, rough=0.2)

    def _AdFace(self):
        return mat.emissive_screen("AdFace", (1.0, 0.8, 0.3), 2.5, rough=0.14)

    def _MumFace(self):
        return mat.emissive_screen("MumFace", (0.3, 0.55, 0.42), 1.8, rough=0.16)

    def _RampFace(self):
        return mat.emissive_screen("RampFace", (0.7, 0.2, 0.9), 2.2, rough=0.1)

    def _AutoplayBelt(self):
        return mat.emissive_screen("AutoplayBelt", (1.0, 0.75, 0.1), 1.5, base=(0.02, 0.02, 0.02), rough=0.6)

    def _Warn(self):
        return mat.flat("Warn", "#ff1a1a", rough=0.3, emission="#ff1a1a", strength=6.0)

    def _Glass(self):
        m = mat.glass("Glass", color=(0.85, 0.93, 1.0), rough=0.03, alpha=0.14, smudges="Fingerprints002",
                      smudge_strength=0.15)
        return m

    # ---- train
    def _ti(self):  # natural titanium unibody, brushed, grime low down
        s = Sh("ti")
        t = s.texset("Metal009", 0.5)
        col = s.mix(1.0, t["color"], "#c9c3b8", "MULTIPLY")
        col = s.mix(1.0, col, (1.35, 1.33, 1.3), "MULTIPLY")
        _, _, z = s.xyz()
        streak = s.noise(s.vec((3.0, 3.0, 0.9)), scale=1.0, detail=5, rough=0.6)
        low = s.m("MULTIPLY", s.smooth(z, 0.75, 0.36), s.smooth(streak, 0.4, 0.75))
        col = s.mix(s.m("MULTIPLY", low, 0.22), col, "#51493d")
        r = s.m("MULTIPLY_ADD", t["rough"], 0.55, 0.12, clamp=True)
        r = s.mixf(low, r, 0.7)
        return s.out(base=col, rough=r, metal=s.mixf(low, 1.0, 0.4), normal=s.normal_map(t["normal_col"], 0.4))

    def _frosted(self):  # textured matte back glass in the frame colour
        s = Sh("frosted")
        g = s.noise(scale=180.0, detail=2)
        col = s.mix(0.08, "#8f8a82", g, "OVERLAY")
        return s.out(base=col, rough=s.m("MULTIPLY_ADD", g, 0.1, 0.4), metal=0.0,
                     normal=s.bump(g, 0.05, 0.002))

    def _antenna(self):
        return flat("antenna", "#5d5a55", rough=0.5)

    def _chamfer(self):
        return flat("chamfer", "#e9e6df", rough=0.12, metal=1.0)

    def _black_glass(self):
        s = Sh("black_glass")
        fp = s.image(mat.find_maps("Fingerprints002")["roughness"], s.vec(0.9), box=True, color=False)
        r = s.m("MULTIPLY_ADD", fp.outputs["Color"], 0.18, 0.04, clamp=True)
        return s.out(base="#040506", rough=r, metal=0.0, **{"Specular IOR Level": 0.6})

    def _island(self):
        return flat("island", "#010102", rough=0.25)

    def _lens(self):  # coated camera glass: violet-green sheen
        s = Sh("lens")
        f = s.m("POWER", s.m("SUBTRACT", 1.0, s.m("ABSOLUTE", s.xyz(s.geo("Normal"))[1])), 2.0)
        col = s.mix(f, "#07060c", "#2b1c4a")
        return s.out(base=col, rough=0.03, metal=0.0, **{"Specular IOR Level": 0.8})

    def _headlight(self):
        return flat("headlight", "#fff6ea", rough=0.1, emission="#fff4e4", strength=7.0)

    def _taillight(self):
        return flat("taillight", "#ff2020", rough=0.15, emission="#ff1a10", strength=4.0)

    def _walkway(self):  # anti-slip diamond plate (CC0 set; procedural fallback if it isn't fetched)
        try:
            lib.texture_dir("DiamondPlate008A")
        except FileNotFoundError:
            log("DiamondPlate008A not in assets/textures: procedural diamond plate")
            s = Sh("walkway")
            v = s.vec((1, 1, 1), rot=(0, 0, math.radians(45)))
            x, y, _ = s.xyz(v)
            cell = lambda c, k: s.m("SUBTRACT", s.m("FRACT", s.m("MULTIPLY", c, k)), 0.5)  # noqa: E731
            ga = s.m("MULTIPLY", s.m("ABSOLUTE", cell(x, 14.0)), 1.0)
            gb = s.m("ABSOLUTE", cell(y, 14.0))
            lug = s.m("MULTIPLY", s.smooth(ga, 0.12, 0.02), s.smooth(gb, 0.42, 0.3))
            n = s.noise(scale=3.0, detail=5)
            col = s.mix(s.m("MULTIPLY", s.smooth(n, 0.45, 0.8), 0.45), "#7e8084", "#1c1a18")
            return s.out(base=col, rough=s.mixf(lug, 0.55, 0.3), metal=0.9, normal=s.bump(lug, 0.6, 0.004))
        return cc0("walkway", "DiamondPlate008A", 0.5, tint="#8c8e92", rough_mul=1.1,
                   grime=dict(amount=0.45, scale=1.5, color="#1c1a18"))

    def _powder(self):  # black powder-coated steel
        return cc0("powder", "Metal027", 0.5, tint="#3a3b3e", rough_mul=1.0,
                   grime=dict(amount=0.35, scale=2.5, color="#15130f"))

    def _steel(self):
        return cc0("steel", "Metal009", 0.4, tint="#8a8a88", rough_mul=0.9, rough_add=0.15, metal=1.0,
                   grime=dict(amount=0.5, scale=4.0, color="#3a2616"))

    def _rubber(self):
        return cc0("rubber", "Rubber004", 0.35, tint="#606060", rough_mul=1.0)

    def _vent(self):  # slatted grille (bump), dark aluminium
        s = Sh("vent", "#2c2e31", rough=0.45, metal=0.8)
        _, y, _ = s.xyz()
        slat = s.wave(scale=12.0, direction="Y", profile="SAW")
        return s.out(normal=s.bump(slat, 0.8, 0.02), base=s.mix(s.smooth(slat, 0.8, 1.0), "#2c2e31", "#0a0a0b"))

    def _spring_coil(self):  # coil spring faked on a cylinder
        s = Sh("spring_coil", "#1d3a2a", rough=0.5, metal=0.3)
        _, _, z = s.xyz()
        coil = s.m("SINE", s.m("MULTIPLY", z, 110.0))
        return s.out(normal=s.bump(coil, 0.9, 0.02), base=s.mix(s.smooth(coil, -0.6, -0.9), "#2b4a36", "#050806"))

    def _yellow(self):  # safety yellow paint, worn to steel on edges
        s = Sh("yellow")
        t = s.texset("Metal027", 0.4)
        wear = s.smooth(s.noise(scale=9.0, detail=8, rough=0.7), 0.62, 0.72)
        col = s.mix(wear, "#f1b80b", "#6d6a66")
        col = s.mix(s.m("MULTIPLY", s.smooth(s.noise(scale=2.0, detail=4), 0.5, 0.8), 0.4), col, "#5b4a18")
        return s.out(base=col, rough=s.mixf(wear, 0.42, 0.3), metal=s.mixf(wear, 0.0, 0.9),
                     normal=s.normal_map(t["normal_col"], 0.5))

    def _galv(self):  # hot-dip galvanised steel (spangle)
        s = Sh("galv")
        t = s.texset("Metal009", 0.6)
        sp = s.voronoi(scale=18.0, out="Color")
        col = s.mix(0.25, s.mix(1.0, t["color"], "#a4a7aa", "MULTIPLY"), sp, "OVERLAY")
        col = s.mix(s.m("MULTIPLY", s.smooth(s.noise(scale=3.0, detail=5), 0.5, 0.8), 0.5), col, "#4c4a45")
        return s.out(base=col, rough=s.m("MULTIPLY_ADD", t["rough"], 0.6, 0.3, clamp=True), metal=0.9,
                     normal=s.normal_map(t["normal_col"], 0.5))

    # ---- barriers
    def _frost(self):  # the notification pill's frosted glass body
        s = Sh("frost")
        n = s.noise(scale=60.0, detail=2)
        return s.out(base=s.mix(0.05, "#dfe3ea", n, "OVERLAY"), rough=0.28, metal=0.0, emission="#e6ecff",
                     strength=0.35, normal=s.bump(n, 0.03, 0.002))

    def _hazard(self):  # yellow/black diagonal stripes, scuffed
        s = Sh("hazard")
        st = s.wave(scale=2.2, kind="BANDS", direction="DIAGONAL", profile="SAW")
        m = s.m("GREATER_THAN", st, 0.5)
        wear = s.smooth(s.noise(scale=14.0, detail=6, rough=0.7), 0.6, 0.7)
        col = s.mix(m, "#0c0c0c", "#f2b705")
        col = s.mix(s.m("MULTIPLY", wear, 0.7), col, "#5a5650")
        return s.out(base=col, rough=0.5, metal=s.mixf(wear, 0.0, 0.8))

    def _lamp(self):
        return flat("lamp", "#fff1d6", rough=0.2, emission="#ffe7c2", strength=5.0)

    # ---- habits (matte, warm, realistic)
    def _cork(self):
        s = Sh("cork")
        n = s.noise(scale=90.0, detail=4, rough=0.6)
        v = s.voronoi(scale=140.0, out="Distance")
        grain = s.m("MULTIPLY", s.smooth(v, 0.05, 0.3), s.smooth(n, 0.3, 0.7))
        col = s.ramp(grain, [(0.0, "#5a3a22"), (0.5, "#9c7048"), (1.0, "#c8a07a")])
        return s.out(base=col, rough=0.85, normal=s.bump(grain, 0.6, 0.004))

    def _water(self):  # opaque stand-in for water seen through glass: dark teal body, lit meniscus, caustics
        s = Sh("water")
        x, y, z = s.xyz()
        r = s.m("SQRT", s.m("ADD", s.m("MULTIPLY", x, x), s.m("MULTIPLY", y, y)))
        edge = s.smooth(r, 0.18, 0.33)
        top = s.m("MULTIPLY", s.smooth(z, 0.7, 0.735), s.smooth(r, 0.29, 0.325))
        body = s.mix(edge, "#04141a", "#1b4450")
        body = s.mix(s.smooth(z, 0.2, 0.7), body, s.mix(edge, "#08222b", "#2d6574"))
        caus = s.smooth(s.voronoi(s.vec((1, 1, 0.5)), scale=14.0, feature="SMOOTH_F1", out="Distance"), 0.18, 0.0)
        caus = s.m("MULTIPLY", caus, s.smooth(z, 0.3, 0.1))
        col = s.mix(s.m("MAXIMUM", top, s.m("MULTIPLY", caus, 0.5)), body, "#c6e9f2")
        return s.out(base=col, rough=0.03, metal=0.0, emission="#bfe9f5",
                     strength=s.m("MULTIPLY", s.m("MAXIMUM", caus, s.m("MULTIPLY", top, 0.5)), 0.35))

    def _paper(self):  # page edges: fine layered lines, yellowed toward the outside
        s = Sh("paper")
        lines = s.wave(s.vec((1, 1, 1)), scale=18.0, direction="Z", profile="SIN", distortion=0.6, detail=2)
        sig = s.wave(s.vec((1, 1, 1)), scale=4.0, direction="Z", profile="SIN", distortion=0.3)
        n = s.noise(scale=8.0, detail=3)
        col = s.mix(s.m("MULTIPLY", lines, 0.18), "#efe7d5", "#b9ae98")
        col = s.mix(s.m("MULTIPLY", s.smooth(sig, 0.85, 1.0), 0.25), col, "#a89a80")
        col = s.mix(s.m("MULTIPLY", n, 0.25), col, "#d8c49a")
        return s.out(base=col, rough=0.8, normal=s.bump(lines, 0.35, 0.002))

    def _cloth(self, name, color):
        s = Sh(name)
        t = s.texset("rough_linen", 0.22)
        col = s.mix(1.0, t["color"], color, "MULTIPLY")
        col = s.mix(1.0, col, (2.2, 2.2, 2.2), "MULTIPLY")
        _, y, _ = s.xyz()
        # gold foil rules across the spine (the curved side, text-free)
        x, yy, zz = s.xyz()
        spine = s.smooth(s.m("ABSOLUTE", yy), 0.3, 0.33)
        rules = s.m("MULTIPLY", spine, s.m("GREATER_THAN", s.m("SINE", s.m("MULTIPLY", s.m("ABSOLUTE", x), 70.0)), 0.93))
        rules = s.m("MULTIPLY", rules, s.smooth(s.m("ABSOLUTE", x), 0.28, 0.33))
        col = s.mix(rules, col, "#c9a45a")
        return s.out(base=col, rough=s.mixf(rules, s.m("MULTIPLY", t["rough"], 1.0), 0.3), metal=s.mixf(rules, 0, 1),
                     normal=s.normal_map(t["normal_col"], 0.8))

    def _cloth_green(self):
        return self._cloth("cloth_green", "#34503f")

    def _cloth_red(self):
        return self._cloth("cloth_red", "#6e2328")

    def _cloth_navy(self):
        return self._cloth("cloth_navy", "#26334f")

    def _ribbon(self):
        return flat("ribbon", "#8e1b24", rough=0.35, sheen_weight=0.5)

    def _knit(self):  # engineered knit upper, soft grey-blue
        s = Sh("knit")
        t = s.texset("knitted_fleece", 0.09)
        col = s.mix(1.0, t["color"], "#9aa6ad", "MULTIPLY")
        col = s.mix(1.0, col, (1.6, 1.6, 1.6), "MULTIPLY")
        return s.out(base=col, rough=0.9, normal=s.normal_map(t["normal_col"], 1.2))

    def _synthetic(self):
        s = Sh("synthetic")
        n = s.noise(scale=40.0, detail=3)
        return s.out(base=s.mix(0.1, "#d9dcdc", n, "OVERLAY"), rough=0.45, normal=s.bump(n, 0.05, 0.002))

    def _lining(self):
        return cc0("lining", "jogging_melange", 0.08, tint="#3a3d44", rough_mul=1.0)

    def _foam(self):  # EVA foam midsole: fine pores, off-white
        s = Sh("foam")
        n = s.noise(scale=220.0, detail=2)
        v = s.voronoi(scale=260.0)
        pore = s.smooth(v, 0.0, 0.25)
        return s.out(base=s.mix(0.08, "#eeebe4", n, "OVERLAY"), rough=0.75, normal=s.bump(pore, 0.12, 0.002))

    def _outsole(self):  # rubber with lug tread (bump on the bottom)
        s = Sh("outsole")
        t = s.texset("Rubber004", 0.2)
        x, y, z = s.xyz()
        lug = s.m("GREATER_THAN", s.wave(s.vec((1, 1, 1), rot=(0, 0, 0.5)), scale=4.0, direction="X",
                                          profile="SIN"), 0.45)
        return s.out(base=s.mix(1.0, t["color"], "#4a4a4c", "MULTIPLY"), rough=0.85,
                     normal=s.bump(lug, 0.6, 0.01, normal=s.normal_map(t["normal_col"], 0.8)))

    def _shoe_upper_mat(self, name, knit_tint, overlay, lining, accent, bright=1.6, emission=None, estr=0.0):
        s = Sh(name)
        at = s.node("ShaderNodeAttribute", attribute_name="sh", attribute_type="GEOMETRY")
        t, h, c = s.xyz(at.outputs["Vector"])
        col_fac = at.outputs["Alpha"]
        ac = s.m("ABSOLUTE", c)
        k = s.texset("knitted_fleece", 0.22)
        grey = s.node("ShaderNodeRGBToBW")
        s.set(grey.inputs[0], k["color"])
        g = s.m("MULTIPLY", grey.outputs[0], bright)
        knit = s.mix(1.0, s.comb(g, g, g), knit_tint, "MULTIPLY")
        counter = s.m("MULTIPLY", s.smooth(s.m("SUBTRACT", t, s.m("MULTIPLY", h, 0.1)), 0.23, 0.15),
                      s.smooth(h, 0.9, 0.7))
        toe = s.m("MULTIPLY", s.smooth(t, 0.84, 0.92), s.smooth(h, 0.66, 0.4))
        mud = s.smooth(h, 0.2, 0.06)
        eye = s.m("MULTIPLY", s.m("MULTIPLY", s.smooth(ac, 0.08, 0.14), s.smooth(ac, 0.36, 0.28)),
                  s.m("MULTIPLY", s.smooth(t, 0.33, 0.37), s.smooth(t, 0.67, 0.63)))
        eye = s.m("MULTIPLY", eye, s.smooth(h, 0.8, 0.9))
        ov = s.m("MAXIMUM", s.m("MAXIMUM", counter, toe), s.m("MAXIMUM", mud, eye))
        stripe = s.m("MULTIPLY", s.m("GREATER_THAN", s.m("SINE", s.m("MULTIPLY", h, 44.0)), 0.8),
                     s.m("MULTIPLY", s.smooth(t, 0.2, 0.14), s.smooth(h, 0.3, 0.4)))
        stripe = s.m("MULTIPLY", stripe, s.smooth(h, 0.62, 0.55))
        col = s.mix(ov, knit, overlay)
        col = s.mix(stripe, col, accent)
        lin = s.smooth(col_fac, 0.2, 0.5)
        col = s.mix(lin, col, lining)
        rough = s.mixf(ov, 0.92, 0.42)
        nrm = s.normal_map(k["normal_col"], s.mixf(s.m("MAXIMUM", ov, lin), 1.3, 0.1))
        s.out(base=col, rough=s.mixf(stripe, rough, 0.2), normal=nrm)
        if emission is not None:
            s.out(emission=emission, strength=s.mixf(ov, estr, estr * 0.3))
        return s.mt

    def _shoe_sole_mat(self, name, foam, outsole, groove=True, emission=None, estr=0.0):
        s = Sh(name)
        at = s.node("ShaderNodeAttribute", attribute_name="sh", attribute_type="GEOMETRY")
        t, zr, side = s.xyz(at.outputs["Vector"])
        n = s.noise(scale=220.0, detail=2)
        pore = s.smooth(s.voronoi(scale=260.0), 0.0, 0.25)
        out_band = s.smooth(zr, 0.026, 0.02)
        bottom = s.smooth(s.xyz(s.geo("Normal"))[2], -0.6, -0.8)
        rub = s.m("MAXIMUM", out_band, bottom)
        lug = s.m("GREATER_THAN", s.wave(s.vec((1, 1, 1), rot=(0, 0, 0.5)), scale=5.0, direction="X"), 0.45)
        grv = s.m("MULTIPLY", s.smooth(s.m("ABSOLUTE", s.m("SUBTRACT", zr, 0.085)), 0.008, 0.0), 1.0 if groove else 0.0)
        col = s.mix(rub, s.mix(0.08, foam, n, "OVERLAY"), outsole)
        col = s.mix(s.m("MULTIPLY", grv, 0.35), col, "#6b6a66")
        h = s.m("ADD", s.m("MULTIPLY", pore, s.m("SUBTRACT", 1.0, rub)), s.m("MULTIPLY", lug, s.m("MULTIPLY", rub, 3.0)))
        h = s.m("SUBTRACT", h, s.m("MULTIPLY", grv, 2.0))
        s.out(base=col, rough=s.mixf(rub, 0.72, 0.9), normal=s.bump(h, 0.3, 0.004))
        if emission is not None:
            s.out(emission=emission, strength=s.mixf(rub, estr, 0.0))
        return s.mt

    def _shoe_upper(self):
        return self._shoe_upper_mat("shoe_upper", "#8fa3b3", "#e6e7e3", "#2f3238", "#e8734a", bright=2.0)

    def _shoe_sole(self):
        return self._shoe_sole_mat("shoe_sole", "#efece6", "#3d3f44")

    def _lace(self):
        s = Sh("lace")
        w = s.wave(scale=40.0, direction="DIAGONAL", profile="SIN")
        return s.out(base="#e8e4da", rough=0.9, normal=s.bump(w, 0.3, 0.002))

    def _floral(self):  # Mum's phone case: pastel pink, scattered flowers
        s = Sh("floral")
        img = floral_image()
        n = s.image(img, s.vec(3.2), box=True, blend=0.3)
        return s.out(base=n.outputs["Color"], rough=0.45, **{"Coat Weight": 0.3})

    def _white_front(self):
        return flat("white_front", "#f1f0ec", rough=0.08, **{"Coat Weight": 0.5})

    def _chrome(self):
        return flat("chrome", "#dcdcdc", rough=0.08, metal=1.0)

    def _alu(self):  # bead-blasted aluminium
        return cc0("alu", "Metal009", 0.3, tint="#cfd1d4", rough_mul=0.6, rough_add=0.25, metal=1.0, nstr=0.3)

    # ---- the Thumb
    def _skin(self):
        s = Sh("skin")
        x, y, z = s.xyz()
        mott = s.noise(scale=1.6, detail=4, rough=0.6)
        base = s.ramp(mott, [(0.3, "#c98f74"), (0.7, "#dcaa8e")])
        # redder knuckles, fingertip and edges of the nail
        knuck = s.m("EXPONENT", s.m("MULTIPLY", s.m("POWER", s.m("SUBTRACT", y, 4.35), 2.0), -3.0))
        tip = s.smooth(y, 7.0, 7.9)
        red = s.m("MULTIPLY", s.m("MAXIMUM", knuck, tip), 0.55)
        base = s.mix(red, base, "#c07466")
        # dorsal knuckle wrinkles: curved transverse lines around the IP joint and the base
        top = s.smooth(s.xyz(s.geo("Normal"))[2], 0.35, 0.8)
        curvy = s.m("ADD", y, s.m("MULTIPLY", s.m("MULTIPLY", x, x), 0.22))
        wr = s.wave(s.comb(0.0, curvy, 0.0), scale=0.8, direction="Y", profile="SIN", distortion=2.5, detail=3)
        base_wr = s.m("MULTIPLY", s.m("EXPONENT", s.m("MULTIPLY", s.m("POWER", s.m("SUBTRACT", y, 1.1), 2.0), -4.0)),
                      0.45)
        wr_mask = s.m("MULTIPLY", s.m("MAXIMUM", s.m("EXPONENT", s.m("MULTIPLY", s.m("POWER", s.m("SUBTRACT", y, 4.35),
                                                                                              2.0), -5.0)), base_wr),
                      s.m("MULTIPLY", top, s.smooth(s.m("ABSOLUTE", x), 0.75, 0.35)))
        wr_line = s.m("MULTIPLY", s.smooth(wr, 0.78, 0.97), wr_mask)
        # fingerprint whorl on the pad
        fp_d = s.m("SQRT", s.m("ADD", s.m("MULTIPLY", s.m("MULTIPLY", x, x), 1.6),
                                s.m("POWER", s.m("SUBTRACT", y, 6.6), 2.0)))
        fp = s.m("SINE", s.m("MULTIPLY", fp_d, 55.0))
        fp_mask = s.m("MULTIPLY", s.smooth(z, 0.45, 0.15), s.smooth(fp_d, 1.3, 0.9))
        pores = s.voronoi(scale=26.0, feature="F1")
        lines = s.wave(s.vec((1, 1, 1), rot=(0, 0, 0.7)), scale=2.4, direction="X", distortion=3.0, detail=3)
        h = s.m("ADD", s.m("MULTIPLY", s.smooth(pores, 0.0, 0.25), 0.25), s.m("MULTIPLY", lines, 0.12))
        h = s.m("SUBTRACT", h, s.m("MULTIPLY", wr_line, 1.2))
        h = s.m("ADD", h, s.m("MULTIPLY", s.m("MULTIPLY", fp, fp_mask), 0.2))
        col = s.mix(s.m("MULTIPLY", wr_line, 0.45), base, "#8d5647")
        col = s.mix(s.m("MULTIPLY", s.smooth(pores, 0.12, 0.0), 0.12), col, "#a8705c")
        # the skin folds around the nail: pinker, a little darker
        around = s.m("MULTIPLY", s.m("MULTIPLY", s.smooth(s.m("ABSOLUTE", x), 0.82, 0.62), s.smooth(y, 5.0, 5.3)),
                     s.smooth(z, 1.1, 1.45))
        col = s.mix(s.m("MULTIPLY", around, 0.45), col, "#b36a5c")
        # lit from below by the screen it presses on
        glow = s.m("MULTIPLY", s.smooth(z, 0.9, 0.0), 0.22)
        return s.out(base=col, rough=s.mixf(s.smooth(pores, 0.0, 0.3), 0.62, 0.48), normal=s.bump(h, 0.35, 0.02),
                     emission=col, strength=s.m("ADD", glow, 0.06), **{"Subsurface Weight": 0.15})

    def _nail(self):
        s = Sh("nail")
        x, y, z = s.xyz()
        v = s.m("DIVIDE", s.m("SUBTRACT", y, NAIL_Y0), NAIL_Y1 - NAIL_Y0)
        lun = s.smooth(s.m("SQRT", s.m("ADD", s.m("MULTIPLY", s.m("MULTIPLY", x, x), 2.2),
                                        s.m("POWER", s.m("MULTIPLY", s.m("SUBTRACT", v, 0.0), 2.4), 2.0))), 0.62, 0.52)
        free = s.smooth(y, 7.5, 7.6)
        ridges = s.wave(s.comb(x, 0.0, 0.0), scale=2.6, direction="X", profile="SIN", distortion=0.8)
        col = s.mix(lun, "#eab7ab", "#f8e4dc")
        col = s.mix(free, col, "#fbf1e6")
        cut = s.smooth(v, 0.06, 0.0)
        col = s.mix(s.m("MULTIPLY", cut, 0.7), col, "#b06a58")
        edge = s.smooth(s.m("ABSOLUTE", x), 0.5, 0.64)
        col = s.mix(s.m("MULTIPLY", edge, 0.35), col, "#c48475")
        return s.out(base=col, rough=0.16, normal=s.bump(ridges, 0.1, 0.004), emission=col, strength=0.1,
                     **{"Coat Weight": 0.6})

    # ---- pads
    def _brushed(self):
        return cc0("brushed", "Metal009", 0.6, tint="#d3d5d8", rough_mul=0.5, rough_add=0.12, metal=1.0, nstr=0.5)

    def _led_pink(self):
        return flat("led_pink", "#ff2e88", rough=0.3, emission="#ff2e88", strength=5.0)

    def _spring_steel(self):
        return cc0("spring_steel", "Metal009", 0.2, tint="#9ea2a8", rough_mul=0.5, rough_add=0.15, metal=1.0)

    def _pad_foam(self):  # padded vinyl rim, cyan
        s = Sh("pad_foam")
        n = s.noise(scale=30.0, detail=3)
        return s.out(base="#0b8fb0", rough=0.4, normal=s.bump(n, 0.1, 0.004), emission="#00e1ff", strength=0.25,
                     **{"Coat Weight": 0.3})

    def _membrane(self):  # black jump mat, woven, with the pull-to-refresh spinner in light
        s = Sh("membrane")
        x, y, z = s.xyz()
        cx = s.m("SUBTRACT", y, BOUNCE_R)
        ang = s.m("ARCTAN2", x, cx)
        rad = s.m("SQRT", s.m("ADD", s.m("MULTIPLY", x, x), s.m("MULTIPLY", cx, cx)))
        # 12 capsule bars around, fading like the spinner
        seg = s.m("FRACT", s.m("DIVIDE", s.m("ADD", ang, math.pi), TAU / 12))
        bar = s.m("MULTIPLY", s.smooth(s.m("ABSOLUTE", s.m("SUBTRACT", seg, 0.5)), 0.22, 0.12),
                  s.m("MULTIPLY", s.smooth(rad, 0.2, 0.24), s.smooth(rad, 0.52, 0.48)))
        fade = s.m("FRACT", s.m("DIVIDE", s.m("ADD", ang, math.pi), TAU))
        lum = s.m("MULTIPLY", bar, s.m("ADD", 0.15, s.m("MULTIPLY", fade, 0.85)))
        weave = s.m("MULTIPLY", s.wave(scale=60.0, direction="X"), s.wave(scale=60.0, direction="Y"))
        col = s.mix(lum, "#101216", "#e9fbff")
        return s.out(base=col, rough=0.6, normal=s.bump(weave, 0.2, 0.002), emission="#bff6ff",
                     strength=s.m("MULTIPLY", lum, 3.0))

    def _stainless(self):
        return cc0("stainless", "Metal009", 0.5, tint="#dfe2e6", rough_mul=0.4, rough_add=0.08, metal=1.0, nstr=0.4)

    def _brush(self):
        return flat("brush", "#0c0c0d", rough=0.95)

    def _landing(self):  # aluminium landing plate with anti-slip ribs
        s = Sh("landing")
        rib = s.wave(scale=10.0, direction="X", profile="SIN")
        t = s.texset("Metal009", 0.4)
        return s.out(base=s.mix(1.0, t["color"], "#c8cacc", "MULTIPLY"), rough=0.35, metal=1.0,
                     normal=s.bump(s.smooth(rib, 0.7, 0.9), 0.6, 0.004))

    def _comb(self):
        s = Sh("comb")
        return s.out(base="#e7c21a", rough=0.4, metal=0.6)

    # ---- pickups: glossy, a little glow in the dark
    def _candy_red(self):
        s = Sh("candy_red")
        z = s.xyz()[2]
        col = s.mix(s.smooth(z, -0.35, 0.35), "#e3002f", "#ff5b7f")
        return s.out(base=col, rough=0.12, emission=col, strength=0.7, **{"Coat Weight": 0.8})

    def _badge_red(self):
        return flat("badge_red", "#ff2e3b", rough=0.14, emission="#ff2e3b", strength=0.7, **{"Coat Weight": 0.8})

    def _white_gloss(self):
        return flat("white_gloss", "#ffffff", rough=0.15, emission="#ffffff", strength=0.9)

    def _reel_grad(self):
        s = Sh("reel_grad")
        x, _, z = s.xyz()
        k = s.m("MULTIPLY_ADD", s.m("SUBTRACT", x, z), 0.75, 0.5, clamp=True)
        col = s.ramp(k, [(0.0, "#00e1ff"), (0.55, "#6a5cff"), (1.0, "#ff2e88")])
        return s.out(base=col, rough=0.14, emission=col, strength=0.7, **{"Coat Weight": 0.8})

    def _emoji(self):  # angry face: orange top to red bottom, eyes and a frown on both faces
        s = Sh("emoji")
        x, y, z = s.xyz()
        col = s.mix(s.smooth(z, 0.35, -0.3), "#ff7a1f", "#e2231a")
        ey = s.m("SQRT", s.m("ADD", s.m("POWER", s.m("SUBTRACT", s.m("ABSOLUTE", x), 0.13), 2.0),
                                s.m("MULTIPLY", s.m("POWER", s.m("SUBTRACT", z, 0.03), 2.0), 0.6)))
        eyes = s.smooth(ey, 0.055, 0.045)
        mr = s.m("SQRT", s.m("ADD", s.m("MULTIPLY", x, x), s.m("POWER", s.m("ADD", z, 0.36), 2.0)))
        mouth = s.m("MULTIPLY", s.smooth(s.m("ABSOLUTE", s.m("SUBTRACT", mr, 0.24)), 0.03, 0.02),
                    s.m("MULTIPLY", s.smooth(s.m("ABSOLUTE", x), 0.17, 0.14), s.smooth(z, -0.2, -0.16)))
        face = s.m("MULTIPLY", s.m("MAXIMUM", eyes, mouth), s.smooth(s.m("ABSOLUTE", y), 0.12, 0.2))
        col = s.mix(face, col, "#3a0d05")
        return s.out(base=col, rough=s.mixf(face, 0.14, 0.3), emission=col, strength=s.mixf(face, 0.7, 0.0),
                     **{"Coat Weight": 0.8})

    def _emoji_dark(self):
        return flat("emoji_dark", "#3a0d05", rough=0.3)

    # ---- power-ups
    def _glass_edge(self):
        return flat("glass_edge", "#bff7ff", rough=0.05, emission="#8ff0ff", strength=1.5)

    def _crack(self):
        return flat("crack", "#ffffff", rough=0.2, emission="#dff9ff", strength=2.0)

    def _tab(self):
        return flat("tab", "#2aa5ff", rough=0.35, emission="#2aa5ff", strength=0.4)

    def _magnet_red(self):
        s = Sh("magnet_red")
        n = s.noise(scale=30.0, detail=3)
        return s.out(base="#e0144f", rough=s.m("MULTIPLY_ADD", n, 0.1, 0.18), emission="#ff2e88", strength=0.5,
                     **{"Coat Weight": 0.7})

    def _pole_silver(self):
        return cc0("pole_silver", "Metal009", 0.15, tint="#eef0f3", rough_mul=0.3, rough_add=0.06, metal=1.0,
                   emission="#ffffff", estr=0.15)

    def _magnet_heart(self):
        return flat("magnet_heart", "#ffe3ef", rough=0.12, emission="#ffd0e4", strength=1.0)

    def _rocket(self):  # glossy amber cans with a white band and a black-yellow warning stripe
        s = Sh("rocket")
        z = s.xyz()[2]
        band = s.m("MULTIPLY", s.smooth(z, -0.02, 0.0), s.smooth(z, 0.1, 0.08))
        haz = s.m("MULTIPLY", s.smooth(z, -0.22, -0.2), s.smooth(z, -0.12, -0.14))
        stripes = s.m("GREATER_THAN", s.wave(scale=3.0, direction="DIAGONAL", profile="SAW"), 0.5)
        col = s.mix(band, "#ffb300", "#f4f1ea")
        col = s.mix(haz, col, s.mix(stripes, "#111111", "#ffcf33"))
        return s.out(base=col, rough=0.18, metal=0.3, emission="#ffb300",
                     strength=s.mixf(s.m("MAXIMUM", band, haz), 0.4, 0.1), **{"Coat Weight": 0.6})

    def _nozzle(self):
        return cc0("nozzle", "Metal009", 0.1, tint="#6b5d52", rough_mul=0.6, rough_add=0.2, metal=1.0)

    def _flame(self):
        return flat("flame", "#ffae3b", rough=0.5, emission="#ff8a1f", strength=6.0)

    def _fin(self):
        return flat("fin", "#1a1a1d", rough=0.3, metal=0.4)

    def _counter(self):  # tiny LED display: "1.2M" views, eye icon
        s = Sh("counter")
        n = s.image(counter_image(), s.co("UV"))
        return s.out(base="#050505", rough=0.1, emission=n.outputs["Color"], strength=3.0)

    def _strap(self):
        return flat("strap", "#232327", rough=0.8)

    def _strap_black(self):
        return cc0("strap_black", "denim_fabric", 0.06, tint="#2b2c31", rough_mul=1.0)

    def _gauge(self):
        s = Sh("gauge")
        x, _, z = s.xyz()
        a = s.m("ARCTAN2", x, s.m("SUBTRACT", z, 0.12))
        tick = s.m("GREATER_THAN", s.m("SINE", s.m("MULTIPLY", a, 12.0)), 0.9)
        return s.out(base=s.mix(tick, "#f0eee5", "#111111"), rough=0.1, emission="#fff3d0", strength=0.3)

    def _gold(self):
        return cc0("gold", "Metal034", 0.2, tint="#ffd98a", rough_mul=0.35, rough_add=0.05, metal=1.0,
                   emission="#ffb84a", estr=0.12)

    def _gold_glyph(self):
        return cc0("gold_glyph", "Metal034", 0.1, tint="#ffe29e", rough_mul=0.2, rough_add=0.04, metal=1.0,
                   emission="#ffd54a", estr=0.6)

    def _ring_led(self):  # the diffuser: bright, with the LED dots showing through
        s = Sh("ring_led")
        x, _, z = s.xyz()
        a = s.m("ARCTAN2", x, z)
        dots = s.m("MULTIPLY_ADD", s.m("SINE", s.m("MULTIPLY", a, 120.0)), 0.12, 0.88)
        return s.out(base="#fff7e6", rough=0.3, emission="#fff1d0", strength=s.m("MULTIPLY", dots, 5.0))

    def _neon_upper(self):
        return self._shoe_upper_mat("neon_upper", "#8cff5e", "#ff2e88", "#1a0d24", "#ffe600", bright=2.2,
                                    emission="#7dff5a", estr=0.6)

    def _cloud_sole(self):
        return self._shoe_sole_mat("cloud_sole", "#f3ecff", "#c9b8ff", groove=False, emission="#e8dcff", estr=0.35)

    def _neon_lace(self):
        return flat("neon_lace", "#ff2e88", rough=0.6, emission="#ff2e88", strength=0.8)

    # ---- rails
    def _cable(self):  # white TPE sheath: matte, faint mould line along the bottom, soft grime
        s = Sh("cable")
        x, y, z = s.xyz()
        fine = s.noise(scale=90.0, detail=2)
        n = s.noise(scale=5.0, detail=3)
        seam = s.m("MULTIPLY", s.smooth(s.m("ABSOLUTE", x), 0.012, 0.004), s.smooth(z, RAIL_Z - 0.05, RAIL_Z - 0.09))
        col = s.mix(s.m("MULTIPLY", s.smooth(n, 0.55, 0.85), 0.25), "#f3f3f0", "#c8c3b6")
        col = s.mix(s.m("MULTIPLY", seam, 0.3), col, "#d8d8d4")
        return s.out(base=col, rough=s.m("MULTIPLY_ADD", fine, 0.12, 0.38), normal=s.bump(fine, 0.08, 0.002),
                     emission="#ffffff", strength=0.08, **{"Sheen Weight": 0.3})

    def _clip(self):
        return flat("clip", "#2c2d31", rough=0.5)

    def _pipe(self):
        return cc0("pipe", "PaintedMetal006", 0.6, tint="#8ca0b8", rough_mul=0.9, value=1.0)

    def _flange(self):
        return cc0("flange", "Metal027", 0.3, tint="#5a6070", rough_mul=0.9)

    def _plug_metal(self):
        return cc0("plug_metal", "Metal009", 0.12, tint="#e6e7ea", rough_mul=0.3, rough_add=0.08, metal=1.0)

    def _boot(self):
        return flat("boot", "#f2f2ef", rough=0.35, emission="#ffffff", strength=0.06)

    def _port(self):
        return flat("port", "#0a0a0c", rough=0.3, metal=0.6)


M = Mats()


# ============================================================== reel train

TRAIN_W, TRAIN_H, Z_FLOOR = 2.0, 2.8, 0.36
R_TOP, R_BOT, R_END = 0.42, 0.06, 0.12
BAND = (1.1, 2.3)          # black glass band on the sides
SCREEN = (1.2, 2.18)       # side ReelScreen, 2:1 per 2 m module (1.96 x 0.98)
SEG = (2, 2, 6, 6)
WHEEL_Z = 0.05 + 0.235      # wheel centre: tread on the hidden rail head (top 0.05)


def train_profile(d=0.0):
    h = TRAIN_H - Z_FLOOR
    return rrect(TRAIN_W - 2 * d, h - 2 * d, (R_BOT - d, R_BOT - d, R_TOP - d, R_TOP - d), SEG,
                 0.0, Z_FLOOR + h / 2)


def shell_rings(ys_insets):
    return [[V(u, y, v) for u, v in train_profile(d)] for y, d in ys_insets]


def roof_z(x):
    """Top of the shell at lateral x (the flat roof plus its shoulders)."""
    flat_half = TRAIN_W / 2 - R_TOP
    if abs(x) <= flat_half:
        return TRAIN_H
    dx = abs(x) - flat_half
    return TRAIN_H - R_TOP + math.sqrt(max(R_TOP ** 2 - dx ** 2, 0.0))


def side_band(y0, y1, ys, name):
    """Black glass band on both sides (flush + 6 mm), polished edges. No end
    faces (modules tile)."""
    out = []
    for sx in (-1, 1):
        x = sx * (TRAIN_W / 2 + 0.006)
        xi = sx * TRAIN_W / 2
        z0, z1 = BAND
        rows = [V(x, y, z0) for y in ys], [V(x, y, z1) for y in ys]
        face = orient(strip(f"{name}_band{sx}", *rows, material=M.black_glass), direction=(sx, 0, 0))
        top = orient(strip(f"{name}_bt{sx}", [V(xi, y, z1) for y in ys], [V(x, y, z1) for y in ys],
                           material=M.chamfer), direction=(0, 0, 1))
        bot = orient(strip(f"{name}_bb{sx}", [V(x, y, z0) for y in ys], [V(xi, y, z0) for y in ys],
                           material=M.chamfer), direction=(0, 0, -1))
        out += [face, top, bot]
    for o in out:
        o.data.update()
    return out


def side_screens(ys, name):
    out = []
    y0, y1 = ys[0], ys[-1]
    for sx in (-1, 1):
        x = sx * (TRAIN_W / 2 + 0.009)
        z0, z1 = SCREEN
        rows = [V(x, y, z0) for y in ys], [V(x, y, z1) for y in ys]
        o = orient(strip(f"{name}_scr{sx}", *rows, material=M.ReelScreen), direction=(sx, 0, 0))
        mesh.uv_fit_faces(o, material="ReelScreen")
        out.append(o)
    return out


def roof_walkway(y0, y1, ys, name, w=0.36):
    z0, z1 = TRAIN_H - 0.004, TRAIN_H + 0.012
    rows = []
    prof = [(-w, z0), (-w, z1 - 0.004), (-w + 0.006, z1), (w - 0.006, z1), (w, z1 - 0.004), (w, z0)]
    rings = [[V(x, y, z) for x, z in prof] for y in ys]
    o = loft(f"{name}_walk", rings, M.walkway, closed=False, recalc=False)
    return [orient(o, inside=lambda c: (0.0, c.y, TRAIN_H - 0.2))]


def grab_rails(y0, y1, name, posts):
    out = []
    for sx in (-1, 1):
        x = sx * 0.66
        z = roof_z(x) + 0.075
        pts = [V(x, y0, z)] + [V(x, y, z) for y in cuts_y(y0, y1, 1.0)] + [V(x, y1, z)]
        out.append(tube(f"{name}_rail{sx}", pts, 0.017, 5, M.yellow))
        for py in posts:
            out.append(mesh.cylinder(f"{name}_post{sx}", 0.013, 0.08, 5, location=(x, py, z - 0.04), caps=False))
            mesh.apply_transform(out[-1])
            mat.assign(out[-1], M.powder)
    return out


def underframe_skirts(spans, name):
    out = []
    for sx in (-1, 1):
        for y0, y1 in spans:
            x = sx * 0.95
            o = box(f"{name}_skirt", min(x, x + sx * 0.02), max(x, x + sx * 0.02), y0, y1, 0.17, Z_FLOOR + 0.02,
                    M.ti)
            out.append(o)
    return out


def wheelset(y, name):
    out = []
    # (radius, depth inward from the hub face): hub, web, tread, flange
    prof_w = [(0.0, -0.02), (0.09, -0.02), (0.235, 0.0), (0.235, 0.07), (0.27, 0.08), (0.27, 0.11)]
    zc = WHEEL_Z
    for sx in (-1, 1):
        prof = [(r, sx * (0.8 - h)) for r, h in prof_w]
        w = lathe(f"{name}_wheel{sx}", prof, 10, axis="X", material=M.steel, center=(0, y, zc), smooth=40,
                  recalc=False)
        orient(w, inside=(sx * 0.9, y, zc))
        out.append(w)
        ab = box(f"{name}_axlebox{sx}", sx * 0.88 - 0.05, sx * 0.88 + 0.05, y - 0.1, y + 0.1, zc - 0.08, zc + 0.08,
                 M.powder)
        out.append(ab)
        sp = mesh.cylinder(f"{name}_spring{sx}", 0.05, Z_FLOOR - zc - 0.08, 6,
                           location=(sx * 0.88, y, (zc + 0.08 + Z_FLOOR) / 2), caps=False)
        mesh.apply_transform(sp)
        mat.assign(sp, M.spring_coil)
        out.append(sp)
    ax = mesh.cylinder(f"{name}_axle", 0.04, 1.6, 5, location=(0, y, zc), axis="X", caps=False)
    mesh.apply_transform(ax)
    mat.assign(ax, M.steel)
    out.append(ax)
    return out


def hidden_rails(ys, name):
    out = []
    prof = [(-0.04, 0.0), (-0.012, 0.03), (-0.03, 0.05), (0.03, 0.05), (0.012, 0.03), (0.04, 0.0)]
    for sx in (-1, 1):
        rings = [[V(sx * 0.76 + x, y, z) for x, z in prof] for y in ys]
        o = loft(f"{name}_hrail{sx}", rings, M.steel, closed=False, recalc=False)
        out.append(orient(o, inside=lambda c, sx=sx: (sx * 0.76, c.y, 0.02)))
    return out


def build_train_mid():
    ys = [0.0, 1.0, 2.0]
    parts = []
    shell = loft("train_mid", shell_rings([(y, 0.0) for y in ys]), M.ti, closed=True, recalc=False)
    parts.append(orient(shell, inside=lambda c: (0.0, c.y, 1.65)))
    parts += side_band(0, 2, ys, "tm")
    parts += side_screens([0.02, 1.0, 1.98], "tm")
    parts += roof_walkway(0, 2, ys, "tm")
    parts += grab_rails(0.12, 1.88, "tm", (0.3, 1.7))
    # roof: an HVAC vent unit and a hatch, both low (people run here)
    v = box("tm_vent", -0.56, -0.38, 0.35, 1.0, TRAIN_H - 0.01, TRAIN_H + 0.06, M.vent, bevel=0.012, seg=1)
    parts.append(v)
    h = box("tm_hatch", 0.38, 0.56, 1.1, 1.72, TRAIN_H - 0.01, TRAIN_H + 0.022, M.powder, bevel=0.008, seg=1)
    parts.append(h)
    hh = tube("tm_hatch_handle", [V(0.47, 1.62, TRAIN_H + 0.022), V(0.47, 1.62, TRAIN_H + 0.05),
                                  V(0.47, 1.52, TRAIN_H + 0.05), V(0.47, 1.52, TRAIN_H + 0.022)], 0.008, 5, M.chamfer)
    parts.append(hh)
    # underframe
    parts += wheelset(1.0, "tm")
    parts += hidden_rails(ys, "tm")
    # equipment boxes under the floor, between the axles (dark, in shadow)
    parts.append(box("tm_equip", -0.62, 0.62, 0.16, 0.7, 0.2, Z_FLOOR + 0.01, M.powder))
    parts.append(box("tm_equip2", -0.5, 0.5, 1.3, 1.84, 0.24, Z_FLOOR + 0.01, M.powder))
    o = join(parts, "train_mid")
    mesh.smooth(o, 32)
    return [o]


def front_shell(name, back=False):
    """1 m cap: straight from the joint, then the rounded end (phone corner
    radius R_END) and a flat end face: black glass inside a polished chamfer."""
    steps = 5
    rings = [(1.0, 0.0)]
    for k in range(steps + 1):
        th = math.radians(90 * k / steps)
        rings.append((R_END * (1 - math.sin(th)), R_END * (1 - math.cos(th))))
    if back:
        rings = [(1.0 - y, d) for y, d in rings]
    rs = shell_rings(rings)
    bm = new_bm()
    vs, _ = loft_bm(bm, rs, closed=True)
    # chamfer ring + glass end face
    ring_in = [bm.verts.new(V(u, rings[-1][0], v)) for u, v in train_profile(R_END + 0.018)]
    n = len(ring_in)
    last = vs[-1]
    for i in range(n):
        i2 = (i + 1) % n
        bm.faces.new((last[i], last[i2], ring_in[i2], ring_in[i]))
    bm.faces.new(ring_in)
    o = finish(name, bm, recalc=False)
    orient(o, inside=(0.0, 0.4 if back else 0.6, 1.65))
    mat.assign(o, M.ti)
    end_y = rings[-1][0]
    glass = M.frosted if back else M.black_glass
    mat.assign(o, M.chamfer, faces=lambda p: abs(p.center.y - end_y) < 1e-4)
    mat.assign(o, glass, faces=lambda p: abs(p.center.y - end_y) < 1e-4 and len(p.vertices) > 8)
    return o


def antenna_lines(y, name):
    """The phone's antenna bands: thin plastic lines across the frame."""
    out = []
    for sx in (-1, 1):
        x = sx * (TRAIN_W / 2 + 0.002)
        o = quad(f"{name}_ant{sx}", [V(x, y - 0.012, Z_FLOOR + R_BOT), V(x, y + 0.012, Z_FLOOR + R_BOT),
                                     V(x, y + 0.012, BAND[0]), V(x, y - 0.012, BAND[0])], M.antenna)
        out.append(orient(o, direction=(sx, 0, 0)))
    return out


def light_cluster(name, cx, cz, back=False):
    """Headlight/tail-light cluster styled as a phone camera module: a
    rounded plateau with a big lens (the lamp) and a small marker lens."""
    f = 1 if back else -1
    y0 = 1.0 if back else 0.0
    d0, d1 = sorted((y0, y0 + f * 0.035))
    plat = prism(f"{name}_plat", rrect(0.5, 0.3, 0.12, 4, cx, cz), d0, d1, "Y", M.black_glass, bevel=0.012,
                 bseg=2)
    sx = 1 if cx > 0 else -1
    core = M.taillight if back else M.headlight
    a = lens_ring(f"{name}_lamp", cx + sx * 0.09, cz, 0.115, y0 + f * 0.035, f, core=core, segs=16)
    b = lens_ring(f"{name}_mark", cx - sx * 0.14, cz, 0.052, y0 + f * 0.035, f, core=M.taillight if back else core,
                  segs=10)
    return [plat, a, b]


def lens_ring(name, cx, cz, r, y=0.0, face=-1, core=None, ring=None, segs=14):
    """Camera-lens style light: polished ring, black step, coated glass,
    optional emissive core. Faces -Y (face=-1) or +Y."""
    f = face
    prof = [(r * 1.0, y), (r * 1.0, y + f * 0.03), (r * 0.93, y + f * 0.036), (r * 0.8, y + f * 0.03),
            (r * 0.78, y + f * 0.018), (r * 0.62, y + f * 0.02), (r * 0.4, y + f * 0.03), (r * 0.0, y + f * 0.034)]
    o = lathe(name, prof, segs, axis="Y", center=(cx, 0, cz), smooth=50)
    mat.assign(o, ring or M.chamfer)
    mat.assign(o, M.powder, faces=lambda p: math.hypot(p.center.x - cx, p.center.z - cz) < r * 0.8
               and math.hypot(p.center.x - cx, p.center.z - cz) > r * 0.64)
    mat.assign(o, M.lens, faces=lambda p: math.hypot(p.center.x - cx, p.center.z - cz) <= r * 0.64)
    if core is not None:
        mat.assign(o, core, faces=lambda p: math.hypot(p.center.x - cx, p.center.z - cz) < r * 0.5)
    return o


def build_train_front():
    parts = [front_shell("train_front")]
    ys = [R_END, 1.0]
    parts += side_band(R_END, 1.0, ys, "tf")
    parts += roof_walkway(0.3, 1.0, [0.3, 1.0], "tf")
    parts += grab_rails(0.34, 1.0, "tf", (0.5,))
    # front: the phone face. ReelFront screen (1:1), dynamic island, earpiece, lens headlights
    s0, s1 = 0.62, 2.44
    scr = quad("tf_screen", [V(-0.8, -0.003, s0), V(0.8, -0.003, s0), V(0.8, -0.003, s1),
                             V(-0.8, -0.003, s1)], M.ReelFront)
    if scr.data.polygons[0].normal.y > 0:
        scr.data.flip_normals()
    mesh.uv_fit_faces(scr, material="ReelFront")
    parts.append(scr)
    # the dynamic island, stretched wide: selfie camera in the middle, the headlights at its ends
    iz = 2.545
    isl = prism("tf_island", stadium(0.96, 0.17, 6, 0.0, iz), -0.008, 0.0, "Y", M.island)
    cam = lathe("tf_island_cam", [(0.03, -0.0085), (0.02, -0.011), (0.0, -0.012)], 10, axis="Y",
                center=(0.13, 0, iz), material=M.lens)
    parts += [isl, cam]
    for sx in (-1, 1):
        parts.append(lens_ring(f"tf_head{sx}", sx * 0.36, iz, 0.068, -0.008, -1, core=M.headlight, segs=14))
        parts.append(lens_ring(f"tf_mark{sx}", sx * 0.2, iz, 0.03, -0.008, -1, core=M.taillight, segs=8))
    parts += antenna_lines(0.3, "tf")
    # side buttons (the phone's): power right, volume rocker left
    parts.append(prism("tf_power", stadium(0.34, 0.075, 4, 0.62, 0.8), 1.0, 1.024, "X", M.chamfer, bevel=0.006,
                       bseg=1))
    for k, yc in enumerate((0.48, 0.78)):
        parts.append(prism(f"tf_vol{k}", stadium(0.24, 0.075, 4, yc, 0.8), -1.024, -1.0, "X", M.chamfer,
                           bevel=0.006, bseg=1))
    # bumper, pilot (plough) and coupler
    parts.append(box("tf_bumper", -0.86, 0.86, -0.03, 0.1, Z_FLOOR + 0.01, Z_FLOOR + 0.1, M.rubber, bevel=0.022,
                     seg=2))
    pil = prism("tf_pilot", [(0.0, 0.07), (0.04, 0.07), (0.16, Z_FLOOR), (0.1, Z_FLOOR)], -0.84, 0.84, "X",
                M.powder, bevel=0.01, bseg=1)
    parts.append(pil)
    cp = lathe("tf_coupler", [(0.0, -0.07), (0.07, -0.07), (0.085, -0.05), (0.085, 0.04), (0.06, 0.07),
                              (0.06, 0.3)], 10, axis="Y", center=(0, 0, 0.22), material=M.steel, smooth=40)
    parts.append(cp)
    # roof antennas: shark fin + whip
    fin = prism("tf_fin", [(0.42, TRAIN_H), (0.72, TRAIN_H), (0.7, TRAIN_H + 0.1), (0.66, TRAIN_H + 0.12),
                           (0.6, TRAIN_H + 0.11)], 0.4, 0.46, "X", M.powder, bevel=0.012, bseg=2)
    parts.append(fin)
    whip = mesh.cylinder("tf_whip", 0.007, 0.2, 5, location=(-0.42, 0.62, TRAIN_H + 0.1))
    mesh.apply_transform(whip)
    mat.assign(whip, M.powder)
    base = mesh.cylinder("tf_whip_base", 0.03, 0.03, 8, location=(-0.42, 0.62, TRAIN_H + 0.015))
    mesh.apply_transform(base)
    mat.assign(base, M.powder)
    parts += [whip, base]
    parts.append(box("tf_equip", -0.62, 0.62, 0.3, 0.95, 0.2, Z_FLOOR + 0.01, M.powder))
    parts += hidden_rails([0.2, 1.0], "tf")
    o = join(parts, "train_front")
    mesh.smooth(o, 32)
    return [o]


def build_train_back():
    parts = [front_shell("train_back", back=True)]
    parts += side_band(0.0, 1 - R_END, [0.0, 1 - R_END], "tb")
    parts += roof_walkway(0.0, 0.7, [0.0, 0.7], "tb")
    parts += grab_rails(0.0, 0.66, "tb", (0.5,))
    yb = 1.0
    # the phone's back: camera plateau with three lenses, flash (tail light), LiDAR, mic
    plateau = prism("tb_plateau", rrect(0.78, 0.78, 0.2, 5, 0.34, 2.12), yb, yb + 0.05, "Y", M.frosted,
                    bevel=0.02, bseg=2)
    parts.append(plateau)
    for i, (lx, lz) in enumerate(((0.19, 2.29), (0.19, 1.95), (0.5, 2.12))):
        parts.append(lens_ring(f"tb_lens{i}", lx, lz, 0.13, yb + 0.05, 1))
    parts.append(lens_ring("tb_flash", 0.52, 2.37, 0.05, yb + 0.05, 1, core=M.taillight, segs=10))
    parts.append(lathe("tb_lidar", [(0.035, yb + 0.05), (0.03, yb + 0.056), (0.0, yb + 0.058)], 10, axis="Y",
                       center=(0.52, 0, 1.87), material=M.island))
    for sx in (-1, 1):
        parts += light_cluster(f"tb_tl{sx}", sx * 0.55, 0.7, back=True)
    # a small engraved "brand" plate: invented, text-free (a pill)
    parts.append(prism("tb_plate", stadium(0.3, 0.07, 4, -0.3, 1.25), yb, yb + 0.004, "Y", M.chamfer))
    parts.append(box("tb_bumper", -0.86, 0.86, 0.9, 1.03, Z_FLOOR + 0.01, Z_FLOOR + 0.1, M.rubber, bevel=0.022,
                     seg=2))
    cp = lathe("tb_coupler", [(0.06, 0.7), (0.06, 0.93), (0.085, 0.96), (0.085, 1.05), (0.07, 1.07), (0.0, 1.07)],
               10, axis="Y", center=(0, 0, 0.22), material=M.steel, smooth=40)
    parts.append(cp)
    parts += antenna_lines(0.7, "tb")
    parts.append(box("tb_equip", -0.62, 0.62, 0.05, 0.7, 0.2, Z_FLOOR + 0.01, M.powder))
    parts += hidden_rails([0.0, 0.8], "tb")
    o = join(parts, "train_back")
    mesh.smooth(o, 32)
    return [o]


def build_train_warn():
    y0, y1 = 0.26, 0.4
    z0 = TRAIN_H + 0.012
    parts = []
    for sx in (-0.6, 0.6):
        parts.append(box("tw_foot", sx - 0.05, sx + 0.05, y0 + 0.01, y1 - 0.01, TRAIN_H - 0.005, z0 + 0.02, M.powder,
                         bevel=0.005, seg=1))
    hous = box("tw_housing", -0.78, 0.78, y0, y1, z0 + 0.02, z0 + 0.06, M.powder, bevel=0.01, seg=1)
    parts.append(hous)
    lens = prism("tw_lens", stadium(y1 - y0 - 0.01, 0.12, 3, (y0 + y1) / 2, z0 + 0.1), -0.74, 0.74, "X", M.Warn)
    parts.append(lens)
    for k in range(1, 6):
        x = -0.74 + 1.48 * k / 6
        parts.append(box(f"tw_rib{k}", x - 0.012, x + 0.012, y0 - 0.002, y1 + 0.002, z0 + 0.03, z0 + 0.168, M.powder))
    for sx in (-1, 1):
        parts.append(prism(f"tw_cap{sx}", stadium(y1 - y0 + 0.01, 0.14, 3, (y0 + y1) / 2, z0 + 0.1),
                           min(sx * 0.74, sx * 0.79), max(sx * 0.74, sx * 0.79), "X", M.powder))
    o = join(parts, "train_warn")
    mesh.smooth(o, 32)
    return [o]


def build_train_stairs():
    L, H, N = 7.0, TRAIN_H, 14
    parts = []
    slope = H / L
    zl = lambda y: (y + L) * slope  # noqa: E731  ramp line
    for k in range(N):
        y0 = -L + L / N * k
        y1 = y0 + L / N
        zt = H * (k + 0.75) / N
        t = box(f"ts_tread{k}", -0.86, 0.86, y0 + 0.012, y1 - 0.004, zt - 0.03, zt, M.walkway)
        nose = box(f"ts_nose{k}", -0.86, 0.86, y0, y0 + 0.07, zt - 0.045, zt + 0.003, M.yellow)
        parts += [t, nose]
    # stringers: C channels along the slope, cut level at the ground and plumb at the top
    for sx in (-1, 1):
        xw0, xw1 = sorted((sx * 0.86, sx * 0.9))
        top_off, bot_off = 0.16, -0.16
        out = [(-L - top_off / slope + 0.0, 0.0), (0.0, 0.0)]
        poly = [(-L, 0.0), (-L - bot_off / slope, 0.0), (0.0, H + bot_off), (0.0, H + top_off), (-L, top_off)]
        web = prism(f"ts_web{sx}", poly, xw0, xw1, "X", M.galv)
        parts.append(web)
        f0, f1 = sorted((sx * 0.9, sx * 0.96))
        fl = [(-L, top_off - 0.012), (0.0, H + top_off - 0.012), (0.0, H + top_off), (-L, top_off)]
        parts.append(prism(f"ts_flange_t{sx}", fl, f0, f1, "X", M.galv))
        fl = [(-L - bot_off / slope, 0.0), (0.0, H + bot_off), (0.0, H + bot_off + 0.012),
              (-L - (bot_off + 0.012) / slope, 0.0)]
        parts.append(prism(f"ts_flange_b{sx}", fl, f0, f1, "X", M.galv))
        # handrails: top + mid rail, posts
        x = sx * 0.935
        posts_y = [-6.7, -5.3, -3.9, -2.5, -1.1, -0.15]
        rail_top = [V(x, y, zl(y) + 0.98) for y in [-6.85] + cuts_y(-6.85, -0.15, 1.0) + [-0.15]]
        rail_mid = [V(x, y, zl(y) + 0.52) for y in [-6.7] + cuts_y(-6.7, -0.15, 1.0) + [-0.15]]
        parts.append(tube(f"ts_rail{sx}", [V(x, -6.85, zl(-6.85) + 0.18)] + rail_top, 0.024, 6, M.yellow))
        parts.append(tube(f"ts_mrail{sx}", rail_mid, 0.018, 6, M.yellow))
        for py in posts_y:
            zb = zl(py) + top_off
            parts.append(tube(f"ts_post{sx}{py}", [V(x, py, zb - 0.02), V(x, py, zl(py) + 0.98)], 0.022, 6,
                              M.yellow))
    # top landing lip resting on the roof
    parts.append(box("ts_lip", -0.86, 0.86, -0.22, 0.24, H - 0.015, H + 0.006, M.walkway, bevel=0.004, seg=1))
    parts.append(box("ts_lip_nose", -0.86, 0.86, -0.25, -0.18, H - 0.03, H + 0.008, M.yellow, bevel=0.005, seg=1))
    # supports: legs at the top and in the middle, cross braced, on base plates
    for ly, name in ((-0.3, "top"), (-3.6, "mid")):
        ztop = zl(ly) - 0.16
        for sx in (-1, 1):
            x = sx * 0.88
            parts.append(box(f"ts_leg{name}{sx}", x - 0.04, x + 0.04, ly - 0.04, ly + 0.04, 0.02, ztop, M.galv))
            parts.append(box(f"ts_plate{name}{sx}", x - 0.1, x + 0.1, ly - 0.1, ly + 0.1, 0.0, 0.02, M.galv,
                             bevel=0.004, seg=1))
            for bx, by in ((-0.07, -0.07), (0.07, 0.07)):
                b = mesh.cylinder("ts_bolt", 0.012, 0.02, 6, location=(x + bx, ly + by, 0.03))
                mesh.apply_transform(b)
                mat.assign(b, M.steel)
                parts.append(b)
        # X bracing between the legs (flat bars)
        for a, b in ((-1, 1), (1, -1)):
            parts.append(tube(f"ts_brace{name}{a}", [V(a * 0.86, ly, 0.15), V(b * 0.86, ly, ztop - 0.08)], 0.018, 4,
                              M.galv, section=[(1, 0.25), (-1, 0.25), (-1, -0.25), (1, -0.25)]))
    for sx in (-1, 1):
        parts.append(box(f"ts_foot{sx}", sx * 0.93 - 0.08, sx * 0.93 + 0.08, -7.02, -6.55, 0.0, 0.02, M.galv,
                         bevel=0.004, seg=1))
    o = join(parts, "train_stairs")
    mesh.subdivide_along(o, "Y", positions=[-6.0, -5.0, -4.0, -3.0, -2.0, -1.0])
    mesh.smooth(o, 32)
    return [o]


# ============================================================== barriers

def hex_bolt(name, x, y, z, r=0.014, h=0.012, axis="Z", material=None):
    o = mesh.cylinder(name, r, h, 6, location=(x, y, z), axis=axis)
    mesh.apply_transform(o)
    mat.assign(o, material or M.steel)
    return o


def build_barrier_low():
    parts = []
    z0, z1 = 0.38, 0.9
    body = prism("bl_body", rrect(1.9, z1 - z0, 0.17, 6, 0.0, (z0 + z1) / 2), -0.1, 0.1, "Y", M.frost, bevel=0.03,
                 bseg=3)
    parts.append(body)
    # the notification canvas: 4:1, corner radius matching the canvas (40/128 of its height)
    fh = 0.46
    face = prism("bl_face", rrect(4 * fh, fh, 0.3125 * fh, 6, 0.0, (z0 + z1) / 2), -0.1025, -0.1, "Y",
                 M.NotifFace)
    mat.assign(face, M.frost, faces=lambda p: p.normal.y > -0.9)
    mesh.uv_fit_faces(face, material="NotifFace", faces=lambda p: p.normal.y < -0.9)
    parts.append(face)
    for sx in (-1, 1):
        x = sx * 0.62
        parts.append(box("bl_post", x - 0.03, x + 0.03, -0.03, 0.03, 0.08, z0 + 0.04, M.galv))
        # clamp bracket gripping the pill, bolted through
        parts.append(box("bl_clamp", x - 0.07, x + 0.07, -0.115, 0.115, z0 - 0.05, z0 + 0.03, M.galv, bevel=0.008,
                         seg=1))
        for by in (-0.118, 0.118):
            for bx in (-0.035, 0.035):
                parts.append(hex_bolt("bl_bolt", x + bx, by, z0 - 0.012, 0.012, 0.012, axis="Y"))
        # foot: a flat bar across, rubber pads at the ends
        parts.append(box("bl_foot", x - 0.04, x + 0.04, -0.22, 0.22, 0.012, 0.04, M.galv, bevel=0.006, seg=1))
        for fy in (-0.19, 0.19):
            parts.append(box("bl_pad", x - 0.045, x + 0.045, fy - 0.035, fy + 0.035, 0.0, 0.014, M.rubber))
        parts.append(hex_bolt("bl_fbolt", x, 0.0, 0.046, 0.018, 0.014))
    parts.append(box("bl_rail", -0.62, 0.62, -0.025, 0.025, 0.1, 0.15, M.galv, bevel=0.006, seg=1))
    o = join(parts, "barrier_low")
    mesh.smooth(o, 35)
    return [o]


def i_beam(name, x, z0, z1, depth=0.14, width=0.1, tf=0.014, tw=0.01, material=None):
    """I-beam standing up: flanges face -Y/+Y (outline in the XY plane)."""
    hd, hw = depth / 2, width / 2
    out = [(-hw, -hd), (hw, -hd), (hw, -hd + tf), (tw / 2, -hd + tf), (tw / 2, hd - tf), (hw, hd - tf), (hw, hd),
           (-hw, hd), (-hw, hd - tf), (-tw / 2, hd - tf), (-tw / 2, -hd + tf), (-hw, -hd + tf)]
    out = [(u + x, v) for u, v in out]
    return prism(name, out, z0, z1, "Z", material or M.galv)


def build_barrier_high():
    parts = []
    zb, zt = 1.05, 3.2
    cab_top = 2.2
    for sx in (-1, 1):
        x = sx * 1.05
        parts.append(i_beam(f"bh_pole{sx}", x, 0.02, zt, material=M.powder))
        parts.append(box("bh_cap", x - 0.06, x + 0.06, -0.08, 0.08, zt - 0.012, zt, M.powder))
        bx0 = x - sx * 0.08
        parts.append(box("bh_base", min(bx0, x + sx * 0.05), max(bx0, x + sx * 0.05), -0.17, 0.17, 0.0, 0.022,
                         M.powder, bevel=0.005, seg=1))
        for bx in (x - sx * 0.05, x + sx * 0.025):
            for by in (-0.13, 0.13):
                parts.append(hex_bolt("bh_anchor", bx, by, 0.03, 0.016, 0.018))
        for gy in (-1, 1):  # gusset plates welded to the flanges
            parts.append(prism("bh_gusset", [(gy * 0.07, 0.022), (gy * 0.14, 0.022), (gy * 0.07, 0.2)],
                               x - 0.006, x + 0.006, "X", M.powder))
        # bolted angle brackets holding the cabinet
        for bz in (zb + 0.12, cab_top - 0.1):
            parts.append(box("bh_bracket", x - sx * 0.1, x - sx * 0.05, -0.1, 0.1, bz - 0.05, bz + 0.05, M.galv))
            for by in (-0.101, 0.101):
                parts.append(hex_bolt("bh_bolt", x - sx * 0.075, by, bz, 0.013, 0.012, axis="Y"))
    # LED cabinet: AdFace screens on both sides, hazard band on its bottom edge (roll under it!)
    parts.append(box("bh_cab", -1.0, 1.0, -0.09, 0.09, zb + 0.05, cab_top, M.powder, bevel=0.015, seg=2))
    parts.append(box("bh_hazard", -1.0, 1.0, -0.092, 0.092, zb, zb + 0.055, M.hazard))
    for sy in (-1, 1):
        y = sy * 0.093
        o = quad("bh_ad", [V(-0.96, y, 1.195), V(0.96, y, 1.195), V(0.96, y, 2.155), V(-0.96, y, 2.155)], M.AdFace)
        orient(o, direction=(0, sy, 0))
        mesh.uv_fit_faces(o, material="AdFace")
        parts.append(o)
        # a thin bezel lip around the screen
        zc = (1.195 + 2.155) / 2
        parts.append(frame_ring("bh_bezel", rrect(1.99, 1.03, 0.02, 1, 0, zc), rrect(1.92, 0.96, 0.0, 1, 0, zc),
                                y + sy * 0.008, y - sy * 0.001, "Y", M.powder))
    # vents on the cabinet top
    parts.append(box("bh_vent", -0.8, 0.8, -0.06, 0.06, cab_top, cab_top + 0.02, M.vent))
    # truss header up to 3.2: chords + Warren diagonals (square tubes)
    sq = [(1, 1), (-1, 1), (-1, -1), (1, -1)]
    parts.append(box("bh_chord_t", -1.0, 1.0, -0.045, 0.045, zt - 0.09, zt, M.galv))
    parts.append(box("bh_chord_b", -1.0, 1.0, -0.045, 0.045, cab_top + 0.02, cab_top + 0.1, M.galv))
    xs = [-1.0 + 2.0 * k / 5 for k in range(6)]
    for k in range(5):
        za, zc = (cab_top + 0.1, zt - 0.09) if k % 2 == 0 else (zt - 0.09, cab_top + 0.1)
        parts.append(tube(f"bh_diag{k}", [V(xs[k] + (0.02 if k == 0 else 0), 0, za),
                                          V(xs[k + 1] - (0.02 if k == 4 else 0), 0, zc)], 0.022, 4, M.galv,
                          section=sq, up=(0, 1, 0), smooth=None))
    # two floodlights on arms, aimed back down at the screen (the runner's side)
    for sx in (-0.55, 0.55):
        parts.append(tube("bh_arm", [V(sx, -0.045, zt - 0.05), V(sx, -0.34, zt - 0.02)], 0.018, 6, M.powder))
        head = box("bh_lamp", sx - 0.11, sx + 0.11, -0.44, -0.3, zt - 0.1, zt + 0.0, M.powder, bevel=0.012, seg=1)
        xform(head, loc=(0, 0, 0))
        parts.append(head)
        lensq = quad("bh_lamp_lens", [V(sx - 0.095, -0.43, zt - 0.101), V(sx + 0.095, -0.43, zt - 0.101),
                                      V(sx + 0.095, -0.31, zt - 0.101), V(sx - 0.095, -0.31, zt - 0.101)], M.lamp)
        parts.append(orient(lensq, direction=(0, 0, -1)))
    o = join(parts, "barrier_high")
    mesh.smooth(o, 35)
    return [o]


# ============================================================== habits

def build_habit_water():
    parts = []
    cz = 0.032  # coaster top
    coaster = lathe("hw_coaster", [(0.0, 0.0), (0.42, 0.0), (0.43, 0.008), (0.43, cz - 0.008), (0.42, cz),
                                   (0.0, cz)], 32, material=M.cork, smooth=40)
    parts.append(coaster)
    z = lambda v: cz + v  # noqa: E731
    wall = lambda zz: 0.29 + (0.343 - 0.29) * (zz - 0.13) / (0.975 - 0.13)  # noqa: E731  inner wall radius
    prof = [(0.0, z(0.0)), (0.25, z(0.0)), (0.288, z(0.006)), (0.303, z(0.03)), (0.36, z(0.94)), (0.361, z(0.955)),
            (0.357, z(0.962)), (0.349, z(0.962)), (0.344, z(0.953)), (wall(0.13) + 0.001, z(0.13)),
            (0.27, z(0.098)), (0.12, z(0.088)), (0.0, z(0.086))]
    glass = lathe("hw_glass", prof, 40, material=M.Glass, smooth=60, recalc=True)
    uv_box_fit(glass, "Glass", 0.5)
    parts.append(glass)
    fill = 0.7
    r_top = wall(fill) - 0.003
    wprof = [(0.0, z(0.089)), (0.12, z(0.091)), (0.268, z(0.1)), (wall(0.13) - 0.002, z(0.13)),
             (wall(0.4) - 0.003, z(0.4)), (r_top, z(fill)), (r_top - 0.002, z(fill + 0.014)),
             (r_top - 0.012, z(fill + 0.004)), (r_top - 0.04, z(fill)), (0.0, z(fill - 0.002))]
    water = lathe("hw_water", wprof, 40, material=M.water, smooth=60, recalc=True)
    parts.append(water)
    o = join(parts, "habit_water")
    return [o]


def book(name, L, W, T, cloth, spine=-1, board=0.022, sq=0.016):
    """Hardcover lying flat: C-shaped case (boards + rounded spine, joint
    grooves) over a page block with a slightly concave fore-edge. Spine at
    y = spine * W/2. Local origin: bottom centre."""
    hw = W / 2
    b = board
    outer = [(hw, 0.0), (-hw + 0.06, 0.0), (-hw + 0.045, 0.007), (-hw + 0.03, 0.0), (-hw, 0.0)]
    n = 7
    for k in range(1, n):
        a = math.pi * k / n
        outer.append((-hw - 0.028 * math.sin(a), T / 2 - T / 2 * math.cos(a)))
    outer += [(-hw, T), (-hw + 0.03, T), (-hw + 0.045, T - 0.007), (-hw + 0.06, T), (hw, T), (hw, T - b)]
    inner = [(-hw + 0.012, T - b)]
    for k in range(n - 1, 0, -1):
        a = math.pi * k / n
        inner.append((-hw - 0.012 * math.sin(a) + 0.004, T / 2 - (T / 2 - b) * math.cos(a)))
    inner += [(-hw + 0.012, b), (hw, b)]
    outline = outer + inner
    case = prism(f"{name}_case", outline, -L / 2, L / 2, "X", cloth, smooth=35)
    pages = prism(f"{name}_pages", [(-hw + 0.01, b), (hw - sq, b), (hw - sq - 0.01, T / 2), (hw - sq, T - b),
                                    (-hw + 0.01, T - b)], -L / 2 + sq, L / 2 - sq, "X", M.paper)
    parts = [case, pages]
    o = join(parts, name)
    if spine > 0:
        xform(o, rot=(0, 0, math.pi))
    return o


def build_habit_books():
    specs = [(1.0, 0.57, 0.29, M.cloth_green, -1, 0.04), (0.92, 0.56, 0.25, M.cloth_red, 1, -0.07),
             (0.84, 0.52, 0.23, M.cloth_navy, -1, 0.11)]
    z = 0.0
    parts = []
    for i, (L, W, T, cl, sp, rot) in enumerate(specs):
        b = book(f"hb_book{i}", L, W, T, cl, sp)
        xform(b, loc=(0.02 * (i - 1), 0.0, z), rot=(0, 0, rot))
        parts.append(b)
        z += T
    # a satin bookmark ribbon hanging out of the middle book's tail
    t0 = specs[0][2] + specs[1][2] - 0.03
    rib = [V(-0.3, 0.0, t0), V(-0.44, 0.02, t0 + 0.005), V(-0.47, 0.03, t0 - 0.03), V(-0.475, 0.035, t0 - 0.2)]
    r = tube("hb_ribbon", rib, 0.012, 4, M.ribbon, section=[(1.0, 0.12), (-1.0, 0.12), (-1.0, -0.12), (1.0, -0.12)],
             up=(0, 0, 1))
    xform(r, rot=(0, 0, -0.1))
    parts.append(r)
    o = join(parts, "habit_books")
    return [o]


# ---------------------------------------------------------------- shoes

def _interp(pts, t):
    for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
        if t0 <= t <= t1:
            k = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            k = k * k * (3 - 2 * k)
            return v0 + (v1 - v0) * k
    return pts[-1][1] if t > pts[-1][0] else pts[0][1]


def _ss(a, b, x):
    k = min(max((x - a) / (b - a), 0.0), 1.0)
    return k * k * (3 - 2 * k)


def shoe(name, L=1.12, mats=None, n_sec=28, n_ring=22, n_out=44, stack=(0.16, 0.1), cloud=0.0, lace_n=6,
         bow=True):
    """A running shoe pointing +X, heel at x = -L/2, on the ground. Returns
    the joined object. mats: dict upper, sole, lace. Overlays (heel counter,
    toe cap, eyestay, mudguard), the lining and the outsole band are drawn by
    the shaders from a per-vertex attribute "sh" = (t heel..toe, h, s)."""
    wl = [(0.0, 0.0), (0.03, 0.105), (0.1, 0.145), (0.25, 0.15), (0.45, 0.152), (0.68, 0.19), (0.82, 0.188),
          (0.93, 0.15), (0.985, 0.08), (1.0, 0.0)]
    wm = [(0.0, 0.0), (0.03, 0.1), (0.1, 0.14), (0.25, 0.14), (0.45, 0.115), (0.68, 0.192), (0.82, 0.195),
          (0.93, 0.155), (0.985, 0.08), (1.0, 0.0)]
    sc = L / 1.12
    zb = lambda t: sc * (0.075 * _ss(0.7, 1.0, t) ** 1.4 + 0.022 * (1 - _ss(0.0, 0.1, t)))  # noqa: E731
    zm = lambda t: zb(t) + sc * (stack[0] + (stack[1] - stack[0]) * _ss(0.2, 0.78, t))  # noqa: E731
    zt = lambda t: zm(t) - sc * 0.1 + sc * _interp([(0.0, 0.3), (0.05, 0.31), (0.12, 0.27), (0.33, 0.25),
                                                    (0.45, 0.245), (0.62, 0.205), (0.8, 0.15), (0.93, 0.11),
                                                    (1.0, 0.07)], t) + sc * 0.1  # noqa: E731
    X = lambda t: -L / 2 + L * t  # noqa: E731
    half = lambda t, side: sc * _interp(wl if side > 0 else wm, t)  # noqa: E731

    def attr_bm():
        bm = new_bm()
        return bm, bm.verts.layers.float_color.new("sh")

    # --- sole: plan outline lofted through levels (outsole, bulging foam, rounded top edge)
    ts = [0.5 - 0.5 * math.cos(math.pi * k / (n_out // 2)) for k in range(n_out // 2 + 1)]
    plan = [(t, 1) for t in ts] + [(t, -1) for t in reversed(ts[1:-1])]
    levels = [(0.0, 0.94, 0.0), (0.0, 1.0, 0.012), (0.0, 1.0, 0.03), (0.5, 1.035, None), (0.85, 1.0, None),
              (1.0, 0.95, None)]
    if cloud > 0:  # two stacked puffs, lobed along the length
        levels = [(0.0, 0.9, 0.0), (0.0, 1.0, 0.012), (0.22, 1.07, None), (0.42, 0.97, None), (0.64, 1.08, None),
                  (0.86, 1.0, None), (1.0, 0.94, None)]
    bm, lay = attr_bm()
    rings = []
    for li, (f, k, dz) in enumerate(levels):
        ring = []
        for t, side in plan:
            w = half(t, side) + 0.012 * sc
            if cloud > 0 and 0 < li < len(levels) - 1:
                w += cloud * sc * (0.5 + 0.5 * math.cos(t * TAU * 5.0 + (0.0 if li < 3 else math.pi))) * (k - 0.9) * 8
            zz = zb(t) + (dz * sc if dz is not None else f * (zm(t) - zb(t)))
            x = X(t) + (0.012 * sc if (t < 0.02 and li == 0) else 0) - (0.01 * sc if (t > 0.98 and li == 0) else 0)
            v = bm.verts.new(V(x, side * w * k, zz))
            v[lay] = (t, (zz - zb(t)) / sc, side, 1.0)
            ring.append(v)
        rings.append(ring)
    n = len(plan)
    for j in range(len(rings) - 1):
        for i in range(n):
            i2 = (i + 1) % n
            bm.faces.new((rings[j][i], rings[j][i2], rings[j + 1][i2], rings[j + 1][i]))
    bm.faces.new(list(reversed(rings[0])))
    bm.faces.new(rings[-1])
    sole = finish(f"{name}_sole", bm, mats["sole"])
    # --- upper: superellipse arches over the sole, collar opening at the heel
    tsec = [0.5 - 0.5 * math.cos(math.pi * k / (n_sec - 1)) for k in range(n_sec)]
    bm, lay = attr_bm()
    urings = []
    for t in tsec:
        base = zm(t) - 0.02 * sc
        top = zt(t)
        ring = []
        collar = _ss(0.03, 0.09, t) * (1 - _ss(0.3, 0.38, t))
        for i in range(n_ring):
            ph = math.pi * i / (n_ring - 1)  # 0 lateral bottom .. pi medial bottom
            c, sn = math.cos(ph), math.sin(ph)
            e = 2 / 2.6
            w = half(t, 1 if c >= 0 else -1) * 0.97
            y = w * math.copysign(abs(c) ** e, c)
            h = abs(sn) ** e
            zz = base + (top - base) * h
            if collar > 0 and abs(c) < 0.62:  # foot opening: the top folds down into the lining
                k = 1 - (abs(c) / 0.62) ** 2
                zz -= collar * k * 0.2 * sc
                y *= 1 - 0.3 * collar * k
            v = bm.verts.new(V(X(t), y, zz))
            v[lay] = (t, h, c, collar * (1 - _ss(0.5, 0.62, abs(c))))
            ring.append(v)
        v = bm.verts.new(V(X(t), 0.0, base - 0.01 * sc))
        v[lay] = (t, 0.0, 0.0, 0.0)
        ring.append(v)
        urings.append(ring)
    m_ = len(urings[0])
    for j in range(len(urings) - 1):
        for i in range(m_):
            i2 = (i + 1) % m_
            bm.faces.new((urings[j][i], urings[j][i2], urings[j + 1][i2], urings[j + 1][i]))
    upper = finish(f"{name}_upper", bm, mats["upper"])
    parts = [sole, upper]
    # --- tongue (padded, sticking up out of the collar)
    tr = []
    for k in range(6):
        u = k / 5
        t = 0.52 - 0.2 * u
        zz = zt(0.52) - 0.02 * sc + (0.1 * sc) * u ** 1.3
        w = (0.085 - 0.01 * u) * sc
        tr.append([V(X(t), yy * w, zz + dz * sc) for yy, dz in
                   ((-1, 0), (-0.8, 0.018), (0.8, 0.018), (1, 0), (0.8, -0.012), (-0.8, -0.012))])
    tongue = loft(f"{name}_tongue", tr, mats["upper"], closed=True, cap0=False, cap1=True, smooth=50)
    parts.append(tongue)
    # --- laces: criss-cross flat bands between the eyelet rows, a bow at the top
    lz = lambda t, y: zt(t) - (0.02 * sc) * (y / (0.08 * sc)) ** 2 + 0.012 * sc  # noqa: E731
    flat_sec = [(0.3, 1.0), (-0.3, 1.0), (-0.3, -1.0), (0.3, -1.0)]
    rows = [0.62 - (0.62 - 0.39) * k / (lace_n - 1) for k in range(lace_n)]
    for k in range(lace_n - 1):
        ta, tb = rows[k], rows[k + 1]
        for sgn in (-1, 1):
            ya, yb = sgn * 0.075 * sc, -sgn * 0.075 * sc
            pts = [V(X(ta), ya, lz(ta, ya)), V(X((ta + tb) / 2), 0.0, lz((ta + tb) / 2, 0) + 0.006 * sc),
                   V(X(tb), yb, lz(tb, yb))]
            parts.append(tube(f"{name}_lace", pts, 0.012 * sc, 4, mats["lace"], section=flat_sec, up=(0, 0, 1)))
    if bow:
        tb = rows[-1]
        for sgn in (-1, 1):  # bow loops + ends
            c = V(X(tb) - 0.01 * sc, 0.0, lz(tb, 0) + 0.008 * sc)
            loop = [c + V(-0.025 * sc * math.sin(a), sgn * 0.07 * sc * math.sin(a / 2) ** 0.8, 0.03 * sc * math.sin(a))
                    for a in [math.pi * 2 * k / 8 for k in range(9)]]
            parts.append(tube(f"{name}_bow", loop, 0.011 * sc, 4, mats["lace"], section=flat_sec, up=(0, 0, 1)))
            end = [c, c + V(-0.04 * sc, sgn * 0.04 * sc, -0.012 * sc), c + V(-0.05 * sc, sgn * 0.085 * sc, -0.07 * sc)]
            parts.append(tube(f"{name}_lend", end, 0.011 * sc, 4, mats["lace"], section=flat_sec, up=(0, 0, 1)))
    o = join(parts, name)
    mesh.smooth(o, 60)
    return o


def build_habit_shoe():
    mats = dict(upper=M.shoe_upper, sole=M.shoe_sole, lace=M.lace)
    o = shoe("habit_shoe", 1.12, mats)
    xform(o, rot=(0, 0, 0.0))
    return [o]


def build_habit_phone():
    parts = []
    tilt = math.radians(10)
    W, H, R = 0.46, 0.93, 0.07
    cw, ch, cr = W + 0.026, H + 0.026, R + 0.013
    zc = H / 2 + 0.013
    # case: floral shell with a raised front lip
    case = prism("hp_case", rrect(cw, ch, cr, 6, 0, zc), -0.03, 0.05, "Y", M.floral, bevel=0.014, bseg=2)
    parts.append(case)
    lip = frame_ring("hp_lip", rrect(cw - 0.004, ch - 0.004, cr - 0.002, 6, 0, zc),
                     rrect(W + 0.002, H + 0.002, R + 0.001, 6, 0, zc), -0.037, -0.029, "Y", M.floral)
    parts.append(lip)
    # the phone's white front glass, screen, home button, earpiece and camera
    front = prism("hp_front", rrect(W, H, R, 6, 0, zc), -0.031, -0.028, "Y", M.white_front)
    parts.append(front)
    sw, sh = 0.38, 0.76
    sz0 = zc - sh / 2 + 0.01
    scr = quad("hp_screen", [V(-sw / 2, -0.0315, sz0), V(sw / 2, -0.0315, sz0), V(sw / 2, -0.0315, sz0 + sh),
                             V(-sw / 2, -0.0315, sz0 + sh)], M.MumFace)
    orient(scr, direction=(0, -1, 0))
    mesh.uv_fit_faces(scr, material="MumFace")
    parts.append(scr)
    hb_z = sz0 / 2 + (zc - H / 2) / 2
    parts.append(lathe("hp_home", [(0.036, -0.0312), (0.034, -0.0322), (0.03, -0.0318), (0.0, -0.0305)], 20, axis="Y",
                       center=(0, 0, hb_z), material=M.chrome, smooth=60))
    top_z = (sz0 + sh + zc + H / 2) / 2
    parts.append(prism("hp_ear", stadium(0.075, 0.012, 3, 0.0, top_z), -0.0318, -0.031, "Y", M.island))
    parts.append(lathe("hp_cam", [(0.009, -0.0318), (0.0, -0.0322)], 8, axis="Y", center=(-0.07, 0, top_z),
                       material=M.lens))
    # tilt back and stand it on a cheap aluminium desk stand
    ph = join(parts, "hp_phone")
    xform(ph, loc=(0, 0.02, 0.036), rot=(-tilt, 0, 0))
    st = []
    st.append(prism("hp_base", rrect(0.36, 0.34, 0.04, 3, 0.0, 0.07), 0.0, 0.018, "Z", M.alu, bevel=0.006,
                    bseg=1))
    st.append(box("hp_ledge", -0.15, 0.15, -0.08, -0.03, 0.0, 0.07, M.alu, bevel=0.008, seg=1))
    back = box("hp_back", -0.12, 0.12, 0.0, 0.018, 0.0, 0.5, M.alu, bevel=0.006, seg=1)
    xform(back, rot=(-tilt, 0, 0))
    xform(back, loc=(0, 0.1, 0.012))
    st.append(back)
    for sx in (-0.13, 0.13):
        st.append(box("hp_foot", sx - 0.03, sx + 0.03, 0.14, 0.2, -0.004, 0.004, M.rubber))
    o = join([ph] + st, "habit_phone")
    mesh.smooth(o, 40)
    return [o]


# ============================================================== the Thumb

# key sections along the lane: (y, bottom z, top z, half width, pad flatness)
THUMB_KEYS = [(0.0, 2.72, 2.72, 0.0, 0.0), (0.06, 2.2, 3.3, 0.52, 0.0), (0.2, 1.92, 3.5, 0.8, 0.0),
              (0.45, 1.7, 3.6, 0.95, 0.0), (0.9, 1.44, 3.5, 0.98, 0.0), (1.5, 1.18, 3.24, 0.93, 0.0),
              (2.3, 0.92, 2.88, 0.87, 0.0), (3.1, 0.66, 2.52, 0.84, 0.1), (3.8, 0.42, 2.24, 0.84, 0.2),
              (4.3, 0.24, 2.05, 0.86, 0.3), (4.75, 0.1, 1.86, 0.92, 0.5), (5.4, 0.02, 1.74, 0.99, 0.8),
              (6.2, 0.0, 1.7, 1.0, 1.0), (6.9, 0.01, 1.64, 0.99, 1.0), (7.4, 0.05, 1.54, 0.92, 0.9),
              (7.72, 0.14, 1.36, 0.78, 0.6), (7.9, 0.3, 1.12, 0.56, 0.3), (7.985, 0.52, 0.84, 0.2, 0.1),
              (8.0, 0.66, 0.66, 0.0, 0.0)]


def thumb_section(y):
    ks = THUMB_KEYS
    for a, b in zip(ks, ks[1:]):
        if a[0] <= y <= b[0]:
            k = (y - a[0]) / (b[0] - a[0])
            k2 = k * k * (3 - 2 * k)
            lin = [a[i] + (b[i] - a[i]) * k for i in range(1, 5)]
            sm = [a[i] + (b[i] - a[i]) * k2 for i in range(1, 5)]
            # widths blend smoothly, heights linearly (keeps the tilt straight)
            return lin[0], lin[1], sm[2] * 0.5 + lin[2] * 0.5, lin[3]
    return ks[-1][1:]


def thumb_point(y, th):
    """Surface point at lane distance y and angle th (0 right, pi/2 top)."""
    zb, zt, hw, flat = thumb_section(y)
    c, s_ = math.cos(th), math.sin(th)
    top = s_ >= 0
    zc = zb + (zt - zb) * 0.47
    e_top = 2 / 2.2
    e_bot = 2 / (2.2 + 2.2 * flat)  # the pressed pad flattens
    e = e_top if top else e_bot
    x = hw * math.copysign(abs(c) ** e, c)
    z = zc + ((zt - zc) if top else (zc - zb)) * math.copysign(abs(s_) ** e, s_)
    return V(x, y, z)


def build_thumb():
    n_ring = 44
    ys = []
    y = 0.0
    while y < 8.0:
        ys.append(y)
        # dense at the rounded ends, ~0.2 m along the body
        step = 0.03 if y < 0.12 or y > 7.86 else (0.08 if y < 0.5 or y > 7.5 else 0.21)
        y += step
    ys.append(8.0)
    rings = [[thumb_point(yy, TAU * i / n_ring) for i in range(n_ring)] for yy in ys]
    bm = new_bm()
    vs, _ = loft_bm(bm, rings, True)
    # the nail bed: sink the skin under the nail a little, raise the folds around it
    for ring in vs:
        for v in ring:
            nail_u, nail_v, inside = _nail_uv(v.co)
            if nail_v is None:
                continue
            fold = math.exp(-((nail_v - 0.0) / 0.05) ** 2) * 0.03 + math.exp(-((abs(nail_u) - 1.0) / 0.08) ** 2) * 0.02
            dent = -0.02 if inside else 0.0
            v.co.z += (fold * (1.0 if nail_v > -0.2 else 0.0) + dent)
    finger = finish("thumb", bm, M.skin, smooth=None)
    mesh.smooth(finger, 80)
    nail = build_nail()
    o = join([finger, nail], "thumb")
    mesh.smooth(o, 70)
    o["atlas_weight"] = 2.0
    return [o]


NAIL_Y0, NAIL_Y1 = 5.25, 7.78  # proximal fold .. free edge


def _nail_w(y):
    k = (y - NAIL_Y0) / (NAIL_Y1 - NAIL_Y0)
    return 0.58 + 0.08 * math.sin(min(max(k, 0), 1) * math.pi * 0.8)


def _nail_uv(co):
    """(u across -1..1, v along 0..1, inside) for skin points near the nail,
    else (None, None, False)."""
    if co.z < 1.0 or not (NAIL_Y0 - 0.3 < co.y < NAIL_Y1):
        return None, None, False
    w = _nail_w(co.y)
    u = co.x / w
    v = (co.y - NAIL_Y0) / (NAIL_Y1 - NAIL_Y0)
    if abs(u) > 1.3:
        return None, None, False
    return u, v, abs(u) < 0.97 and v > 0.02


def build_nail():
    nu, nv = 12, 14
    bm = new_bm()
    top, bot = [], []
    for j in range(nv + 1):
        v = j / nv
        y = NAIL_Y0 + (NAIL_Y1 - NAIL_Y0) * v
        w = _nail_w(y)
        rt, rb = [], []
        for i in range(nu + 1):
            u = -1 + 2 * i / nu
            x = u * w * 0.98
            # surface height at this x (search the ring angle with that x on the top)
            p = _surface_top(y, x)
            curve = 0.05 * (1 - u * u)  # the nail's own transverse C-curve
            tuck = 0.03 * _ss(0.8, 1.0, abs(u)) + 0.03 * (1 - _ss(0.0, 0.08, v))
            z = p.z + 0.035 + curve * 0.5 - tuck
            if y > 7.5:  # the free edge runs past the fingertip, level-ish
                z = max(z, _surface_top(7.5, x).z + 0.035 + curve * 0.5 - tuck - (y - 7.5) * 0.6)
            rt.append(bm.verts.new(V(x, y, z)))
            rb.append(bm.verts.new(V(x * 0.99, y - 0.01, z - 0.035)))
        top.append(rt)
        bot.append(rb)
    for j in range(nv):
        for i in range(nu):
            bm.faces.new((top[j][i], top[j][i + 1], top[j + 1][i + 1], top[j + 1][i]))
            bm.faces.new((bot[j][i], bot[j + 1][i], bot[j + 1][i + 1], bot[j][i + 1]))
    for i in range(nu):  # free edge thickness
        bm.faces.new((top[nv][i], top[nv][i + 1], bot[nv][i + 1], bot[nv][i]))
    for j in range(nv):  # side walls (tucked into the skin)
        bm.faces.new((top[j][0], top[j + 1][0], bot[j + 1][0], bot[j][0]))
        bm.faces.new((top[j][nu], bot[j][nu], bot[j + 1][nu], top[j + 1][nu]))
    o = finish("thumb_nail", bm, M.nail, recalc=True)
    return o


def _surface_top(y, x):
    lo, hi = 0.0, math.pi / 2
    for _ in range(30):  # x decreases from th=0 to th=pi/2 on the top-right; mirror for negative x
        mid = (lo + hi) / 2
        if thumb_point(y, mid).x > abs(x):
            lo = mid
        else:
            hi = mid
    p = thumb_point(y, (lo + hi) / 2)
    return V(x, y, p.z)


# ============================================================== pads

def build_pad_ramp():
    L, H, hw = 6.0, 1.4, 0.95
    sl = H / L
    parts = []
    ys = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    # solid wedge under the glass face
    wedge = prism("pr_wedge", [(0.0, 0.0), (L, 0.0), (L, H), (0.0, 0.0)][:3], -0.86, 0.86, "X", M.powder,
                  cuts=None)
    parts.append(wedge)
    # glass face (RampFace), v up the slope
    y0, y1 = 0.16, L - 0.05
    zf = lambda y: y * sl + 0.012  # noqa: E731
    rows = [[V(-0.84, y, zf(y)) for y in [y0] + ys[1:-1] + [y1]], [V(0.84, y, zf(y)) for y in [y0] + ys[1:-1] + [y1]]]
    face = orient(strip("pr_face", rows[0], rows[1], M.RampFace), direction=(0, -sl, 1))
    mesh.uv_fit_faces(face, material="RampFace")
    parts.append(face)
    # side cheeks: brushed aluminium, slope + 0.1 lip, LED strip on the inside top
    for sx in (-1, 1):
        x0, x1 = sorted((sx * 0.84, sx * hw))
        cheek = prism("pr_cheek", [(0.0, 0.0), (L, 0.0), (L, H + 0.1), (0.0, 0.1)], x0, x1, "X", M.brushed,
                      bevel=0.008, bseg=1)
        parts.append(cheek)
        xi = sx * 0.838
        led = [V(xi, y, y * sl + 0.075) for y in [0.05] + ys[1:-1] + [L - 0.05]]
        led2 = [V(xi, y, y * sl + 0.055) for y in [0.05] + ys[1:-1] + [L - 0.05]]
        parts.append(orient(strip("pr_led", led2, led, M.led_pink), direction=(-sx, 0, 0)))
        for by in (0.6, 1.8, 3.0, 4.2, 5.4):
            parts.append(hex_bolt("pr_bolt", sx * (hw + 0.004), by, by * sl * 0.5 + 0.05, 0.02, 0.012, axis="X"))
    # kick plate at the bottom edge and a bullnose at the top
    parts.append(prism("pr_kick", [(0.0, 0.0), (0.18, 0.0), (0.18, 0.18 * sl + 0.012), (0.0, 0.006)], -0.84, 0.84,
                       "X", M.brushed))
    parts.append(prism("pr_kick_y", [(0.0, 0.0), (0.05, 0.0), (0.05, 0.05 * sl + 0.014), (0.0, 0.008)], -0.84,
                       0.84, "X", M.yellow))
    bn = mesh.cylinder("pr_nose", 0.045, 1.9, 12, location=(0, L - 0.04, H + 0.0), axis="X")
    mesh.apply_transform(bn)
    mat.assign(bn, M.brushed)
    parts.append(bn)
    parts.append(box("pr_back", -hw, hw, L - 0.03, L, 0.0, H - 0.02, M.powder))
    o = join(parts, "pad_ramp")
    mesh.subdivide_along(o, "Y", positions=[1.0, 2.0, 3.0, 4.0, 5.0])
    mesh.smooth(o, 35)
    return [o]


BOUNCE_R = 0.9


def build_pad_bouncer():
    cy = BOUNCE_R
    base = lathe("pad_bouncer", [(0.0, 0.0), (0.88, 0.0), (0.9, 0.012), (0.9, 0.05), (0.87, 0.07), (0.62, 0.075),
                                 (0.0, 0.075)], 28, material=M.powder, center=(0, cy, 0), smooth=40)
    mat.assign(base, M.rubber, faces=lambda p: p.center.z < 0.03)
    bolts = [hex_bolt("pb_bolt", cy * 0 + 0.74 * math.cos(a), cy + 0.74 * math.sin(a), 0.076, 0.022, 0.014)
             for a in [TAU * k / 8 + 0.2 for k in range(8)]]
    ring = lathe("pb_seat", [(0.5, 0.07), (0.62, 0.07), (0.62, 0.09), (0.5, 0.09)], 24, material=M.steel,
                 center=(0, cy, 0))
    base = join([base, ring] + bolts, "pad_bouncer")
    mesh.smooth(base, 40)
    # the spring: one big compression coil (the renderer squashes this node along Z)
    zt = 0.42
    pts = helix(0.55, zt - 0.06 - 0.075, 3.2, 18, z0=0.075, cx=0.0, cy=cy, wire=0.026, end_turns=0.6)
    spring = tube("pad_bouncer_spring", pts, 0.026, 6, M.spring_steel, caps=True, smooth=60)
    # top: padded rim, the pull-to-refresh membrane on a steel plate
    rim = lathe("pb_rim", [(0.66, zt - 0.05), (0.84, zt - 0.05), (0.89, zt - 0.02), (0.9, zt + 0.02), (0.87, zt + 0.06),
                           (0.8, zt + 0.07), (0.72, zt + 0.06), (0.68, zt + 0.03), (0.66, zt - 0.05)], 28,
                material=M.pad_foam, center=(0, cy, 0), smooth=60)
    plate = lathe("pb_plate", [(0.0, zt - 0.06), (0.66, zt - 0.06), (0.66, zt - 0.04), (0.0, zt - 0.04)], 24,
                  material=M.powder, center=(0, cy, 0))
    mem = lathe("pb_mem", [(0.0, zt + 0.018), (0.3, zt + 0.02), (0.6, zt + 0.028), (0.69, zt + 0.035)], 32,
                material=M.membrane, center=(0, cy, 0), smooth=80)
    top = join([rim, plate, mem], "pad_bouncer_top")
    mesh.smooth(top, 60)
    return [base, spring, top]


def build_pad_autoplay():
    L = 7.0
    parts = []
    ys = [float(k) for k in range(8)]
    zb = 0.07
    # belt (AutoplayBelt, renderer scrolls V), inset between the skirts
    y0, y1 = 0.46, L - 0.46
    rows = [[V(-0.72, y, zb) for y in [y0] + ys[1:-1] + [y1]], [V(0.72, y, zb) for y in [y0] + ys[1:-1] + [y1]]]
    belt = orient(strip("pa_belt", rows[0], rows[1], M.AutoplayBelt), direction=(0, 0, 1))
    mesh.uv_fit_faces(belt, material="AutoplayBelt")
    parts.append(belt)
    parts.append(box("pa_bed", -0.74, 0.74, y0 - 0.02, y1 + 0.02, 0.0, zb - 0.004, M.powder))
    # skirts: low stainless decks with a black deflector brush on the inner edge
    for sx in (-1, 1):
        x0, x1 = sorted((sx * 0.74, sx * 0.9))
        parts.append(prism("pa_skirt", rrect(x1 - x0, 0.14, (0.0, 0.0, 0.03, 0.03) if sx > 0 else
                                             (0.0, 0.0, 0.03, 0.03), 3, (x0 + x1) / 2, 0.07), 0.0, L, "Y",
                           M.stainless))
        xi = sx * 0.735
        br = [V(xi, y, zb + 0.03) for y in ys]
        br2 = [V(xi - sx * 0.025, y, zb + 0.005) for y in ys]
        parts.append(orient(strip("pa_brush", br2, br, M.brush), direction=(-sx, 0, 0.4)))
        parts.append(orient(strip("pa_yellow", [V(sx * 0.9, y, 0.141) for y in ys],
                                  [V(sx * 0.87, y, 0.141) for y in ys], M.yellow), direction=(0, 0, 1)))
    # landing plates + comb plates at both ends (teeth mesh into the belt grooves)
    for end in (0, 1):
        ya, yb = (0.0, y0 - 0.12) if end == 0 else (y1 + 0.12, L)
        lz0, lz1 = (0.012, zb + 0.01) if end == 0 else (zb + 0.01, 0.012)
        parts.append(prism("pa_landing", [(ya, 0.0), (yb, 0.0), (yb, lz1), (ya, lz0)], -0.74, 0.74, "X", M.landing))
        yc = y0 - 0.12 if end == 0 else y1 + 0.12
        sg = 1 if end == 0 else -1
        teeth = []
        n = 24
        for k in range(n + 1):
            x = -0.72 + 1.44 * k / n
            teeth.append((x, yc))
            if k < n:
                teeth.append((x + 0.72 / n, yc + sg * 0.1))
        outline = [(-0.72, yc - sg * 0.02)] + teeth + [(0.72, yc - sg * 0.02)]
        parts.append(prism("pa_comb", outline, zb - 0.01, zb + 0.012, "Z", M.comb))
    o = join(parts, "pad_autoplay")
    mesh.subdivide_along(o, "Y", positions=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    mesh.smooth(o, 35)
    return [o]


# ============================================================== pickups

def build_pickup_like():
    ol = heart_outline(0.8, 0.72, 20)
    prof = [(-0.12, 0.3), (-0.105, 0.7), (-0.07, 0.92), (0.0, 1.0), (0.07, 0.92), (0.105, 0.7), (0.12, 0.3)]
    rings = [[V(u * k, d, v * k) for u, v in ol] for d, k in prof]
    o = loft("pickup_like", rings, M.candy_red, closed=True, cap0=True, cap1=True, smooth=None)
    mesh.smooth(o, None)
    return [o]


def glyph_one(h=0.42):
    k = h / 0.42
    return [(0.045 * k, -0.2 * k), (0.045 * k, 0.21 * k), (-0.02 * k, 0.21 * k), (-0.11 * k, 0.13 * k),
            (-0.085 * k, 0.09 * k), (-0.045 * k, 0.12 * k), (-0.045 * k, -0.2 * k)]


def build_pickup_notif():
    disc = lathe("pickup_notif", [(0.0, -0.075), (0.29, -0.075), (0.34, -0.065), (0.36, -0.035), (0.36, 0.035),
                                  (0.34, 0.065), (0.29, 0.075), (0.0, 0.075)], 20, axis="Y", material=M.badge_red,
                 smooth=50)
    ones = []
    for sy in (-1, 1):
        g = [(u * (-sy), v) for u, v in glyph_one()]
        d0, d1 = sorted((sy * 0.074, sy * 0.1))
        ones.append(prism("pn_one", g, d0, d1, "Y", M.white_gloss))
    o = join([disc] + ones, "pickup_notif")
    mesh.smooth(o, 40)
    return [o]


def build_pickup_reel():
    tile = prism("pickup_reel", rrect(0.68, 0.68, 0.17, 3), -0.07, 0.07, "Y", M.reel_grad, bevel=0.035, bseg=1,
                 angle=20)
    tris = []
    for sy in (-1, 1):
        tri = [(-0.09 * -sy, -0.15), (0.17 * -sy, 0.0), (-0.09 * -sy, 0.15)]
        d0, d1 = sorted((sy * 0.069, sy * 0.095))
        tris.append(prism("prl_play", tri, d0, d1, "Y", M.white_gloss))
    o = join([tile] + tris, "pickup_reel")
    mesh.smooth(o, 40)
    return [o]


def build_pickup_outrage():
    bm = new_bm()
    bmesh.ops.create_uvsphere(bm, u_segments=14, v_segments=8, radius=0.4)
    for v in bm.verts:
        v.co = V(v.co.x, v.co.z * 0.62, v.co.y)  # flattened toward -Y/+Y faces, poles on the sides
        v.co = V(v.co.x, v.co.y, v.co.z)
    face = finish("pickup_outrage", bm, M.emoji)
    # rotate so the poles sit left/right (clean faces front and back)
    brows = []
    for sy in (-1, 1):
        for sx in (-1, 1):
            b = [(sx * 0.05, 0.12), (sx * 0.23, 0.2), (sx * 0.25, 0.15), (sx * 0.07, 0.07)]
            yy = sy * 0.215
            d0, d1 = sorted((yy, yy + sy * 0.05))
            brows.append(prism("po_brow", b, d0, d1, "Y", M.emoji_dark))
    o = join([face] + brows, "pickup_outrage")
    mesh.smooth(o, 50)
    return [o]


# ============================================================== power-ups

def build_power_protector():
    w, h, r = 0.56, 1.0, 0.09
    ol = rrect(w, h, r, 5)
    # notch cut into the top edge
    top = [(x, y) for x, y in ol if y > h / 2 - 1e-6]
    notch = [(0.11, h / 2), (0.1, h / 2 - 0.035), (0.08, h / 2 - 0.045), (-0.08, h / 2 - 0.045), (-0.1, h / 2 - 0.035),
             (-0.11, h / 2)]
    out = []
    for i, p in enumerate(ol):
        out.append(p)
        q = ol[(i + 1) % len(ol)]
        if p[1] > h / 2 - 1e-6 and q[1] > h / 2 - 1e-6 and p[0] > 0 > q[0]:
            out += notch
    # the bottom-right corner is broken off along a jagged line
    brk = [(w / 2, -h / 2 + 0.22), (w / 2 - 0.05, -h / 2 + 0.18), (w / 2 - 0.035, -h / 2 + 0.13),
           (w / 2 - 0.1, -h / 2 + 0.09), (w / 2 - 0.12, -h / 2 + 0.03), (w / 2 - 0.19, -h / 2)]
    out2 = []
    skipping = False
    for p in out:
        if p[0] > w / 2 - 0.19 and p[1] < -h / 2 + 0.22 and not (abs(p[0] - w / 2) < 1e-6 and p[1] > -h / 2 + 0.22):
            if not skipping:
                out2 += brk[::-1] if False else []
                skipping = True
            continue
        out2.append(p)
    # re-insert the break points in order (walking CCW: bottom edge -> right edge)
    idx = next(i for i, p in enumerate(out2) if abs(p[0] - w / 2) < 1e-6 and p[1] > -h / 2 + 0.22)
    out2 = out2[:idx] + brk[::-1] + out2[idx:]
    pane = prism("power_protector", out2, -0.014, 0.014, "Y", M.Glass, bevel=0.009, bseg=2, angle=20)
    mat.assign(pane, M.glass_edge, faces=lambda p: abs(p.normal.y) < 0.97)
    uv_box_fit(pane, "Glass", 0.6)
    # cracks radiating from the break, on both faces
    rng = np.random.default_rng(3)
    cracks = []
    origin = (w / 2 - 0.09, -h / 2 + 0.12)
    for k in range(7):
        a = math.radians(95 + k * 22 + rng.uniform(-8, 8))
        pts = [origin]
        ln = rng.uniform(0.18, 0.42)
        for j in range(1, 4):
            a += rng.uniform(-0.35, 0.35)
            px, pz = pts[-1]
            pts.append((px + math.cos(a) * ln / 3, pz + math.sin(a) * ln / 3))
        for sy in (-1, 1):
            yy = sy * 0.0145
            ra, rb = [], []
            for j, (px, pz) in enumerate(pts):
                wd = 0.006 * (1 - j / 4)
                ra.append(V(px - wd * 0.7, yy, pz + wd))
                rb.append(V(px + wd * 0.7, yy, pz - wd))
            cracks.append(orient(strip("pp_crack", ra, rb, M.crack), direction=(0, sy, 0)))
    # the pull-tab sticker ("peel here")
    tab = prism("pp_tab", rrect(0.1, 0.06, 0.012, 2, -w / 2 - 0.035, h / 2 - 0.18), -0.004, 0.004, "Y", M.tab)
    o = join([pane, tab] + cracks, "power_protector")
    mesh.smooth(o, 30)
    return [o]


def build_power_magnet():
    ro, ri, top, cz = 0.42, 0.17, 0.4, -0.06
    n = 14
    ol = [(ro, top)]
    for k in range(n + 1):
        a = -math.pi * k / n  # right -> bottom -> left along the outside
        ol.append((ro * math.cos(a), cz + ro * math.sin(a)))
    ol += [(-ro, top), (-ri, top)]
    for k in range(n + 1):
        a = -math.pi + math.pi * k / n
        ol.append((ri * math.cos(a), cz + ri * math.sin(a)))
    ol += [(ri, top)]
    body = prism("power_magnet", ol, -0.1, 0.1, "Y", M.magnet_red, bevel=0.025, bseg=2, angle=25,
                 cuts=None)
    mesh.apply_transform(body)
    # pole tips: bisect at z 0.25, silver above
    bm = bmesh.new()
    bm.from_mesh(body.data)
    bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=(0, 0, 0.25),
                           plane_no=(0, 0, 1))
    bm.to_mesh(body.data)
    bm.free()
    mat.assign(body, M.pole_silver, faces=lambda p: p.center.z > 0.25)
    hearts = []
    for sy in (-1, 1):
        hol = [(u, v + cz - 0.29) for u, v in heart_outline(0.2, 0.18, 20)]
        d0, d1 = sorted((sy * 0.099, sy * 0.125))
        hearts.append(prism("pm_heart", hol, d0, d1, "Y", M.magnet_heart, bevel=0.008, bseg=1, angle=20))
    o = join([body] + hearts, "power_magnet")
    xform(o, loc=(0, 0, -0.02))
    mesh.smooth(o, 35)
    return [o]


def build_power_viral():
    parts = []
    for sx in (-1, 1):
        cx = sx * 0.17
        prof = [(0.0, -0.36), (0.07, -0.36), (0.1, -0.44), (0.105, -0.44), (0.075, -0.3), (0.13, -0.29),
                (0.13, 0.18), (0.12, 0.24), (0.08, 0.36), (0.03, 0.43), (0.0, 0.44)]
        can = lathe(f"pv_can{sx}", prof, 16, material=M.rocket, center=(cx, 0, 0), smooth=40)
        mat.assign(can, M.nozzle, faces=lambda p: p.center.z < -0.29)
        parts.append(can)
        glow = lathe(f"pv_glow{sx}", [(0.0, -0.37), (0.085, -0.43)], 12, material=M.flame, center=(cx, 0, 0))
        parts.append(glow)
        for k in range(3):
            a = math.radians(90 * sx) + TAU * k / 3
            fin = prism("pv_fin", [(0.0, -0.3), (0.13, -0.36), (0.12, -0.2), (0.0, -0.08)], -0.008, 0.008, "Y", M.fin)
            xform(fin, loc=(0.12, 0, 0))
            xform(fin, rot=(0, 0, a))
            xform(fin, loc=(cx, 0, 0))
            parts.append(fin)
    # the view counter: a small display bolted between the cans
    parts.append(box("pv_disp", -0.07, 0.07, -0.075, 0.075, -0.02, 0.1, M.powder, bevel=0.01, seg=1))
    for sy in (-1, 1):
        q = quad("pv_screen", [V(-0.055, sy * 0.0765, 0.0), V(0.055, sy * 0.0765, 0.0), V(0.055, sy * 0.0765, 0.08),
                               V(-0.055, sy * 0.0765, 0.08)], M.counter)
        orient(q, direction=(0, sy, 0))
        mesh.uv_fit_faces(q)
        parts.append(q)
    for z in (-0.18, 0.12):
        parts.append(box("pv_strap", -0.2, 0.2, -0.02, 0.02, z - 0.02, z + 0.02, M.strap))
    o = join(parts, "power_viral")
    mesh.smooth(o, 40)
    return [o]


def stroke_outline(pts, t):
    """Polygon around a 2D polyline of width t (miter joins, square ends)."""
    P = [Vector(p) for p in pts]
    n = len(P)
    left, right = [], []
    for i in range(n):
        if i == 0:
            d = (P[1] - P[0]).normalized()
            nn = Vector((-d.y, d.x))
            m = 1.0
        elif i == n - 1:
            d = (P[-1] - P[-2]).normalized()
            nn = Vector((-d.y, d.x))
            m = 1.0
        else:
            d0 = (P[i] - P[i - 1]).normalized()
            d1 = (P[i + 1] - P[i]).normalized()
            n0, n1 = Vector((-d0.y, d0.x)), Vector((-d1.y, d1.x))
            nn = (n0 + n1).normalized()
            m = 1.0 / max(nn.dot(n0), 0.35)
        left.append(tuple(P[i] + nn * t / 2 * m))
        right.append(tuple(P[i] - nn * t / 2 * m))
    return left + right[::-1]


def glyph_strokes():
    """'x2' as strokes (x: two bars; 2: bowl + diagonal, base bar)."""
    xs = [[(-0.14, -0.06), (-0.04, 0.05)], [(-0.14, 0.05), (-0.04, -0.06)]]
    bowl = [(0.03 + 0.05 * math.cos(math.radians(a)), 0.035 + 0.05 * math.sin(math.radians(a)))
            for a in (165, 120, 80, 40, 5, -30)]
    two = [bowl + [(0.025, -0.07)], [(0.01, -0.075), (0.13, -0.075)]]
    return xs + two


def glyph_x(s=0.18, t=0.05):
    a = t / math.sqrt(2)
    h = s / 2
    return [(0.0, a * 1.0), (h - a, h), (h, h - a), (a * 1.0, 0.0), (h, -h + a), (h - a, -h), (0.0, -a * 1.0),
            (-h + a, -h), (-h, -h + a), (-a * 1.0, 0.0), (-h, h - a), (-h + a, h)]


def glyph_two(s=0.24, t=0.055):
    """A '2' as one outline: bowl arc, diagonal, base bar."""
    r = s * 0.3
    cx, cy = 0.0, s / 2 - r
    outer, inner = [], []
    for k in range(9):
        a = math.radians(160 - 200 * k / 8)
        outer.append((cx + (r + t / 2) * math.cos(a), cy + (r + t / 2) * math.sin(a)))
        inner.append((cx + (r - t / 2) * math.cos(a), cy + (r - t / 2) * math.sin(a)))
    base_y = -s / 2
    pts = outer + [(-s * 0.3 + t * 0.9, base_y + t), (s * 0.36, base_y + t), (s * 0.36, base_y), (-s * 0.36, base_y),
                   (-s * 0.36, base_y + t * 0.6)] + inner[::-1][:-1] + [inner[0]]
    return pts


def build_power_mainchar():
    parts = []
    prof = [(0.33, 0.03), (0.33, -0.03), (0.35, -0.05), (0.45, -0.05), (0.47, -0.03), (0.47, 0.03), (0.45, 0.05),
            (0.35, 0.05), (0.33, 0.03)]
    ring = lathe("power_mainchar", prof, 40, axis="Y", material=M.gold, smooth=50)
    mat.assign(ring, M.ring_led, faces=lambda p: abs(p.normal.y) > 0.9 and 0.345 < math.hypot(p.center.x, p.center.z) < 0.455)
    parts.append(ring)
    # a phone held in the ring light's clamp, its screen reading "x2" (both faces)
    parts.append(prism("pmc_phone", rrect(0.4, 0.26, 0.05, 4), -0.018, 0.018, "Y", M.black_glass, bevel=0.008,
                       bseg=1))
    for sy in (-1, 1):
        d0, d1 = sorted((sy * 0.0185, sy * 0.03))
        for k, strk in enumerate(glyph_strokes()):
            ol = [(u * -sy, v) for u, v in stroke_outline(strk, 0.042)]
            parts.append(prism(f"pmc_g{k}", ol, d0, d1, "Y", M.gold_glyph))
    for sx in (-1, 1):  # the clamp arms
        parts.append(tube("pmc_spoke", [V(sx * 0.2, 0, 0.0), V(sx * 0.34, 0, 0.0)], 0.014, 6, M.powder))
        parts.append(box("pmc_jaw", sx * 0.2 - 0.02, sx * 0.2 + 0.02, -0.03, 0.03, -0.06, 0.06, M.powder))
    # ball-head mount under the ring
    parts.append(lathe("pmc_mount", [(0.0, -0.47), (0.04, -0.47), (0.04, -0.52), (0.055, -0.55), (0.055, -0.57),
                                     (0.0, -0.58)], 12, material=M.powder))
    o = join(parts, "power_mainchar")
    xform(o, loc=(0, 0, 0.05))
    mesh.smooth(o, 40)
    return [o]


def build_power_kicks():
    mats = dict(upper=M.neon_upper, sole=M.cloud_sole, lace=M.neon_lace)
    a = shoe("pk_a", 0.82, mats, n_sec=16, n_ring=13, n_out=28, stack=(0.32, 0.26), cloud=0.06, lace_n=4, bow=False)
    b = shoe("pk_b", 0.82, mats, n_sec=16, n_ring=13, n_out=28, stack=(0.32, 0.26), cloud=0.06, lace_n=4, bow=False)
    b.data.transform(Matrix.Diagonal((1, -1, 1, 1)))
    b.data.flip_normals()
    xform(a, loc=(0.03, -0.14, 0), rot=(0, 0, 0.12))
    xform(b, loc=(-0.03, 0.15, 0), rot=(0, 0, -0.05))
    o = join([a, b], "power_kicks")
    lo, hi = mesh.bounds(o)
    xform(o, loc=(-(lo.x + hi.x) / 2, -(lo.y + hi.y) / 2, -(lo.z + hi.z) / 2))
    return [o]


def build_att_jetpack():
    parts = []
    plate = prism("aj_plate", rrect(0.36, 0.46, 0.06, 3, 0.0, -0.03), -0.07, -0.02, "Y", M.strap_black, bevel=0.012,
                  bseg=1)
    parts.append(plate)
    for sx in (-1, 1):
        cx = sx * 0.125
        prof = [(0.0, -0.31), (0.055, -0.31), (0.075, -0.41), (0.08, -0.41), (0.065, -0.28), (0.1, -0.27),
                (0.1, 0.16), (0.09, 0.22), (0.06, 0.27), (0.0, 0.29)]
        can = lathe(f"aj_can{sx}", prof, 16, material=M.rocket, center=(cx, -0.18, 0), smooth=40)
        mat.assign(can, M.nozzle, faces=lambda p: p.center.z < -0.27)
        parts.append(can)
        parts.append(lathe(f"aj_glow{sx}", [(0.0, -0.32), (0.07, -0.4)], 12, material=M.flame, center=(cx, -0.18, 0)))
        for z in (-0.16, 0.08):  # clamp bands
            parts.append(lathe("aj_band", [(0.103, z - 0.02), (0.103, z + 0.02)], 16, material=M.powder,
                               center=(cx, -0.18, 0)))
        # shoulder strap: up the back, over the shoulder, down the chest a little
        strap = [V(sx * 0.1, -0.03, 0.14), V(sx * 0.11, -0.02, 0.28), V(sx * 0.12, 0.05, 0.36), V(sx * 0.13, 0.14, 0.33),
                 V(sx * 0.13, 0.2, 0.2), V(sx * 0.13, 0.21, 0.06)]
        parts.append(tube("aj_strap", strap, 0.03, 4, M.strap_black, section=[(1, 0.2), (-1, 0.2), (-1, -0.2), (1, -0.2)],
                          up=(1, 0, 0)))
        belt = [V(sx * 0.17, -0.04, -0.2), V(sx * 0.21, 0.02, -0.21), V(sx * 0.22, 0.1, -0.22)]
        parts.append(tube("aj_belt", belt, 0.028, 4, M.strap_black, section=[(1, 0.2), (-1, 0.2), (-1, -0.2), (1, -0.2)],
                          up=(0, 0, 1)))
        parts.append(box("aj_buckle", sx * 0.13 - 0.025, sx * 0.13 + 0.025, 0.2, 0.225, 0.12, 0.17, M.chrome))
    # fuel gauge + the view counter on top, a carry handle
    parts.append(lathe("aj_gauge", [(0.045, -0.07), (0.045, -0.09), (0.04, -0.095), (0.0, -0.095)], 12, axis="Y",
                       center=(0.0, 0, 0.12), material=M.gauge))
    parts.append(box("aj_disp", -0.06, 0.06, -0.26, -0.1, 0.2, 0.27, M.powder, bevel=0.008, seg=1))
    q = quad("aj_screen", [V(-0.05, -0.2605, 0.21), V(0.05, -0.2605, 0.21), V(0.05, -0.2605, 0.26),
                           V(-0.05, -0.2605, 0.26)], M.counter)
    orient(q, direction=(0, -1, 0))
    mesh.uv_fit_faces(q)
    parts.append(q)
    parts.append(tube("aj_handle", [V(-0.07, -0.06, 0.2), V(-0.06, -0.08, 0.3), V(0.06, -0.08, 0.3), V(0.07, -0.06, 0.2)],
                      0.014, 6, M.chrome))
    o = join(parts, "att_jetpack")
    mesh.smooth(o, 40)
    return [o]


# ============================================================== rails

RAIL_TOP, RAIL_R = 1.1, 0.1
RAIL_Z = RAIL_TOP - RAIL_R


def build_rail_cable():
    cable = tube("rail_cable", [V(0, 0.0, RAIL_Z), V(0, 1.0, RAIL_Z)], RAIL_R, 12, M.cable, caps=True, smooth=80,
                 up=(0, 0, 1))
    post = mesh.cylinder("rc_post", 0.028, RAIL_Z - RAIL_R + 0.02, 6, location=(0, 0.5, (RAIL_Z - RAIL_R + 0.02) / 2),
                         caps=False)
    mesh.apply_transform(post)
    mat.assign(post, M.powder)
    clip = tube("rc_clip", [V(0.115 * math.cos(a), 0.5, RAIL_Z + 0.115 * math.sin(a)) for a in
                            [math.pi * (1.0 + k / 4) for k in range(5)]], 0.03, 4, M.clip,
                section=[(1, 0.35), (-1, 0.35), (-1, -0.35), (1, -0.35)], up=(0, 1, 0), smooth=50)
    foot = lathe("rc_foot", [(0.0, 0.0), (0.11, 0.0), (0.11, 0.015), (0.06, 0.03), (0.0, 0.03)], 8, material=M.powder,
                 center=(0, 0.5, 0))
    o = join([cable, post, clip, foot], "rail_cable")
    mesh.smooth(o, 50)
    return [o]


def build_rail_pipe():
    pipe = tube("rail_pipe", [V(0, 0.0, RAIL_Z), V(0, 1.0, RAIL_Z)], RAIL_R, 10, M.pipe, caps=True, smooth=80,
                up=(0, 0, 1))
    fl = lathe("rp_flange", [(RAIL_R, 0.47), (0.15, 0.475), (0.15, 0.525), (RAIL_R, 0.53)],
               10, axis="Y", center=(0, 0, RAIL_Z), material=M.flange)
    post = mesh.cylinder("rp_post", 0.03, RAIL_Z - RAIL_R - 0.01, 5, location=(0, 0.2, (RAIL_Z - RAIL_R) / 2),
                         caps=False)
    mesh.apply_transform(post)
    mat.assign(post, M.galv)
    ub = tube("rp_ubolt", [V(0.11 * math.cos(a), 0.2, RAIL_Z + 0.11 * math.sin(a)) for a in
                           [math.pi * (1.0 + k / 4) for k in range(5)]], 0.014, 3, M.galv, smooth=50, caps=False)
    base = box("rp_base", -0.09, 0.09, 0.11, 0.29, 0.0, 0.018, M.galv)
    o = join([pipe, fl, post, ub, base], "rail_pipe")
    mesh.smooth(o, 50)
    return [o]


def _ramp_axis(y, r=RAIL_R, y0=-1.5):
    """Centreline of a rail ramping from the track (y0) to RAIL_TOP at y 0,
    easing into horizontal over the last 0.45 m."""
    th = math.atan2(RAIL_TOP, -y0)
    lift = r / math.cos(th)
    lin = lambda yy: RAIL_TOP * (yy - y0) / (-y0) - lift  # noqa: E731
    yb = -0.45
    if y <= yb:
        return lin(y)
    # quadratic ease: matches the slope at yb and ends level at RAIL_Z at 0
    z0, s0 = lin(yb), RAIL_TOP / (-y0)
    k = (y - yb) / (-yb)
    p0, p1, p2 = z0, z0 + s0 * (-yb) / 2, RAIL_Z
    zz = (1 - k) ** 2 * p0 + 2 * (1 - k) * k * p1 + k * k * p2
    return zz


def build_rail_end():
    parts = []
    th = math.atan2(RAIL_TOP, 1.5)
    d = V(0, math.cos(th), math.sin(th))
    # USB-C plug: the shell goes into a port in the track, boot + strain relief rise out of it
    y_in = -1.5 + (RAIL_R / math.cos(th)) * 1.5 / RAIL_TOP
    base = V(0, y_in, 0.0)
    up = V(0, -math.sin(th), math.cos(th))

    def along(s, u=0.0, v=0.0):
        return base + d * s + V(1, 0, 0) * u + up * v

    def section(w, h, n=12):
        return [(w / 2 * math.copysign(abs(math.cos(TAU * k / n)) ** 0.5, math.cos(TAU * k / n)),
                 h / 2 * math.copysign(abs(math.sin(TAU * k / n)) ** 0.5, math.sin(TAU * k / n))) for k in range(n)]

    def ring(s, w, h, n=12):
        return [along(s, u, v) for u, v in section(w, h, n)]

    shell = loft("re_shell", [ring(-0.28, 0.4, 0.13, 16), ring(0.02, 0.4, 0.13, 16), ring(0.02, 0.36, 0.095, 16),
                              ring(-0.02, 0.36, 0.095, 16)], M.plug_metal, closed=True, smooth=60)
    tongue = box("re_tongue", -0.14, 0.14, -0.01, 0.01, -0.02, 0.0, M.island)
    parts += [shell]
    boot = loft("re_boot", [ring(0.0, 0.5, 0.2), ring(0.02, 0.54, 0.24), ring(0.4, 0.54, 0.24), ring(0.44, 0.5, 0.22),
                            ring(0.47, 0.3, 0.2), ring(0.62, 0.23, 0.21), ring(0.78, 0.205, 0.205)], M.boot,
                closed=True, cap0=True, smooth=60)
    parts.append(boot)
    # the cable, following the ramp line and easing level into the rail modules
    ys = [y_in + (0.78) * d.y + (0.0 - (y_in + 0.78 * d.y)) * k / 10 for k in range(11)]
    pts = [V(0, y, _ramp_axis(y)) for y in ys]
    parts.append(tube("re_cable", pts, RAIL_R, 12, M.cable, caps=False, smooth=80, up=(1, 0, 0)))
    # the port in the screen: a dark stadium rim around where the plug goes in
    port = frame_ring("re_port", stadium(0.62, 0.34 / math.sin(th) * 0.55, 6, 0.0, y_in - 0.02),
                      stadium(0.44, 0.16 / math.sin(th) * 0.55, 6, 0.0, y_in - 0.02), 0.006, 0.0, "Z", M.port)
    parts.append(port)
    o = join(parts, "rail_end")
    mesh.smooth(o, 50)
    return [o]


def build_rail_pipe_end():
    ys = [-1.25 + 1.25 * k / 8 for k in range(9)]
    pts = [V(0, y, _ramp_axis(y, y0=-1.5)) for y in ys]
    pts[0] = V(0, -1.3, 0.05)
    pipe = tube("rail_pipe_end", pts, RAIL_R, 10, M.pipe, caps=False, smooth=80, up=(1, 0, 0))
    fl = lathe("rpe_flange", [(0.0, 0.0), (0.2, 0.0), (0.2, 0.03), (RAIL_R, 0.05)], 12, center=(0, -1.3, 0),
               material=M.flange)
    bolts = [hex_bolt("rpe_bolt", 0.16 * math.cos(a), -1.3 + 0.16 * math.sin(a), 0.035, 0.016, 0.016)
             for a in [TAU * k / 6 for k in range(6)]]
    o = join([pipe, fl] + bolts, "rail_pipe_end")
    mesh.smooth(o, 50)
    return [o]


# ============================================================== registry

BUILDERS = [
    (("train_front",), build_train_front),
    (("train_mid",), build_train_mid),
    (("train_back",), build_train_back),
    (("train_stairs",), build_train_stairs),
    (("train_warn",), build_train_warn),
    (("barrier_low",), build_barrier_low),
    (("barrier_high",), build_barrier_high),
    (("habit_water",), build_habit_water),
    (("habit_books",), build_habit_books),
    (("habit_shoe",), build_habit_shoe),
    (("habit_phone",), build_habit_phone),
    (("thumb",), build_thumb),
    (("pad_ramp",), build_pad_ramp),
    (("pad_bouncer", "pad_bouncer_spring", "pad_bouncer_top"), build_pad_bouncer),
    (("pad_autoplay",), build_pad_autoplay),
    (("pickup_like",), build_pickup_like),
    (("pickup_notif",), build_pickup_notif),
    (("pickup_reel",), build_pickup_reel),
    (("pickup_outrage",), build_pickup_outrage),
    (("power_protector",), build_power_protector),
    (("power_magnet",), build_power_magnet),
    (("power_viral",), build_power_viral),
    (("power_mainchar",), build_power_mainchar),
    (("power_kicks",), build_power_kicks),
    (("att_jetpack",), build_att_jetpack),
    (("rail_cable",), build_rail_cable),
    (("rail_pipe",), build_rail_pipe),
    (("rail_end",), build_rail_end),
    (("rail_pipe_end",), build_rail_pipe_end),
]


# ============================================================== preview canvases

PALETTE = ["#ff2e88", "#00e1ff", "#ffb300", "#7dff5a", "#b36bff", "#ff5a3c"]


def _hex(c):
    c = c.lstrip("#")
    return np.array([int(c[i:i + 2], 16) / 255 for i in (0, 2, 4)], np.float32)


class Canvas:
    """Tiny numpy painter (y down, like a 2D canvas), for preview placeholders."""

    def __init__(self, w, h, bg="#000000"):
        self.w, self.h = w, h
        self.a = np.zeros((h, w, 3), np.float32)
        self.a[:] = _hex(bg)
        self.Y, self.X = np.mgrid[0:h, 0:w].astype(np.float32) + 0.5

    def fill(self, sdf, color):
        cov = np.clip(0.5 - sdf, 0.0, 1.0)[..., None]
        col = _hex(color) if isinstance(color, str) else np.asarray(color, np.float32)
        self.a = self.a * (1 - cov) + col * cov

    def rrect(self, x, y, w, h, r, color):
        cx, cy = x + w / 2, y + h / 2
        qx = np.abs(self.X - cx) - w / 2 + r
        qy = np.abs(self.Y - cy) - h / 2 + r
        d = np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - r
        self.fill(d, color)

    def circle(self, cx, cy, r, color):
        self.fill(np.hypot(self.X - cx, self.Y - cy) - r, color)

    def tri(self, pts, color):
        d = np.full(self.X.shape, -1e9, np.float32)
        for i in range(3):
            (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % 3]
            nx, ny = y1 - y0, -(x1 - x0)
            ln = math.hypot(nx, ny)
            d = np.maximum(d, ((self.X - x0) * nx + (self.Y - y0) * ny) / ln)
        d2 = np.full(self.X.shape, -1e9, np.float32)
        for i in range(3):
            (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % 3]
            nx, ny = y1 - y0, -(x1 - x0)
            d2 = np.maximum(d2, -((self.X - x0) * nx + (self.Y - y0) * ny) / math.hypot(nx, ny))
        self.fill(np.minimum(d, d2), color)

    def chevron(self, cx, cy, w, h, t, color):
        # two thick strokes meeting at the top
        for sx in (-1, 1):
            x0, y0, x1, y1 = cx + sx * w / 2, cy + h / 2, cx, cy - h / 2
            px, py = self.X - x0, self.Y - y0
            bx, by = x1 - x0, y1 - y0
            k = np.clip((px * bx + py * by) / (bx * bx + by * by), 0, 1)
            self.fill(np.hypot(px - bx * k, py - by * k) - t / 2, color)

    def gradient(self, x, y, w, h, r, c0, c1):
        k = np.clip(((self.X - x) / w + (self.Y - y) / h) / 2, 0, 1)[..., None]
        col = _hex(c0) * (1 - k) + _hex(c1) * k
        cx, cy = x + w / 2, y + h / 2
        qx = np.abs(self.X - cx) - w / 2 + r
        qy = np.abs(self.Y - cy) - h / 2 + r
        d = np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - r
        cov = np.clip(0.5 - d, 0, 1)[..., None]
        self.a = self.a * (1 - cov) + col * cov

    def image(self, name):
        img = bpy.data.images.new(name, self.w, self.h, alpha=True)
        px = np.ones((self.h, self.w, 4), np.float32)
        lin = np.where(self.a <= 0.04045, self.a / 12.92, ((self.a + 0.055) / 1.055) ** 2.4)
        px[..., :3] = lin[::-1]
        img.colorspace_settings.name = "Linear Rec.709"
        img.pixels.foreach_set(px.ravel())
        img.update()
        return img


def placeholder_images():
    out = {}
    c = Canvas(512, 256, "#0d0b14")
    c.gradient(8, 8, 496, 240, 18, PALETTE[1], PALETTE[4])
    c.rrect(8, 206, 496, 42, 0, (0.03, 0.03, 0.05))
    c.rrect(8, 242, 230, 6, 0, "#ffffff")
    c.rrect(26, 34, 300, 36, 8, "#ffffff")
    c.rrect(26, 214, 150, 18, 6, "#ffffff")
    out["ReelScreen"] = c.image("_ph_reel")
    c = Canvas(256, 256, "#0d0b14")
    c.rrect(10, 10, 236, 236, 26, PALETTE[1])
    c.tri([(98, 78), (178, 128), (98, 178)], "#ffffff")
    out["ReelFront"] = c.image("_ph_reelfront")
    c = Canvas(512, 128, "#101014")
    c.rrect(0, 0, 512, 128, 40, "#f4f2fa")
    c.rrect(22, 24, 80, 80, 20, PALETTE[0])
    c.rrect(124, 34, 250, 30, 8, "#16131f")
    c.rrect(124, 78, 180, 22, 8, "#6b6680")
    c.circle(470, 64, 26, "#ff2e3b")
    c.rrect(465, 50, 10, 28, 3, "#ffffff")
    out["NotifFace"] = c.image("_ph_notif")
    c = Canvas(512, 256, "#ffd23c")
    c.rrect(56, 80, 400, 70, 12, "#16131f")
    c.rrect(116, 166, 280, 26, 8, "#16131f")
    c.rrect(14, 14, 58, 30, 6, (0.1, 0.08, 0.02))
    c.rrect(368, 206, 130, 36, 8, (0.1, 0.08, 0.02))
    out["AdFace"] = c.image("_ph_ad")
    c = Canvas(256, 512, "#2c4439")
    c.circle(128, 150, 54, "#d8d2c4")
    c.rrect(70, 226, 116, 36, 8, "#f2efe6")
    c.rrect(84, 276, 88, 18, 6, "#f2efe6")
    c.circle(66, 426, 34, "#e0473b")
    c.circle(190, 426, 34, "#35b86b")
    out["MumFace"] = c.image("_ph_mum")
    c = Canvas(256, 512, "#1c0b2c")
    for i in range(4):
        c.chevron(128, 150 + i * 90, 140, 64, 16, (1.0 - i * 0.2, 0.18 * (1 - i * 0.2), 0.53 * (1 - i * 0.2)))
    c.rrect(40, 42, 176, 34, 8, "#f4f2fa")
    out["RampFace"] = c.image("_ph_ramp")
    c = Canvas(128, 256, "#000000")
    for i in range(2):
        c.chevron(64, 70 + i * 128, 84, 50, 14, "#ffffff")
    out["AutoplayBelt"] = c.image("_ph_autoplay")
    return out


class Placeholders:
    """Link placeholder canvases into the runtime materials' emission (previews only)."""

    def __enter__(self):
        self.added = []
        imgs = placeholder_images()
        for name, img in imgs.items():
            m = bpy.data.materials.get(name)
            if m is None:
                continue
            nt = m.node_tree
            p = mat.principled(m)
            tn = nt.nodes.new("ShaderNodeTexImage")
            tn.image = img
            uv = nt.nodes.new("ShaderNodeUVMap")
            nt.links.new(uv.outputs[0], tn.inputs["Vector"])
            prev = p.inputs["Emission Color"].default_value[:]
            nt.links.new(tn.outputs["Color"], p.inputs["Emission Color"])
            self.added.append((m, [tn, uv], prev))
        self.imgs = imgs
        return self

    def __exit__(self, *exc):
        for m, nodes, prev in self.added:
            for n in nodes:
                m.node_tree.nodes.remove(n)
            mat.principled(m).inputs["Emission Color"].default_value = prev
        for img in self.imgs.values():
            bpy.data.images.remove(img)
        return False


# ============================================================== game view

def game_view(out_dir, nodes, name="game", runner_y=(0.0, 20.0)):
    """Chase-camera render: pieces laid on a dark three-lane track, fog."""
    by = {o.name: o for o in nodes}
    added = []

    def place(n, x, y, z=0.0, rz=0.0):
        if n not in by:
            return
        c = by[n].copy()
        c.data = by[n].data
        c.location = (x, y, z)
        c.rotation_euler = (0, 0, rz)
        c.hide_render = False
        bpy.context.scene.collection.objects.link(c)
        added.append(c)

    layout = [("pickup_like", 0, 5.0, 1.0), ("pickup_notif", 0, 6.4, 1.0), ("pickup_reel", 0, 7.8, 1.0),
              ("pickup_outrage", 0, 9.2, 1.0), ("barrier_low", -2.2, 10), ("barrier_high", 2.2, 12),
              ("habit_water", 0, 13), ("habit_books", -2.2, 17), ("habit_shoe", 2.2, 18), ("habit_phone", 0, 20),
              ("power_magnet", 2.2, 7, 1.0), ("power_mainchar", -2.2, 22, 1.0), ("power_viral", 2.2, 23, 1.0),
              ("pad_ramp", -2.2, 26), ("pad_autoplay", 2.2, 27), ("rail_end", 2.2, 41.5)]
    for spec in layout:
        place(spec[0], spec[1], spec[2], spec[3] if len(spec) > 3 else 0.0)
    for k in range(14):
        place("rail_cable", 2.2, 41.5 + k)
    for n in ("pad_bouncer", "pad_bouncer_spring", "pad_bouncer_top"):
        place(n, 0, 24)
    # a static train with stairs in the middle lane, a moving one on the left, the Thumb on the right
    y = 34.0
    place("train_stairs", 0, y)
    place("train_front", 0, y)
    for k in range(6):
        place("train_mid", 0, y + 1 + 2 * k)
    place("train_back", 0, y + 13)
    y = 31.0
    place("train_front", -2.2, y)
    place("train_warn", -2.2, y)
    for k in range(5):
        place("train_mid", -2.2, y + 1 + 2 * k)
    place("train_back", -2.2, y + 11)
    place("thumb", 2.2, 58)
    # track: lane screens and bezels
    deck = mesh.box("_g_deck", (9.6, 220, 0.4), (0, 100, -0.2))
    deck.data.materials.append(mat.flat("_g_deck", "#0b0b10", rough=0.35, metal=0.4))
    added.append(deck)
    scr_mats = [mat.flat(f"_g_scr{i}", "#04050a", rough=0.28, emission=c, strength=0.04)
                for i, c in enumerate(["#3b4a7a", "#5a3a6e", "#2e5a66", "#6a4a3a", "#404a58"])]
    for li, lx in enumerate((-2.2, 0.0, 2.2)):
        for k in range(50):
            s = mesh.box("_g_scr", (1.92, 4.06, 0.01), (lx, k * 4.4 - 2.2, 0.006))
            s.data.materials.append(scr_mats[(k * 3 + li) % 5])
            added.append(s)
    sc = bpy.context.scene
    saved_world, saved_cam, saved_engine = sc.world, sc.camera, sc.render.engine
    w = bpy.data.worlds.new("_g_world")
    wn = w.node_tree
    bg = wn.nodes.get("Background") or wn.nodes.new("ShaderNodeBackground")
    bg.inputs["Color"].default_value = (0.02, 0.018, 0.035, 1)
    bg.inputs["Strength"].default_value = 1.0
    vol = wn.nodes.new("ShaderNodeVolumePrincipled")
    vol.inputs["Density"].default_value = 0.0025
    vol.inputs["Color"].default_value = (0.25, 0.22, 0.35, 1)
    wout = next(n for n in wn.nodes if n.type == "OUTPUT_WORLD")
    wn.links.new(bg.outputs[0], wout.inputs["Surface"])
    wn.links.new(vol.outputs[0], wout.inputs["Volume"])
    sc.world = w
    cam_d = bpy.data.cameras.new("_g_cam")
    cam_d.lens = 26
    cam_d.clip_end = 400
    cam = bpy.data.objects.new("_g_cam", cam_d)
    sc.collection.objects.link(cam)
    cam.location = (0, -6.4, 3.5)
    cam.rotation_euler = (math.radians(74), 0, 0)
    sc.camera = cam
    lights = []
    for i, (lx, ly, lz, e, col, rot) in enumerate(((0, -3, 5, 1500, (0.75, 0.85, 1.0), (math.radians(70), 0, 0)),
                                                  (-9, 25, 14, 9000, (1, 0.45, 0.75), (0, math.radians(-35), 0)),
                                                  (9, 40, 14, 9000, (0.45, 0.75, 1), (0, math.radians(35), 0)))):
        ld = bpy.data.lights.new(f"_g_l{i}", "AREA")
        ld.energy = e
        ld.size = 10
        ld.color = col
        lo = bpy.data.objects.new(f"_g_l{i}", ld)
        lo.location = (lx, ly, lz)
        lo.rotation_euler = rot
        sc.collection.objects.link(lo)
        lights.append(lo)
    sc.render.engine = "BLENDER_EEVEE"
    sc.eevee.taa_render_samples = 32
    sc.render.resolution_x, sc.render.resolution_y = 720, 1280
    sc.view_settings.view_transform = "AgX"
    hidden = {o: o.hide_render for o in sc.objects}
    for o in nodes:
        o.hide_render = True
    os.makedirs(out_dir, exist_ok=True)
    for i, ry in enumerate(runner_y):
        cam.location = (0, ry - 6.4, 3.5)
        for lo, (ly0) in zip(lights, (-3, 25, 40)):
            lo.location.y = ly0 + ry
        sc.render.filepath = os.path.join(out_dir, f"{name}{'' if i == 0 else i + 1}.png")
        bpy.ops.render.render(write_still=True)
    for o, h in hidden.items():
        if o.name in bpy.data.objects:
            o.hide_render = h
    for o in added + lights + [cam]:
        bpy.data.objects.remove(o, do_unlink=True)
    sc.world, sc.camera, sc.render.engine = saved_world, saved_cam, saved_engine
    bpy.data.worlds.remove(w)
    log("preview: game view", sc.render.filepath)


# ============================================================== main

# atlas texel density per node (small hero pieces seen up close get more)
WEIGHTS = {"thumb": 1.6, "train_mid": 1.4, "train_front": 1.4, "train_back": 0.8, "train_stairs": 0.7,
           "barrier_low": 1.6, "barrier_high": 1.3, "habit_water": 2.0, "habit_books": 2.5, "habit_shoe": 3.0,
           "habit_phone": 3.0, "pad_ramp": 0.8, "pad_autoplay": 0.8, "pad_bouncer": 1.5, "pad_bouncer_top": 2.0,
           "pad_bouncer_spring": 1.0, "pickup_like": 5.0, "pickup_notif": 5.0, "pickup_reel": 5.0,
           "pickup_outrage": 5.0, "power_protector": 4.0, "power_magnet": 4.0, "power_viral": 4.0,
           "power_mainchar": 4.0, "power_kicks": 4.0, "att_jetpack": 4.0, "rail_cable": 3.0, "rail_pipe": 3.0,
           "rail_end": 2.5, "rail_pipe_end": 2.0, "train_warn": 2.0}


def main():
    nodes = []
    for names, fn in BUILDERS:
        if ONLY and not any(n in ONLY for n in names):
            continue
        made = fn()
        for o in made:
            mesh.apply_transform(o)
        nodes += made
    for o in nodes:
        for k in list(o.keys()):
            if k.startswith("_"):
                del o[k]
    def bb(o):
        lo, hi = mesh.bounds(o)
        return "x %+.2f..%+.2f y %+.2f..%+.2f z %+.2f..%+.2f" % (lo.x, hi.x, lo.y, hi.y, lo.z, hi.z)
    rows = [(o.name, mesh.tri_count(o), round(mesh.max_segment(o), 3), [m.name for m in o.data.materials], bb(o))
            for o in nodes]
    if PREVIEW and NO_BAKE:
        with Placeholders():
            preview.render_each(PREVIEW, nodes, views=VIEWS, size=(640, 640), sheet=True)
            if GAME:
                game_view(PREVIEW, nodes)
    if not NO_BAKE:
        for o in nodes:
            o["atlas_weight"] = WEIGHTS.get(o.name, 1.0)
        res = bake.bake_kit_atlas(nodes, SIZE, TEX_DIR, name="CommonKit", keep_materials=RUNTIME, ao_samples=48,
                                  samples=12, unwrap="smart", ao_distance=0.35)
        log("atlas", res["paths"], "emissive strength", round(res["emissive_strength"], 2))
        for o in nodes:  # build-time data the glb doesn't need
            for k in [k for k in o.keys() if k in ("atlas_weight",) or k.startswith("_")]:
                del o[k]
            for a in [a.name for a in o.data.attributes if a.name == "sh"]:
                o.data.attributes.remove(o.data.attributes[a])
        path = export.export_glb(OUT, nodes)
        export.compress(path, max_texture=SIZE, inspect=False)
        if PREVIEW:
            with Placeholders():
                preview.render_each(PREVIEW, nodes, views=VIEWS, size=(640, 640), sheet=True)
                if GAME:
                    game_view(PREVIEW, nodes)
    log("-" * 60)
    log(f"{'node':<22}{'tris':>7}  {'maxY':>6}  bounds / source materials")
    for n, t, s, ms, b in rows:
        log(f"{n:<22}{t:>7}  {s:>6}  {b}  [{', '.join(m for m in ms if m in RUNTIME) or '-'}]")
    log(f"{'total':<22}{sum(r[1] for r in rows):>7}")


main()
