# Builds a playable doomscroller: a faceless figure hunched over a glowing
# screen, skinned to a small rig, with its animations. Every character shares
# the rig, the clips and most of the body; CHARACTERS picks the outfit, head,
# props, colours and how the screen is held.
#
#   blender -b -P assets/blender/runner.py -- [out.glb] [preview_dir] [--character goblin]
#
# `npm run assets` builds every character into public/assets/characters/<id>.glb.
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
# Material names the game looks up: Screen* (screen light), Hoodie, HoodieDark.

import math
import os
import sys

import bmesh
import bpy
from mathutils import Matrix, Quaternion, Vector

argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
CHAR = "goblin"
if "--character" in argv:
    i = argv.index("--character")
    CHAR = argv[i + 1]
    del argv[i : i + 2]
OUT = argv[0] if argv else f"public/assets/characters/{CHAR}.glb"
PREVIEW = argv[1] if len(argv) > 1 else None


# ================================================================ characters
#
# head:   "hood" (hood up around the face void) or "bare" (a smooth head with
#         a void where the face should be), scaled by head_scale.
# arms:   "sleeve" (hoodie sleeves + ribbed cuffs) or "bare" (skin below a
#         short trimmed sleeve: a muscle tee).
# hem:    material of the ribbed band at the waist (False for none).
# bulk:   thickness of chest, shoulders and arms. belly: front-back girth of
#         the waist.
# hold:   key into HOLDS (how the arms carry the screen).
# props:  extra parts, see the builders under "props".
# colours: material overrides (linear RGB).

CHARACTERS = {
    "goblin": dict(head="hood", arms="sleeve", hem=True, pocket=True, strings=True, props=("phone",), hold="scroll"),
    "bro": dict(
        head="bare", arms="bare", bulk=1.18, hem="Pants", pocket=False, strings=False, hold="double",
        props=("phone", "phone.L", "cap", "airpods", "fannypack"),
        colours={"Hoodie": (0.82, 0.82, 0.85), "HoodieDark": (0.5, 0.5, 0.53), "Pants": (0.12, 0.12, 0.14), "Accent": (1.0, 0.35, 0.02)},
    ),
    "kid": dict(
        head="bare", head_scale=1.3, arms="sleeve", hem=True, pocket=True, strings=False, hold="tablet",
        props=("tablet", "headphones", "hood.down"),
        colours={"Hoodie": (0.8, 0.52, 0.03), "HoodieDark": (0.45, 0.28, 0.02), "Pants": (0.05, 0.08, 0.2), "Accent": (0.02, 0.7, 0.85)},
    ),
    "uncle": dict(
        head="bare", arms="sleeve", bulk=1.08, belly=1.4, hem="HoodieDark", pocket=False, strings=False, hold="far",
        props=("tablet.far", "glasses", "belt", "shawl"),
        colours={"Hoodie": (0.16, 0.025, 0.035), "HoodieDark": (0.09, 0.012, 0.018), "Pants": (0.2, 0.3, 0.45),
                 "Upper": (0.28, 0.16, 0.08), "Midsole": (0.22, 0.13, 0.06), "Accent": (0.28, 0.16, 0.08)},
    ),
    "influencer": dict(
        head="bare", arms="sleeve", hem=True, pocket=False, strings=False, hold="selfie",
        props=("selfie", "bun", "ringlight"),
        colours={"Hoodie": (0.95, 0.3, 0.55), "HoodieDark": (0.6, 0.12, 0.3), "Pants": (0.85, 0.8, 0.75), "Hair": (0.7, 0.5, 0.22), "Accent": (0.95, 0.3, 0.55)},
    ),
    "wellness": dict(
        head="bare", arms="sleeve", hem=True, pocket=False, strings=False, hold="sip",
        props=("phone", "matcha", "ponytail", "yogamat"),
        colours={"Hoodie": (0.22, 0.36, 0.25), "HoodieDark": (0.14, 0.24, 0.16), "Pants": (0.2, 0.14, 0.34), "Hair": (0.12, 0.07, 0.04), "Accent": (0.5, 0.3, 0.7)},
    ),
    "doomer": dict(
        head="bare", arms="sleeve", hem="HoodieDark", pocket=False, strings=False, hold="double",
        props=("phone", "phone.L.news", "phone.L.news2", "collar.up", "belt", "beanie"),
        colours={"Hoodie": (0.2, 0.15, 0.07), "HoodieDark": (0.12, 0.09, 0.04), "Pants": (0.06, 0.06, 0.07), "Accent": (0.03, 0.03, 0.035)},
    ),
}
C = CHARACTERS[CHAR]
BULK = C.get("bulk", 1.0)
HEAD_SCALE = C.get("head_scale", 1.0)

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
    # A second screen showing green candles (the Bro's crypto phone).
    "ScreenAlt": material("ScreenAlt", (0.2, 1.0, 0.45), rough=0.15, emit=(0.2, 1.0, 0.45), strength=5.0),
    # Breaking-news red (the Doomer's other phones) and the ring light.
    "ScreenNews": material("ScreenNews", (1.0, 0.15, 0.1), rough=0.15, emit=(1.0, 0.15, 0.1), strength=5.0),
    "ScreenRing": material("ScreenRing", (1.0, 0.95, 0.9), rough=0.3, emit=(1.0, 0.95, 0.9), strength=2.0),
    "Hair": material("Hair", (0.05, 0.03, 0.02), rough=0.55, sheen=0.4),
    "Matcha": material("Matcha", (0.45, 0.65, 0.25), rough=0.4),
}
for _name, _rgb in C.get("colours", {}).items():
    # Replace, keeping the exact name: the game finds materials by name.
    _rough = MATS[_name].node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value
    bpy.data.materials.remove(MATS[_name])
    MATS[_name] = material(_name, _rgb, rough=_rough)


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
BELLY = C.get("belly", 1.0)
radii = [(0.17, 0.125 * (1 + (BELLY - 1) * 0.6)), (0.19 * (1 + (BELLY - 1) * 0.2), 0.14 * BELLY), (0.215 * BULK, 0.145 * BULK * (1 + (BELLY - 1) * 0.4)), (0.225 * BULK, 0.145 * BULK), (0.08, 0.075)]
edges = [(0, 1), (1, 2), (2, 3), (3, 4)]
for side in ("R", "L"):
    for name, r, parent in (
        (f"shoulder.{side}", (0.095 * BULK, 0.09 * BULK), "upper"),
        (f"elbow.{side}", (0.072 * BULK, 0.07 * BULK), f"shoulder.{side}"),
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


# Materials by region: joggers below the hem (legs only), top elsewhere, and
# bare arms below the sleeve for a muscle tee (needs the auto weights, so it
# runs after skinning).
body.data.materials.append(MATS["Hoodie"])
body.data.materials.append(MATS["Pants"])
body.data.materials.append(MATS["Skin"])

BARE_FROM = 0.13  # metres down the arm from the shoulder joint


def on_bare_arm(c):
    """Past the shoulder along the arm, and close to the arm's axis. Measured
    along the limb so the edge follows the skin mesh's rings (a clean line)."""
    side = "R" if c.x > 0 else "L"
    sh = Vector(J[f"shoulder.{side}"])
    down = (Vector(J[f"wrist.{side}"]) - sh).normalized()
    t = (c - sh).dot(down)
    return t > BARE_FROM


ARM_GROUPS = {body.vertex_groups[f"{b}.{s}"].index for b in ("upperArm", "forearm", "hand") for s in ("R", "L")}


def arm_weight(poly):
    """Average share of the arm bones in this face's vertices (0 = torso)."""
    vs = body.data.vertices
    return sum(sum(g.weight for g in vs[i].groups if g.group in ARM_GROUPS) for i in poly.vertices) / len(poly.vertices)


for poly in body.data.polygons:
    c = poly.center
    if c.z < 0.935 and abs(c.x) < 0.2:
        poly.material_index = 1
    elif C["arms"] == "bare" and arm_weight(poly) > 0.5 and on_bare_arm(c):
        poly.material_index = 2
    else:
        poly.material_index = 0


# ================================================================ head

def hood_up():
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


# Bare head: centre and radii, so hats and headphones can sit on it.
HEAD_R = Vector((0.112, 0.122, 0.135)) * HEAD_SCALE
HEAD_C = Vector((0, 0.02, 1.5 + HEAD_R.z * 0.95))


def bare_head():
    head = primitive("uv_sphere", segments=28, ring_count=16, radius=1, location=HEAD_C)
    head.scale = HEAD_R
    attach(head, "Skin", blend("neck", "head", 2, 1.5, 1.58))
    # The face is a smooth black void, like the hood's.
    face = primitive("uv_sphere", segments=24, ring_count=14, radius=1, location=HEAD_C + Vector((0, HEAD_R.y * 0.6, HEAD_R.z * 0.08)))
    face.scale = (HEAD_R.x * 0.8, HEAD_R.y * 0.45, HEAD_R.z * 0.66)
    attach(face, "Void", "head")


if C["head"] == "hood":
    hood_up()
else:
    bare_head()

# Drawstrings from the hood opening down the chest, with metal aglets.
if C.get("strings"):
    for s in (1, -1):
        pts = [(s * 0.06, 0.155, 1.53), (s * 0.058, 0.17, 1.47), (s * 0.055, 0.172, 1.4), (s * 0.052, 0.168, 1.34)]
        rope = skin("string", pts, [(0, 1), (1, 2), (2, 3)], [(0.0045, 0.0045)] * 4)
        add_modifier(rope, "SUBSURF", levels=1)
        attach(rope, "String", blend("chest", "neck", 2, 1.45, 1.52))
        tip = primitive("cylinder", vertices=12, radius=0.0055, depth=0.022, location=(s * 0.052, 0.168, 1.325))
        attach(tip, "Metal", "chest")


# ================================================================ hoodie details

# Ribbed hem band and kangaroo pocket.
if C.get("hem"):
    hem_mat = C["hem"] if isinstance(C["hem"], str) else "HoodieDark"
    attach(band("hem", (0, -0.005, 0.95), (0, 0, 1), 0.185, 0.137, 0.065, ribs=44, rib=0.012), hem_mat, (BODY, "thigh"))


def kangaroo_pocket():
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


if C.get("pocket"):
    kangaroo_pocket()

# Sleeve cuffs and jogger ankle cuffs.
for side, s in (("R", 1), ("L", -1)):
    wrist = Vector(J[f"wrist.{side}"])
    axis = (Vector(J[f"elbow.{side}"]) - wrist).normalized()
    if C["arms"] == "sleeve":
        attach(band(f"cuff.{side}", wrist + axis * 0.02, axis, 0.05, 0.048, 0.05, ribs=22, rib=0.03), "HoodieDark", BODY)
    else:
        # The tee's sleeve edge, hiding where fabric turns into skin.
        sh = Vector(J[f"shoulder.{side}"])
        down = (wrist - sh).normalized()
        r = 0.092 * BULK
        attach(band(f"sleeve.{side}", sh + down * BARE_FROM, down, r, r * 0.96, 0.03, ribs=22, rib=0.02), "HoodieDark", f"upperArm.{side}")
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


GRIP = (62, 58, 40)
place_r = hand("R", 1, grip=GRIP)
# The left hand grips too when it holds its own phone; otherwise it hovers.
HOLDS_LEFT = ("phone.L", "phone.L.news", "matcha")
place_l = hand("L", -1, grip=GRIP if any(p in C["props"] for p in HOLDS_LEFT) else (38, 45, 30))


# ================================================================ screens

def phone(place, s=1, screen_mat="Screen", size=1.0, name="phone", reach=0.0, fan=0.0):
    """A phone in the hand frame of side `s` (palm at -X*s). `size` scales it
    up into a tablet, growing away from the grip along the fingers. `reach`
    pushes it out along the fingers (a selfie stick); `fan` slides it sideways
    toward the thumb (a second phone in the same hand)."""
    parts = []
    k = size
    cz = -0.12 - 0.076 * (k - 1) - reach  # keep the bottom edge in the palm
    cy = 0.012 + 0.02 * (k - 1) + fan
    shell = rounded_box(name, (0.0085 * min(k, 1.4), 0.074 * k, 0.152 * k), (-0.03 * s, cy, cz), 0.0035 * k, segments=5)
    set_material(shell, "Phone")
    parts.append(shell)
    sx = -(0.03 + 0.0048 * min(k, 1.4)) * s
    screen = rounded_box("screen", (0.0012, 0.068 * k, 0.146 * k), (sx, cy, cz), 0.0006, segments=2)
    set_material(screen, screen_mat)
    parts.append(screen)
    bump = rounded_box("bump", (0.0022, 0.03, 0.03), (-(0.03 - 0.0053 * min(k, 1.4)) * s, cy - 0.018 * k, cz - 0.058 * k), 0.001, segments=3)
    set_material(bump, "Phone")
    parts.append(bump)
    for dy, dz in ((0.0, 0.007), (-0.012, 0.007), (-0.006, -0.006)):
        lens = primitive("cylinder", vertices=16, radius=0.0045, depth=0.003, location=(-(0.03 - 0.0068 * min(k, 1.4)) * s, cy - 0.018 * k + dy, cz - 0.058 * k + dz), rotation=(0, math.radians(90), 0))
        set_material(lens, "Glass")
        parts.append(lens)
    bone = "hand.R" if s > 0 else "hand.L"
    for p in parts:
        bake(p)
        p.data.transform(place)
        attach(p, None, bone)


# ================================================================ props

def cap():
    """Baseball cap, worn backwards."""
    crown = primitive("uv_sphere", segments=24, ring_count=12, radius=1, location=HEAD_C + Vector((0, -0.01, HEAD_R.z * 0.42)))
    crown.scale = (HEAD_R.x * 1.06, HEAD_R.y * 1.04, HEAD_R.z * 0.66)
    attach(crown, "Accent", "head")
    brim = rounded_box("brim", (0.14, 0.085, 0.01), HEAD_C + Vector((0, -HEAD_R.y - 0.02, HEAD_R.z * 0.4)), 0.004, rot=(math.radians(-8), 0, 0))
    attach(brim, "Accent", "head")
    button = primitive("uv_sphere", segments=10, ring_count=6, radius=0.012, location=HEAD_C + Vector((0, -0.01, HEAD_R.z * 1.07)))
    attach(button, "Accent", "head")


def airpods():
    for s in (1, -1):
        bud = primitive("uv_sphere", segments=12, ring_count=8, radius=1, location=HEAD_C + Vector((s * HEAD_R.x * 1.02, 0.02, -0.01)))
        bud.scale = (0.011, 0.013, 0.013)
        attach(bud, "Midsole", "head")
        stem = primitive("cylinder", vertices=8, radius=0.0045, depth=0.035, location=HEAD_C + Vector((s * HEAD_R.x * 1.03, 0.028, -0.03)))
        attach(stem, "Midsole", "head")


def headphones():
    """Oversized over-ears: a band over the top, big cups on the sides."""
    band_r = HEAD_R.x * 1.12
    arc = primitive("torus", major_radius=band_r, minor_radius=0.014, major_segments=40, minor_segments=8, location=HEAD_C + Vector((0, 0, HEAD_R.z * 0.12)), rotation=(0, math.radians(90), math.radians(90)))
    arc.scale = (1, 1, HEAD_R.z / HEAD_R.x)
    attach(arc, "Phone", "head")
    for s in (1, -1):
        cup = primitive("cylinder", vertices=24, radius=0.06 * HEAD_SCALE, depth=0.045, location=HEAD_C + Vector((s * (HEAD_R.x + 0.012), 0.005, -0.005)), rotation=(0, math.radians(90), 0))
        add_modifier(cup, "BEVEL", width=0.012, segments=3, limit_method="NONE")
        attach(cup, "Accent", "head")


def fannypack():
    """Worn crossbody, high on the chest, the way it's done now."""
    pack = rounded_box("pack", (0.21, 0.07, 0.085), (0.02, 0.2, 1.29), 0.03, rot=(0, math.radians(-22), 0))
    add_modifier(pack, "SUBSURF", levels=1)
    attach(pack, "Accent", "chest")
    zip_ = rounded_box("zip", (0.18, 0.006, 0.008), (0.02, 0.237, 1.305), 0.003, rot=(0, math.radians(-22), 0))
    attach(zip_, "Metal", "chest")
    strap = skin("strap", [(0.12, 0.18, 1.33), (0.16, 0.08, 1.46), (0.1, -0.1, 1.44), (-0.12, -0.16, 1.22), (-0.14, 0.05, 1.12), (-0.08, 0.19, 1.25)],
                 [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5)], [(0.018, 0.005)] * 6)
    attach(strap, "Outsole", "chest")


def hood_down():
    """The hood lies flat on the upper back, with a ribbed collar at the neck."""
    hood = primitive("uv_sphere", segments=20, ring_count=12, radius=1, location=(0, -0.13, 1.43))
    hood.scale = (0.15, 0.05, 0.11)
    add_modifier(hood, "DISPLACE", texture=folds, strength=0.006, mid_level=0.5, texture_coords="GLOBAL")
    attach(hood, "Hoodie", "chest")
    attach(band("collar", (0, -0.01, 1.49), (0, 0, 1), 0.095, 0.088, 0.045, ribs=24, rib=0.03), "HoodieDark", blend("chest", "neck", 2, 1.46, 1.52))


def glasses():
    """Reading glasses, pushed up onto the head and forgotten there."""
    top = HEAD_C + Vector((0, HEAD_R.y * 0.55, HEAD_R.z * 0.82))
    for s in (1, -1):
        lens = primitive("torus", major_radius=0.026, minor_radius=0.004, major_segments=20, minor_segments=6, location=top + Vector((s * 0.034, 0, 0)), rotation=(math.radians(-55), 0, 0))
        attach(lens, "Phone", "head")
        arm = primitive("cylinder", vertices=6, radius=0.003, depth=0.12, location=top + Vector((s * 0.062, -0.055, -0.01)), rotation=(math.radians(90 - 20), 0, 0))
        attach(arm, "Phone", "head")
    bridge = primitive("cylinder", vertices=6, radius=0.003, depth=0.018, location=top, rotation=(0, math.radians(90), 0))
    attach(bridge, "Phone", "head")


def belt():
    """A tied fabric belt (bathrobe, trench coat) with a knot at the front."""
    # The subdivided skin body comes out a little inside its skin radii.
    rx, ry = 0.19 * (1 + (BELLY - 1) * 0.2) * 0.9, 0.14 * BELLY * 0.9
    attach(band("belt", (0, 0, 1.02), (0, 0, 1), rx, ry, 0.045, ribs=30, rib=0.0), "HoodieDark", "spine")
    knot = rounded_box("knot", (0.05, 0.035, 0.04), (0.04, ry + 0.012, 1.02), 0.012)
    attach(knot, "HoodieDark", "spine")
    for dx, rot in ((0.03, -12), (0.055, 10)):
        tail = rounded_box("tail", (0.026, 0.012, 0.14), (dx, ry + 0.014, 0.95), 0.005, rot=(0, math.radians(rot), 0))
        attach(tail, "HoodieDark", "spine")


def shawl():
    """Bathrobe lapels: a thick rolled collar crossing into a V on the chest."""
    for s in (1, -1):
        pts = [(s * 0.07, -0.06, 1.5), (s * 0.1, 0.05, 1.48), (s * 0.08, 0.14, 1.36), (s * 0.02, 0.17, 1.2), (-s * 0.03, 0.165, 1.1)]
        lapel = skin("lapel", pts, [(0, 1), (1, 2), (2, 3), (3, 4)], [(0.03, 0.016)] * 5)
        add_modifier(lapel, "SUBSURF", levels=1)
        attach(lapel, "HoodieDark", "chest")


def collar_up():
    """Trench coat collar, popped, hiding the neck."""
    attach(band("collar", (0, -0.015, 1.5), (0, 0.15, 1), 0.105, 0.1, 0.1, ribs=16, rib=0.0, bulge=0.12), "HoodieDark", blend("chest", "neck", 2, 1.46, 1.53))


def beanie():
    hat = primitive("uv_sphere", segments=24, ring_count=12, radius=1, location=HEAD_C + Vector((0, -0.015, HEAD_R.z * 0.45)))
    hat.scale = (HEAD_R.x * 1.04, HEAD_R.y * 1.02, HEAD_R.z * 0.68)
    attach(hat, "Accent", "head")
    attach(band("cuff", HEAD_C + Vector((0, -0.015, HEAD_R.z * 0.42)), (0, 0.25, 1), HEAD_R.x * 1.05, HEAD_R.y * 1.03, 0.035, ribs=28, rib=0.03), "Accent", "head")


def hair_sphere(loc, scale):
    h = primitive("uv_sphere", segments=16, ring_count=10, radius=1, location=loc)
    h.scale = scale
    attach(h, "Hair", "head")


def scalp():
    """A hair cap over the top and back of the head."""
    # Set back so the face void stays clear of it.
    hair_sphere(HEAD_C + Vector((0, -0.03, HEAD_R.z * 0.14)), (HEAD_R.x * 1.05, HEAD_R.y * 1.0, HEAD_R.z * 0.97))


def bun():
    scalp()
    hair_sphere(HEAD_C + Vector((0, -0.03, HEAD_R.z * 1.05)), (0.06, 0.06, 0.05))


def ponytail():
    scalp()
    tail = skin("ponytail", [tuple(HEAD_C + Vector((0, -HEAD_R.y * 0.8, HEAD_R.z * 0.75))), tuple(HEAD_C + Vector((0, -HEAD_R.y * 1.35, HEAD_R.z * 0.35))), tuple(HEAD_C + Vector((0, -HEAD_R.y * 1.45, -HEAD_R.z * 0.4)))],
                [(0, 1), (1, 2)], [(0.035, 0.03), (0.04, 0.035), (0.015, 0.015)])
    add_modifier(tail, "SUBSURF", levels=1)
    attach(tail, "Hair", "head")


def selfie():
    """A selfie stick out of the right fist, the phone on the end facing back."""
    stick = primitive("cylinder", vertices=8, radius=0.008, depth=0.34, location=(-0.03, 0.012, -0.22))
    bake(stick)
    stick.data.transform(place_r)
    attach(stick, "Metal", "hand.R")
    phone(place_r, reach=0.3)


def ringlight():
    """A ring light on a pole out of a small backpack. Always on."""
    attach(rounded_box("backpack", (0.22, 0.1, 0.26), (0, -0.2, 1.24), 0.04), "HoodieDark", "chest")
    pole = primitive("cylinder", vertices=8, radius=0.01, depth=0.55, location=(0, -0.26, 1.58))
    attach(pole, "Metal", "chest")
    ring = primitive("torus", major_radius=0.17, minor_radius=0.018, major_segments=40, minor_segments=8, location=(0, -0.28, 1.86), rotation=(math.radians(80), 0, 0))
    attach(ring, "ScreenRing", "chest")


def matcha():
    """Iced matcha in the left hand: clear-ish cup, green inside, a straw."""
    parts = []
    cup = primitive("cylinder", vertices=18, radius=0.034, depth=0.11, location=(0.035, 0.01, -0.1))
    set_material(cup, "Matcha")
    parts.append(cup)
    lid = primitive("cylinder", vertices=18, radius=0.037, depth=0.012, location=(0.035, 0.01, -0.16))
    set_material(lid, "Midsole")
    parts.append(lid)
    straw = primitive("cylinder", vertices=6, radius=0.005, depth=0.08, location=(0.035, 0.015, -0.2))
    set_material(straw, "Midsole")
    parts.append(straw)
    for p in parts:
        bake(p)
        p.data.transform(place_l)
        attach(p, None, "hand.L")


def yogamat():
    """A rolled yoga mat slung across the back. Unrolled once."""
    mat = primitive("cylinder", vertices=20, radius=0.055, depth=0.6, location=(0, -0.2, 1.25), rotation=(0, math.radians(60), 0))
    add_modifier(mat, "BEVEL", width=0.01, segments=2, limit_method="NONE")
    attach(mat, "Accent", "chest")


PROPS = {
    "phone": lambda: phone(place_r),
    "phone.L": lambda: phone(place_l, s=-1, screen_mat="ScreenAlt"),
    "phone.L.news": lambda: phone(place_l, s=-1, screen_mat="ScreenNews"),
    "phone.L.news2": lambda: phone(place_l, s=-1, screen_mat="ScreenNews", fan=0.05, reach=0.02),
    "tablet": lambda: phone(place_r, size=2.1, name="tablet"),
    "tablet.far": lambda: phone(place_r, size=1.8, name="tablet"),
    "glasses": glasses,
    "belt": belt,
    "shawl": shawl,
    "collar.up": collar_up,
    "beanie": beanie,
    "bun": bun,
    "ponytail": ponytail,
    "selfie": selfie,
    "ringlight": ringlight,
    "matcha": matcha,
    "yogamat": yogamat,
    "cap": cap,
    "airpods": airpods,
    "headphones": headphones,
    "fannypack": fannypack,
    "hood.down": hood_down,
}
for prop in C["props"]:
    PROPS[prop]()


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


# Screen holds (arm aims). scroll: elbows in, forearms forward, phone at chest
# height, screen tilted up to the face; left hand hovers under it. double: a
# phone in each hand, spread apart. tablet: hands wider and lower, the left
# one under the far edge.
HOLDS = {
    "scroll": hold((0.12, 0.3, -1), (-0.35, 1, 0.3), (-0.2, 1, 0.75), (0.1, 0.25, -1), (-0.55, 1, 0.2), (-0.5, 1, 0.3)),
    "double": hold((0.2, 0.3, -1), (-0.15, 1, 0.35), (0.0, 1, 0.8), (0.2, 0.3, -1), (-0.15, 1, 0.35), (0.0, 1, 0.8)),
    "tablet": hold((0.14, 0.35, -1), (-0.3, 1, 0.15), (-0.3, 1, 0.55), (0.14, 0.3, -1), (-0.45, 1, 0.1), (-0.4, 1, 0.4)),
    # far: arms out straight, tablet at arm's length (reading glasses on the head).
    "far": hold((0.1, 0.8, -0.6), (-0.15, 1, 0.1), (-0.25, 1, 0.45), (0.1, 0.75, -0.65), (-0.35, 1, 0.05), (-0.45, 1, 0.3)),
    # selfie: right arm up and forward with the stick; left arm loose.
    "selfie": hold((0.3, 0.8, 0.05), (-0.1, 1, 0.55), (-0.25, 1, 0.35), (0.12, 0.04, -1), (0.07, 0.14, -1), (0.04, 0.12, -1)),
    # sip: phone in the right hand, the drink raised in the left.
    "sip": hold((0.12, 0.3, -1), (-0.35, 1, 0.3), (-0.2, 1, 0.75), (0.15, 0.3, -1), (-0.1, 1, 0.6), (0.0, 0.5, 1)),
}
HOLD = HOLDS[C["hold"]]
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
print(f"runner: {CHAR}")
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
