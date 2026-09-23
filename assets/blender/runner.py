# Builds the runner hero asset: a faceless figure in an oversized hoodie,
# hunched over a glowing phone, skinned to a small rig, with its animations.
#
#   blender -b -P assets/blender/runner.py -- public/assets/runner.glb [preview_dir]
#
# Everything is procedural so the asset can be rebuilt (and ported) from this
# file alone:
#   - body: one continuous skin-modifier mesh (hoodie torso + sleeves + joggers),
#     subdivided, with fine fabric displacement, auto-weighted to the rig
#   - hood with real fabric thickness and a void where the face should be
#   - ribbed cuffs, hem and ankle bands; kangaroo pocket shrink-wrapped to the
#     torso; drawstrings with aglets
#   - hands with jointed fingers; the right one grips a detailed phone
#   - chunky sneakers: outsole, midsole, upper, tongue, laces, heel tab
#
# Blender is Z-up and the runner faces +Y (so +X is its right); the glTF
# exporter turns that into Y-up facing -Z, which is the direction the game runs.
# Budget: one character on an iPhone 14 at 60 fps, so ~40k triangles, no textures.
#
# Animations (glTF clip names): run, idle, jump, roll, present.
# Material names the game looks up: Screen (phone light), Hoodie, HoodieDark.

import math
import os
import sys

import bmesh
import bpy
from mathutils import Matrix, Quaternion, Vector

argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
OUT = argv[0] if argv else "public/assets/runner.glb"
PREVIEW = argv[1] if len(argv) > 1 else None

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.fps = 30


# ================================================================ materials

def material(name, rgb, rough=0.8, emit=None, strength=0.0, metal=0.0, sheen=0.0):
    m = bpy.data.materials.new(name)
    if hasattr(m, "use_nodes"):
        m.use_nodes = True
    p = m.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (*rgb, 1)
    p.inputs["Roughness"].default_value = rough
    p.inputs["Metallic"].default_value = metal
    if sheen and "Sheen Weight" in p.inputs:
        p.inputs["Sheen Weight"].default_value = sheen
    if emit:
        p.inputs["Emission Color"].default_value = (*emit, 1)
        p.inputs["Emission Strength"].default_value = strength
    m.diffuse_color = (*rgb, 1)
    return m


MATS = {
    "Hoodie": material("Hoodie", (0.15, 0.13, 0.25)),
    "HoodieDark": material("HoodieDark", (0.08, 0.07, 0.14)),
    "Pants": material("Pants", (0.035, 0.033, 0.045), rough=0.9),
    "Void": material("Void", (0.0, 0.0, 0.0), rough=1.0),
    "Skin": material("Skin", (0.2, 0.15, 0.13), rough=0.6),
    "String": material("String", (0.85, 0.83, 0.88), rough=0.7),
    "Metal": material("Metal", (0.6, 0.6, 0.65), rough=0.25, metal=1.0),
    "Upper": material("Upper", (0.75, 0.74, 0.8), rough=0.7),
    "Midsole": material("Midsole", (0.92, 0.91, 0.95), rough=0.6),
    "Outsole": material("Outsole", (0.05, 0.05, 0.06), rough=0.9),
    "Accent": material("Accent", (0.9, 0.05, 0.3), rough=0.5),
    "Phone": material("Phone", (0.02, 0.02, 0.025), rough=0.25, metal=0.6),
    "Glass": material("Glass", (0.01, 0.01, 0.015), rough=0.05, metal=0.2),
    "Screen": material("Screen", (0.6, 0.85, 1.0), rough=0.15, emit=(0.6, 0.85, 1.0), strength=6.0),
}


# ================================================================ helpers

def link(obj):
    scene.collection.objects.link(obj)
    return obj


def mesh_object(name, bm):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return link(bpy.data.objects.new(name, me))


def add_modifier(obj, kind, **props):
    mod = obj.modifiers.new(kind.lower(), kind)
    for k, v in props.items():
        setattr(mod, k, v)
    return mod


def bake(obj):
    """Apply modifiers and the object transform into the mesh data."""
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(obj.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
    me.transform(obj.matrix_world)
    obj.modifiers.clear()
    old = obj.data
    obj.data = me
    obj.matrix_world = Matrix.Identity(4)
    if old.users == 0:
        bpy.data.meshes.remove(old)
    for poly in me.polygons:
        poly.use_smooth = True
    return obj


def set_material(obj, name):
    obj.data.materials.clear()
    obj.data.materials.append(MATS[name])


def weigh(obj, weights):
    """`weights` is a bone name (full weight), co -> {bone: w}, or BODY to copy
    the auto weights of the nearest body surface (for things sewn onto it)."""
    if isinstance(weights, tuple) and weights[0] is BODY:
        weigh(obj, BODY)
        # Drop some bones' influence (e.g. the thighs dragging a hem) and renormalise.
        for vg in list(obj.vertex_groups):
            if vg.name.startswith(weights[1]):
                obj.vertex_groups.remove(vg)
        with bpy.context.temp_override(object=obj, active_object=obj):
            bpy.ops.object.vertex_group_normalize_all(group_select_mode="ALL", lock_active=False)
        return
    if weights is BODY:
        for vg in body.vertex_groups:
            obj.vertex_groups.new(name=vg.name)
        mod = add_modifier(obj, "DATA_TRANSFER", object=body, use_vert_data=True, vert_mapping="POLYINTERP_NEAREST")
        mod.data_types_verts = {"VGROUP_WEIGHTS"}
        mod.layers_vgroup_select_src = "ALL"
        mod.layers_vgroup_select_dst = "NAME"
        with bpy.context.temp_override(object=obj, active_object=obj):
            bpy.ops.object.modifier_apply(modifier=mod.name)
        return
    if isinstance(weights, str):
        vg = obj.vertex_groups.new(name=weights)
        vg.add(range(len(obj.data.vertices)), 1.0, "REPLACE")
        return
    groups = {}
    for v in obj.data.vertices:
        for name, w in weights(v.co).items():
            if w <= 1e-4:
                continue
            if name not in groups:
                groups[name] = obj.vertex_groups.new(name=name)
            groups[name].add([v.index], w, "REPLACE")


def blend(a, b, co_axis, lo, hi):
    """Weight fn: bone `a` below `lo`, `b` above `hi` along axis 0/1/2."""

    def fn(co):
        t = min(1.0, max(0.0, (co[co_axis] - lo) / (hi - lo)))
        return {a: 1 - t, b: t}

    return fn


ATTACH = []
BODY = object()  # weights sentinel: copy from the body


TRIS = {}


def count(label, obj):
    TRIS[label] = TRIS.get(label, 0) + sum(len(p.vertices) - 2 for p in obj.data.polygons)


def attach(obj, mat, weights):
    if mat:
        set_material(obj, mat)
    bake(obj)
    weigh(obj, weights)
    ATTACH.append(obj)
    count(obj.name.split(".")[0], obj)
    return obj


def skin(name, verts, edges, radii, root=0):
    """Skin-modifier mesh from a stick figure; radii are (rx, ry) per vertex."""
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, edges, [])
    obj = link(bpy.data.objects.new(name, me))
    bpy.context.view_layer.objects.active = obj
    with bpy.context.temp_override(object=obj, active_object=obj):
        bpy.ops.object.modifier_add(type="SKIN")
    obj.modifiers[-1].branch_smoothing = 0.6
    obj.modifiers[-1].use_smooth_shade = True
    data = me.skin_vertices[0].data
    for i, r in enumerate(radii):
        data[i].radius = r
    data[root].use_root = True
    return obj


def primitive(kind, **kw):
    getattr(bpy.ops.mesh, f"primitive_{kind}_add")(**kw)
    return bpy.context.active_object


def rounded_box(name, size, loc, bevel, segments=4, rot=(0, 0, 0)):
    obj = primitive("cube", size=1, location=loc, rotation=rot)
    obj.name = name
    obj.scale = size
    bake(obj)
    add_modifier(obj, "BEVEL", width=bevel, segments=segments, limit_method="NONE")
    return obj


def band(name, center, axis, rx, ry, length, ribs=24, rib=0.0, rows=3, bulge=0.05):
    """A tube band (cuff, hem) with `ribs` vertical ridges of relative depth `rib`.
    Ribs are modelled with 3 vertices each and smooth shading, no subdivision."""
    segs = ribs * 3
    bm = bmesh.new()
    axis = Vector(axis).normalized()
    ref = Vector((0, 0, 1)) if abs(axis.z) < 0.9 else Vector((0, 1, 0))
    u = axis.cross(ref).normalized()
    v = axis.cross(u).normalized()
    rows_v = []
    for r in range(rows):
        t = r / (rows - 1) - 0.5
        row = []
        for i in range(segs):
            a = 2 * math.pi * i / segs
            k = (1 + rib * math.cos(a * ribs)) * (1 + bulge * (1 - (2 * t) ** 2))
            p = Vector(center) + axis * (t * length) + u * (math.cos(a) * rx * k) + v * (math.sin(a) * ry * k)
            row.append(bm.verts.new(p))
        rows_v.append(row)
    for r in range(rows - 1):
        for i in range(segs):
            j = (i + 1) % segs
            bm.faces.new((rows_v[r][i], rows_v[r][j], rows_v[r + 1][j], rows_v[r + 1][i]))
    obj = mesh_object(name, bm)
    add_modifier(obj, "SOLIDIFY", thickness=0.006, offset=0)
    return obj


# ================================================================ skeleton (rest: A-pose)

A = math.radians(30)  # arms 30 degrees out from the body in the rest pose
J = {"pelvis": (0, 0, 0.96), "spine": (0, -0.005, 1.1), "chest": (0, -0.01, 1.27), "upper": (0, -0.015, 1.4), "neck": (0, -0.005, 1.5)}
for side, s in (("R", 1), ("L", -1)):
    sh = Vector((s * 0.19, -0.02, 1.45))
    down = Vector((s * math.sin(A), 0, -math.cos(A)))
    J[f"shoulder.{side}"] = tuple(sh)
    J[f"elbow.{side}"] = tuple(sh + down * 0.29 + Vector((0, -0.01, 0)))
    J[f"wrist.{side}"] = tuple(sh + down * 0.55)
    J[f"hand.{side}"] = tuple(sh + down * 0.64)
    J[f"hip.{side}"] = (s * 0.1, 0, 0.93)
    J[f"knee.{side}"] = (s * 0.105, 0.012, 0.52)
    J[f"ankle.{side}"] = (s * 0.105, -0.01, 0.12)
    J[f"toe.{side}"] = (s * 0.105, 0.15, 0.03)


# ================================================================ body (hoodie + sleeves + joggers)

names = ["pelvis", "spine", "chest", "upper", "neck"]
radii = [(0.17, 0.125), (0.19, 0.14), (0.215, 0.145), (0.225, 0.145), (0.08, 0.075)]
edges = [(0, 1), (1, 2), (2, 3), (3, 4)]
for side in ("R", "L"):
    for name, r, parent in (
        (f"shoulder.{side}", (0.095, 0.09), "upper"),
        (f"elbow.{side}", (0.072, 0.07), f"shoulder.{side}"),
        (f"wrist.{side}", (0.055, 0.052), f"elbow.{side}"),
        (f"hip.{side}", (0.105, 0.105), "pelvis"),
        (f"knee.{side}", (0.078, 0.082), f"hip.{side}"),
        (f"ankle.{side}", (0.056, 0.058), f"knee.{side}"),
    ):
        names.append(name)
        radii.append(r)
        edges.append((names.index(parent), len(names) - 1))
body = skin("Runner", [J[n] for n in names], edges, radii)
add_modifier(body, "SUBSURF", levels=3, render_levels=3)
bake(body)

# Materials by region: joggers below the hem (legs only), hoodie elsewhere.
body.data.materials.append(MATS["Hoodie"])
body.data.materials.append(MATS["Pants"])
for poly in body.data.polygons:
    c = poly.center
    poly.material_index = 1 if (c.z < 0.935 and abs(c.x) < 0.2) else 0

# Fabric: soft, low-frequency folds (baked into the geometry, no textures).
folds = bpy.data.textures.new("folds", "CLOUDS")
folds.noise_scale = 0.06
folds.noise_depth = 2
add_modifier(body, "DISPLACE", texture=folds, strength=0.012, mid_level=0.5, texture_coords="GLOBAL")
bake(body)


# ================================================================ rig

arm_data = bpy.data.armatures.new("RunnerRig")
rig = link(bpy.data.objects.new("RunnerRig", arm_data))
bpy.context.view_layer.objects.active = rig
bpy.ops.object.mode_set(mode="EDIT")

BONES = {
    "hips": (J["pelvis"], J["spine"], None),
    "spine": (J["spine"], J["chest"], "hips"),
    "chest": (J["chest"], (0, -0.015, 1.45), "spine"),
    "neck": ((0, -0.015, 1.45), (0, -0.005, 1.56), "chest"),
    "head": ((0, -0.005, 1.56), (0, 0.02, 1.82), "neck"),
}
for side, s in (("R", 1), ("L", -1)):
    BONES[f"shoulder.{side}"] = ((s * 0.03, -0.015, 1.42), J[f"shoulder.{side}"], "chest")
    BONES[f"upperArm.{side}"] = (J[f"shoulder.{side}"], J[f"elbow.{side}"], f"shoulder.{side}")
    BONES[f"forearm.{side}"] = (J[f"elbow.{side}"], J[f"wrist.{side}"], f"upperArm.{side}")
    BONES[f"hand.{side}"] = (J[f"wrist.{side}"], J[f"hand.{side}"], f"forearm.{side}")
    BONES[f"thigh.{side}"] = (J[f"hip.{side}"], J[f"knee.{side}"], "hips")
    BONES[f"shin.{side}"] = (J[f"knee.{side}"], J[f"ankle.{side}"], f"thigh.{side}")
    BONES[f"foot.{side}"] = (J[f"ankle.{side}"], J[f"toe.{side}"], f"shin.{side}")

for name, (head, tail, parent) in BONES.items():
    b = arm_data.edit_bones.new(name)
    b.head, b.tail = head, tail
    b.roll = 0
    if parent:
        b.parent = arm_data.edit_bones[parent]
AXES = {b.name: (b.x_axis.copy(), b.y_axis.copy(), b.z_axis.copy()) for b in arm_data.edit_bones}
bpy.ops.object.mode_set(mode="OBJECT")

# Auto (bone heat) weights for the continuous body.
with bpy.context.temp_override(active_object=rig, object=rig, selected_editable_objects=[body, rig], selected_objects=[body, rig]):
    bpy.ops.object.parent_set(type="ARMATURE_AUTO")

# The hoodie hangs from the hips: fade the thighs' pull out of the torso fabric
# above the hip line, so striding legs don't drag it out under the hem.
thighs = [body.vertex_groups[f"thigh.{s}"].index for s in ("R", "L")]
hips_g = body.vertex_groups["hips"]
for v in body.data.vertices:
    if abs(v.co.x) > 0.2 or v.co.z < 0.86:
        continue
    keep = min(1.0, max(0.0, (0.96 - v.co.z) / 0.1))  # 1 at 0.86 and below, 0 from 0.96 up
    moved = 0.0
    for g in v.groups:
        if g.group in thighs:
            moved += g.weight * (1 - keep)
            g.weight *= keep
    if moved:
        hips_g.add([v.index], moved + next((g.weight for g in v.groups if g.group == hips_g.index), 0.0), "REPLACE")


# ================================================================ hood

hood = primitive("uv_sphere", segments=28, ring_count=16, radius=1)
for v in hood.data.vertices:
    x, y, z = v.co
    if z < 0:
        z *= 1.45  # drape down onto the neck and shoulders
    if y < 0:
        y *= 1.18  # fabric bunched at the back
        z += 0.12 * max(0.0, -y) * max(0.0, z)  # a soft peak at the back-top
    v.co = (x * 0.19, y * 0.2, z * 0.2)
hood.location = (0, 0.0, 1.645)
opening = primitive("uv_sphere", segments=32, ring_count=20, radius=1, location=(0, 0.17, 1.625))
opening.scale = (0.125, 0.15, 0.148)
add_modifier(hood, "BOOLEAN", operation="DIFFERENCE", object=opening, solver="EXACT")
add_modifier(hood, "SOLIDIFY", thickness=0.022, offset=-1, use_rim=True)
add_modifier(hood, "SUBSURF", levels=1, render_levels=1)
add_modifier(hood, "DISPLACE", texture=folds, strength=0.006, mid_level=0.5, texture_coords="GLOBAL")
attach(hood, "Hoodie", blend("chest", "head", 2, 1.46, 1.56))
bpy.data.objects.remove(opening)

void = primitive("uv_sphere", segments=24, ring_count=16, radius=1, location=(0, 0.035, 1.63))
void.scale = (0.14, 0.13, 0.155)
attach(void, "Void", "head")

# Drawstrings from the hood opening down the chest, with metal aglets.
for s in (1, -1):
    pts = [(s * 0.06, 0.155, 1.53), (s * 0.058, 0.17, 1.47), (s * 0.055, 0.172, 1.4), (s * 0.052, 0.168, 1.34)]
    rope = skin("string", pts, [(0, 1), (1, 2), (2, 3)], [(0.0045, 0.0045)] * 4)
    add_modifier(rope, "SUBSURF", levels=1)
    attach(rope, "String", blend("chest", "neck", 2, 1.45, 1.52))
    tip = primitive("cylinder", vertices=12, radius=0.0055, depth=0.022, location=(s * 0.052, 0.168, 1.325))
    attach(tip, "Metal", "chest")


# ================================================================ hoodie details

# Ribbed hem band and kangaroo pocket.
attach(band("hem", (0, -0.005, 0.95), (0, 0, 1), 0.185, 0.137, 0.065, ribs=44, rib=0.012), "HoodieDark", (BODY, "thigh"))

pocket = primitive("plane", size=1, location=(0, 0.2, 1.06), rotation=(math.radians(90), 0, 0))
pocket.scale = (0.25, 0.13, 1)
bake(pocket)
bm = bmesh.new()
bm.from_mesh(pocket.data)
bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=8, use_grid_fill=True)
for v in bm.verts:  # trapezoid: narrower at the top, openings slant on the sides
    t = (v.co.z - 0.995) / 0.13
    v.co.x *= 1.0 - 0.18 * t
bm.to_mesh(pocket.data)
bm.free()
add_modifier(pocket, "SHRINKWRAP", target=body, wrap_method="PROJECT", use_project_y=True, use_negative_direction=True, offset=0.004)
add_modifier(pocket, "SOLIDIFY", thickness=0.008, offset=1)
add_modifier(pocket, "SUBSURF", levels=1)
attach(pocket, "Hoodie", (BODY, "thigh"))

# Sleeve cuffs and jogger ankle cuffs.
for side, s in (("R", 1), ("L", -1)):
    wrist = Vector(J[f"wrist.{side}"])
    axis = (Vector(J[f"elbow.{side}"]) - wrist).normalized()
    attach(band(f"cuff.{side}", wrist + axis * 0.02, axis, 0.05, 0.048, 0.05, ribs=22, rib=0.03), "HoodieDark", BODY)
    ankle = Vector(J[f"ankle.{side}"])
    attach(band(f"ankle.{side}", ankle + Vector((0, 0, 0.035)), (0, 0, 1), 0.052, 0.054, 0.06, ribs=22, rib=0.03), "Pants", BODY)


# ================================================================ hands

def hand(side, s, grip):
    """Built in a hand frame (wrist at origin, fingers toward -Z, palm facing
    the body at -X*s, thumb forward at +Y), then placed at the wrist."""
    parts = []
    palm = rounded_box("palm", (0.03, 0.078, 0.085), (0, 0.004, -0.05), 0.012)
    add_modifier(palm, "SUBSURF", levels=1)
    bake(palm)
    parts.append(palm)
    # Fingers: y at the knuckle, segment lengths; each joint curls by `grip`.
    fingers = [(0.026, (0.042, 0.026, 0.022)), (0.009, (0.046, 0.028, 0.023)), (-0.009, (0.044, 0.027, 0.022)), (-0.025, (0.036, 0.022, 0.019))]
    for y0, segs in fingers:
        pts = [Vector((0, y0, -0.092))]
        angle = 0.0
        for i, length in enumerate(segs):
            angle += math.radians(grip[i])
            d = Vector((-s * math.sin(angle), 0, -math.cos(angle)))  # curl toward the palm side
            pts.append(pts[-1] + d * length)
        r = [(0.0105, 0.0105), (0.0098, 0.0098), (0.009, 0.009), (0.0082, 0.0082)]
        f = skin("finger", [tuple(p) for p in pts], [(0, 1), (1, 2), (2, 3)], r)
        add_modifier(f, "SUBSURF", levels=1)
        bake(f)
        parts.append(f)
    # Thumb: from the palm's front edge, lying along the phone screen.
    tpts = [(-s * 0.01, 0.035, -0.03), (-s * 0.028, 0.052, -0.06), (-s * 0.04, 0.056, -0.095), (-s * 0.045, 0.05, -0.12)]
    th = skin("thumb", tpts, [(0, 1), (1, 2), (2, 3)], [(0.013, 0.013), (0.012, 0.012), (0.0105, 0.0105), (0.0095, 0.0095)])
    add_modifier(th, "SUBSURF", levels=1)
    bake(th)
    parts.append(th)

    # Place: rotate the frame to the arm's rest direction, move to the wrist.
    down = (Vector(J[f"hand.{side}"]) - Vector(J[f"wrist.{side}"])).normalized()
    rot = Vector((0, 0, -1)).rotation_difference(down).to_matrix().to_4x4()
    place = Matrix.Translation(Vector(J[f"wrist.{side}"])) @ rot
    for p in parts:
        p.data.transform(place)
        attach(p, "Skin", f"hand.{side}")
    return place


place_r = hand("R", 1, grip=(62, 58, 40))
hand("L", -1, grip=(38, 45, 30))


# ================================================================ phone (right hand)

def phone(place):
    parts = []
    shell = rounded_box("phone", (0.0085, 0.074, 0.152), (-0.03, 0.012, -0.12), 0.0035, segments=5)
    set_material(shell, "Phone")
    parts.append(shell)
    screen = rounded_box("screen", (0.0012, 0.068, 0.146), (-0.0348, 0.012, -0.12), 0.0006, segments=2)
    set_material(screen, "Screen")
    parts.append(screen)
    bump = rounded_box("bump", (0.0022, 0.03, 0.03), (-0.0247, -0.006, -0.178), 0.001, segments=3)
    set_material(bump, "Phone")
    parts.append(bump)
    for dy, dz in ((0.0, 0.007), (-0.012, 0.007), (-0.006, -0.006)):
        lens = primitive("cylinder", vertices=16, radius=0.0045, depth=0.003, location=(-0.0232, dy, -0.178 + dz), rotation=(0, math.radians(90), 0))
        set_material(lens, "Glass")
        parts.append(lens)
    for p in parts:
        bake(p)
        p.data.transform(place)
        attach(p, None, "hand.R")


phone(place_r)


# ================================================================ sneakers

for side, s in (("R", 1), ("L", -1)):
    ax, ay = J[f"ankle.{side}"][0], J[f"ankle.{side}"][1]
    y0 = ay + 0.07  # sole centre along the foot

    attach(rounded_box("outsole", (0.112, 0.3, 0.028), (ax, y0, 0.014), 0.011), "Outsole", f"foot.{side}")
    attach(rounded_box("midsole", (0.108, 0.292, 0.034), (ax, y0 - 0.002, 0.043), 0.013), "Midsole", f"foot.{side}")

    upper = primitive("cube", size=1, location=(ax, y0 - 0.005, 0.1))
    upper.scale = (0.1, 0.27, 0.1)
    bake(upper)
    bm = bmesh.new()
    bm.from_mesh(upper.data)
    bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=3, use_grid_fill=True)
    for v in bm.verts:
        fy = (v.co.y - (y0 - 0.005)) / 0.135  # -1 heel .. +1 toe
        if v.co.z > 0.08:
            v.co.z -= 0.045 * max(0.0, fy) ** 1.3  # toe slopes down
            v.co.z += 0.03 * max(0.0, -fy)  # collar rises at the heel
        v.co.x = ax + (v.co.x - ax) * (1 - 0.12 * max(0.0, fy))
    bm.to_mesh(upper.data)
    bm.free()
    add_modifier(upper, "SUBSURF", levels=1)
    attach(upper, "Upper", blend(f"foot.{side}", f"shin.{side}", 2, 0.1, 0.16))

    attach(rounded_box("tongue", (0.05, 0.06, 0.02), (ax, y0 - 0.02, 0.165), 0.008, rot=(math.radians(-35), 0, 0)), "Upper", f"shin.{side}")
    attach(rounded_box("heel", (0.03, 0.012, 0.05), (ax, y0 - 0.14, 0.14), 0.005), "Accent", f"foot.{side}")
    for i in range(5):
        ly = y0 - 0.005 + i * 0.022
        lz = 0.152 - i * 0.011
        lace = primitive("cylinder", vertices=8, radius=0.0035, depth=0.052, location=(ax, ly, lz), rotation=(0, math.radians(90), math.radians(10 if i % 2 else -10)))
        attach(lace, "String", f"foot.{side}")


# ================================================================ join

count("body", body)
with bpy.context.temp_override(active_object=body, object=body, selected_editable_objects=[body] + ATTACH):
    bpy.ops.object.join()
body.name = "Runner"
body.data.name = "Runner"
# Keep influences glTF-friendly (max 4 per vertex, normalised).
with bpy.context.temp_override(object=body, active_object=body):
    bpy.ops.object.vertex_group_limit_total(group_select_mode="ALL", limit=4)
    bpy.ops.object.vertex_group_normalize_all(group_select_mode="ALL", lock_active=False)


# ================================================================ posing
#
# Spine and legs are posed by intent angles (swing forward / toward the centre).
# Arms are posed by aiming: give each bone a direction in armature space (and,
# for hands, which way the palm should face), which keeps the phone hold exact.

FWD = Vector((0, 1, 0))
DOWN = Vector((0, 0, -1))
ARM_BONES = {f"{b}.{s}" for b in ("upperArm", "forearm", "hand") for s in ("R", "L")}
HEAD_POS = Vector((0, 0.12, 1.6))


def pose(pb, fwd=0.0, side=0.0):
    """`fwd`: tail swings forward (vertical bones) or pitches down (horizontal
    ones). `side`: tail swings toward the body's centre line."""
    x_axis, y_axis, z_axis = AXES[pb.name]
    aim_dir = FWD if abs(y_axis.z) > 0.5 else DOWN
    s_fwd = 1 if z_axis.dot(aim_dir) >= 0 else -1  # local X rotation moves the tail toward local +Z
    hx = pb.bone.tail_local.x
    centre = Vector((-math.copysign(1, hx), 0, 0)) if abs(hx) > 1e-4 else Vector((0, 0, 0))
    s_side = 1 if (-x_axis).dot(centre) >= 0 else -1  # local Z rotation moves the tail toward local -X
    pb.rotation_mode = "XYZ"
    pb.rotation_euler = (math.radians(fwd) * s_fwd, 0, math.radians(side) * s_side)


def aim(pb, direction, face_rest=None, face_to=None):
    """Point the bone along `direction`; optionally twist it so a rest-pose
    direction carried by the bone (`face_rest`) turns toward `face_to`."""
    bpy.context.view_layer.update()
    if pb.parent:
        base = (pb.parent.matrix @ pb.parent.bone.matrix_local.inverted() @ pb.bone.matrix_local).to_3x3().normalized()
    else:
        base = pb.bone.matrix_local.to_3x3().normalized()
    d = Vector(direction).normalized()
    R = base.col[1].rotation_difference(d).to_matrix() @ base
    if face_rest is not None:
        local = pb.bone.matrix_local.to_3x3().normalized().inverted() @ Vector(face_rest)
        now = R @ local
        axis = R.col[1]
        a = (now - axis * now.dot(axis)).normalized()
        t = Vector(face_to)
        b = (t - axis * t.dot(axis)).normalized()
        R = Quaternion(axis, math.atan2(axis.dot(a.cross(b)), a.dot(b))).to_matrix() @ R
    pb.rotation_mode = "QUATERNION"
    pb.rotation_quaternion = (base.inverted() @ R).to_quaternion()


def hold(upper_r, fore_r, hand_r, upper_l, fore_l, hand_l):
    """Arm aims (directions are for the right side; x is mirrored for the left)."""
    return {
        "upperArm.R": upper_r, "forearm.R": fore_r, "hand.R": hand_r,
        "upperArm.L": upper_l, "forearm.L": fore_l, "hand.L": hand_l,
    }


def mirror(v):
    return (-v[0], v[1], v[2])


def key(frame, poses, arms, hips_y=0.0):
    for pb in rig.pose.bones:  # creation order: parents before children
        if pb.name in ARM_BONES:
            side = pb.name[-1]
            d = arms[pb.name]
            if side == "L":
                d = mirror(d)
            if pb.name.startswith("hand"):
                # Palm faces the body in the rest pose; turn it up toward the hood.
                s = 1 if side == "R" else -1
                bpy.context.view_layer.update()
                to_head = HEAD_POS - pb.head
                aim(pb, d, face_rest=(-s, 0, 0), face_to=to_head)
            else:
                aim(pb, d)
            pb.keyframe_insert("rotation_quaternion", frame=frame)
        else:
            f, sd = poses.get(pb.name, (0, 0))
            pose(pb, f, sd)
            pb.keyframe_insert("rotation_euler", frame=frame)
    hips = rig.pose.bones["hips"]
    hips.location = (0, hips_y, 0)  # bone-local Y runs along the bone, i.e. up
    hips.keyframe_insert("location", frame=frame)


# The doomscroll hold: elbows in, forearms forward, phone at chest height,
# screen tilted up to the hood. Left hand hovers under it.
HOLD = hold((0.12, 0.3, -1), (-0.35, 1, 0.3), (-0.2, 1, 0.75), (0.1, 0.25, -1), (-0.55, 1, 0.2), (-0.5, 1, 0.3))
HANG = hold((0.12, 0.04, -1), (0.07, 0.14, -1), (0.04, 0.12, -1), (0.12, 0.04, -1), (0.07, 0.14, -1), (0.04, 0.12, -1))
HUNCH = {"spine": (10, 0), "chest": (8, 0), "neck": (14, 0), "head": (16, 0), "shoulder.R": (0, -6), "shoulder.L": (0, -6)}


def lerp_arms(a, b, k):
    return {n: tuple(a[n][i] + (b[n][i] - a[n][i]) * k for i in range(3)) for n in a}


def action(name):
    act = bpy.data.actions.new(name)
    act.use_fake_user = True
    rig.animation_data_create()
    rig.animation_data.action = act
    return act


# run: 16 frames, looped (the game scales its speed with run speed).
action("run")
N = 16
for f in range(0, N + 1, 2):
    ph = 2 * math.pi * f / N
    p = dict(HUNCH)
    p["spine"] = (14, 0)
    for side, sgn in (("R", 1), ("L", -1)):
        swing = sgn * math.sin(ph)
        p[f"thigh.{side}"] = (46 * swing, 0)
        lift = max(0.0, sgn * math.cos(ph))  # knee flexes while the leg swings forward
        p[f"shin.{side}"] = (-(14 + 72 * lift), 0)
        p[f"foot.{side}"] = (18 * max(0.0, -swing) - 10 * lift, 0)  # toe-off behind, toe up in swing
    arms = dict(HOLD)
    bob = 0.06 * math.sin(2 * ph)
    for n in ("upperArm.R", "upperArm.L"):
        x, y, z = arms[n]
        arms[n] = (x, y + bob, z)
    key(f, p, arms, hips_y=0.035 * abs(math.cos(ph)) - 0.02)

# idle: standing, thumb-scrolling, 60 frames.
action("idle")
for f in range(0, 61, 10):
    ph = 2 * math.pi * f / 60
    p = dict(HUNCH)
    p["chest"] = (8 + 2 * math.sin(ph), 0)
    p["head"] = (18 + 3 * math.sin(ph * 2), 0)
    arms = dict(HOLD)
    x, y, z = arms["hand.R"]
    arms["hand.R"] = (x, y, z + 0.12 * max(0.0, math.sin(ph * 3)))  # scroll flick
    key(f, p, arms, hips_y=-0.005 * math.sin(ph))

# jump: tuck, held.
action("jump")
for f in (0, 8):
    p = dict(HUNCH)
    p["spine"] = (20, 0)
    p["thigh.R"] = (70, 0)
    p["shin.R"] = (-95, 0)
    p["foot.R"] = (20, 0)
    p["thigh.L"] = (-15, 0)
    p["shin.L"] = (-60, 0)
    p["foot.L"] = (25, 0)
    key(f, p, HOLD)

# roll: curled into a ball, still looking at the phone.
action("roll")
for f in (0, 8):
    p = {"spine": (45, 0), "chest": (28, 0), "neck": (12, 0), "head": (12, 0)}
    for side in ("R", "L"):
        p[f"thigh.{side}"] = (105, 0)
        p[f"shin.{side}"] = (-135, 0)
        p[f"foot.{side}"] = (20, 0)
    tucked = hold((0.1, 0.6, -1), (-0.4, 1, 0.1), (-0.2, 1, 0.5), (0.1, 0.55, -1), (-0.5, 1, 0.05), (-0.4, 1, 0.2))
    key(f, p, tucked, hips_y=-0.38)

# present: dopamine is gone. The arms drop, the head comes up. 36 frames.
action("present")
end = {"spine": (0, 0), "chest": (-2, 0), "neck": (-6, 0), "head": (-8, 0)}
for f, k in ((0, 0.0), (12, 0.45), (24, 0.85), (36, 1.0)):
    p = {}
    for bone in set(HUNCH) | set(end):
        a = HUNCH.get(bone, (0, 0))
        b = end.get(bone, (0, 0))
        p[bone] = (a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k)
    key(f, p, lerp_arms(HOLD, HANG, k))

rig.animation_data.action = bpy.data.actions["idle"]


# ================================================================ export

tris = sum(len(p.vertices) - 2 for p in body.data.polygons)
os.makedirs(os.path.dirname(os.path.abspath(OUT)), exist_ok=True)
bpy.ops.export_scene.gltf(
    filepath=OUT,
    export_format="GLB",
    export_yup=True,
    export_skins=True,
    export_animations=True,
    export_animation_mode="ACTIONS",
    export_force_sampling=True,
    export_optimize_animation_size=True,
    export_def_bones=False,
    export_cameras=False,
    export_lights=False,
    export_apply=False,
    export_texcoords=False,
)
print(f"runner: wrote {OUT} ({os.path.getsize(OUT) // 1024} KB, {len(body.data.vertices)} verts, {tris} tris)")
print("runner: tris by part", sorted(TRIS.items(), key=lambda kv: -kv[1]))


# ================================================================ preview

if PREVIEW:
    os.makedirs(PREVIEW, exist_ok=True)
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 768
    scene.render.resolution_y = 960
    scene.view_settings.view_transform = "AgX"
    world = bpy.data.worlds.new("bg")
    scene.world = world
    world.color = (0.03, 0.02, 0.05)

    def light(loc, color, energy, size=0.5):
        data = bpy.data.lights.new("l", "AREA")
        data.color = color
        data.energy = energy
        data.size = size
        obj = link(bpy.data.objects.new("l", data))
        obj.location = loc
        obj.rotation_euler = (Vector((0, 0, 1.0)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()

    light((2.2, 2.5, 2.4), (1.0, 0.95, 0.9), 400, 1.5)  # key
    light((-2.5, 1.0, 1.5), (0.5, 0.6, 1.0), 150, 2.0)  # fill
    light((0.5, -2.5, 2.5), (1.0, 0.25, 0.6), 500, 1.0)  # magenta rim
    floor = primitive("plane", size=20)
    floor.data.materials.append(material("floor", (0.05, 0.045, 0.06), rough=0.6))

    cam_data = bpy.data.cameras.new("cam")
    cam = link(bpy.data.objects.new("cam", cam_data))
    scene.camera = cam
    views = {
        "front": ((1.6, 3.2, 1.4), (0, 0, 0.95), 50),
        "side": ((3.6, 0.3, 1.1), (0, 0, 0.92), 50),
        "back": ((0.6, -3.4, 2.1), (0, 0, 1.0), 50),
        "hands": ((0.9, 1.1, 1.55), (0.12, 0.25, 1.22), 70),
    }
    shots = (("idle", 0, ("front", "side", "back", "hands")), ("run", 4, ("side", "back")), ("present", 36, ("front",)))
    for act_name, frame, vs in shots:
        rig.animation_data.action = bpy.data.actions[act_name]
        scene.frame_set(frame)
        for view in vs:
            loc, target, lens = views[view]
            cam_data.lens = lens
            cam.location = loc
            cam.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
            scene.render.filepath = os.path.join(PREVIEW, f"{act_name}{frame}_{view}.png")
            bpy.ops.render.render(write_still=True)
    print(f"runner: previews in {PREVIEW}")
