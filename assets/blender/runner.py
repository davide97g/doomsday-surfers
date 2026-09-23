# Builds the runner hero asset: a faceless hoodie figure hunched over a
# glowing phone, skinned to a small rig, with its animations.
#
#   blender -b -P assets/blender/runner.py -- public/assets/runner.glb [preview_dir]
#
# Everything is procedural so the asset can be rebuilt (and ported) from this
# file alone. Blender is Z-up and the runner faces +Y; the glTF exporter turns
# that into Y-up facing -Z, which is the direction the game runs.
#
# Animations (glTF clip names): run, idle, jump, roll, present.
# Material names the game looks up: Screen (phone light), Hoodie.

import math
import os
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
OUT = argv[0] if argv else "public/assets/runner.glb"
PREVIEW = argv[1] if len(argv) > 1 else None

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.fps = 30


# ---------------------------------------------------------------- materials

def material(name, rgb, rough=0.75, emit=None, strength=0.0, metal=0.0):
    m = bpy.data.materials.new(name)
    if hasattr(m, "use_nodes"):
        m.use_nodes = True
    p = m.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (*rgb, 1)
    p.inputs["Roughness"].default_value = rough
    p.inputs["Metallic"].default_value = metal
    if emit:
        p.inputs["Emission Color"].default_value = (*emit, 1)
        p.inputs["Emission Strength"].default_value = strength
    m.diffuse_color = (*rgb, 1)  # workbench preview colour
    return m


MATS = {
    "Hoodie": material("Hoodie", (0.15, 0.13, 0.25)),
    "HoodieDark": material("HoodieDark", (0.07, 0.06, 0.12)),
    "Pants": material("Pants", (0.1, 0.09, 0.13)),
    "Shoe": material("Shoe", (0.85, 0.84, 0.88), rough=0.5),
    "Sole": material("Sole", (0.3, 0.28, 0.34)),
    "Void": material("Void", (0.005, 0.004, 0.008), rough=1.0),
    "Hand": material("Hand", (0.16, 0.14, 0.18)),
    "String": material("String", (0.92, 0.9, 0.95)),
    "Phone": material("Phone", (0.04, 0.04, 0.05), rough=0.3, metal=0.4),
    "Screen": material("Screen", (0.6, 0.85, 1.0), rough=0.2, emit=(0.6, 0.85, 1.0), strength=6.0),
}


# ---------------------------------------------------------------- parts

PARTS = []


def bake(obj):
    """Apply modifiers and transform, returning a plain mesh object."""
    dg = bpy.context.evaluated_depsgraph_get()
    mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(dg))
    mesh.transform(obj.matrix_world)
    baked = bpy.data.objects.new(obj.name, mesh)
    scene.collection.objects.link(baked)
    bpy.data.objects.remove(obj)
    return baked


def part(kind, bone, mat, loc, scale=(1, 1, 1), rot=(0, 0, 0), subsurf=1, cut=None, shape=None, weights=None, **kw):
    """One body part. `bone` gets full weight unless `weights(co)` returns {bone: w} per vertex."""
    if kind == "sphere":
        bpy.ops.mesh.primitive_uv_sphere_add(segments=kw.get("segments", 16), ring_count=kw.get("rings", 10), radius=1)
    elif kind == "cyl":
        bpy.ops.mesh.primitive_cylinder_add(vertices=kw.get("segments", 12), radius=1, depth=1)
    elif kind == "cube":
        bpy.ops.mesh.primitive_cube_add(size=1)
    obj = bpy.context.active_object
    if shape:
        shape(obj.data)
    obj.location = loc
    obj.scale = scale
    obj.rotation_euler = rot
    if subsurf:
        mod = obj.modifiers.new("sub", "SUBSURF")
        mod.levels = subsurf
    if cut is not None:
        mod = obj.modifiers.new("cut", "BOOLEAN")
        mod.operation = "DIFFERENCE"
        mod.object = cut
    obj.data.materials.append(MATS[mat])
    obj = bake(obj)
    if weights is None:
        vg = obj.vertex_groups.new(name=bone)
        vg.add(range(len(obj.data.vertices)), 1.0, "REPLACE")
    else:
        groups = {}
        for v in obj.data.vertices:
            for name, w in weights(v.co).items():
                if w <= 0:
                    continue
                if name not in groups:
                    groups[name] = obj.vertex_groups.new(name=name)
                groups[name].add([v.index], w, "REPLACE")
    for poly in obj.data.polygons:
        poly.use_smooth = True
    PARTS.append(obj)
    return obj


def taper(r0, r1, length):
    """Shape a unit cylinder (z in -0.5..0.5) into a tube: radius r0 at the top, r1 at the bottom."""

    def fn(mesh):
        for v in mesh.vertices:
            r = r0 + (r1 - r0) * (0.5 - v.co.z)
            v.co = Vector((v.co.x * r, v.co.y * r, v.co.z * length))

    return fn


def limb(bone, mat, top, bottom, r0, r1):
    """A tapered, rounded tube from `top` to `bottom`."""
    top, bottom = Vector(top), Vector(bottom)
    d = top - bottom
    rot = Vector((0, 0, 1)).rotation_difference(d.normalized()).to_euler()
    # Subdivision rounds the caps and shrinks the tube a little; compensate.
    return part("cyl", bone, mat, (top + bottom) / 2, rot=rot, shape=taper(r0 * 1.15, r1 * 1.15, d.length * 1.1))


def hoodie_shape(mesh):
    """Unit cube to a hoodie body: wider shoulders, slightly narrower hem."""
    for v in mesh.vertices:
        t = v.co.z + 0.5  # 0 at hem, 1 at shoulders
        v.co.x *= 0.9 + 0.2 * t
        v.co.y *= 1.0 - 0.1 * t


def spine_to_chest(co):
    t = min(1.0, max(0.0, (co.z - 1.22) / 0.2))
    return {"spine": 1 - t, "chest": t}


# Pelvis and torso: one soft, boxy hoodie body that bends between spine and chest.
part("sphere", "hips", "Pants", (0, 0, 0.95), (0.19, 0.13, 0.12))
part("cube", "spine", "Hoodie", (0, -0.01, 1.22), (0.5, 0.32, 0.62), subsurf=2, shape=hoodie_shape, weights=spine_to_chest)
part("cube", "spine", "HoodieDark", (0, 0.145, 1.06), (0.24, 0.05, 0.13), subsurf=2)  # kangaroo pocket
part("cyl", "spine", "HoodieDark", (0, -0.01, 0.95), (0.22, 0.155, 0.05), subsurf=1)  # hem
# Hood fabric bunched behind the neck, so the back view reads as a hood, not a helmet.
part("sphere", "chest", "Hoodie", (0, -0.12, 1.52), (0.17, 0.1, 0.1))

# Hood with a black void where the face should be.
bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=10, radius=0.15, location=(0, 0.14, 1.63))
face_cut = bpy.context.active_object
face_cut.scale = (1, 0.9, 1.1)
part("sphere", "head", "Hoodie", (0, -0.02, 1.64), (0.19, 0.2, 0.21), subsurf=1, cut=face_cut, segments=20, rings=14)
bpy.data.objects.remove(face_cut)
part("sphere", "head", "Void", (0, 0.02, 1.63), (0.15, 0.15, 0.17))
# Drawstrings.
for x in (-0.05, 0.05):
    part("cyl", "chest", "String", (x, 0.13, 1.38), (0.008, 0.008, 0.16), subsurf=0, segments=6)

# Arms (hoodie sleeves) and hands.
for side, s in (("L", 1), ("R", -1)):
    limb(f"upperArm.{side}", "Hoodie", (s * 0.25, -0.02, 1.47), (s * 0.26, -0.02, 1.16), 0.07, 0.06)
    limb(f"forearm.{side}", "Hoodie", (s * 0.26, -0.02, 1.17), (s * 0.26, -0.02, 0.92), 0.062, 0.055)
    part("sphere", f"forearm.{side}", "Hand", (s * 0.26, -0.01, 0.88), (0.045, 0.04, 0.055))
    limb(f"thigh.{side}", "Pants", (s * 0.105, 0, 0.97), (s * 0.1, 0, 0.5), 0.115, 0.09)
    limb(f"shin.{side}", "Pants", (s * 0.1, 0, 0.54), (s * 0.1, 0, 0.12), 0.09, 0.075)
    part("cube", f"shin.{side}", "Shoe", (s * 0.1, 0.05, 0.08), (0.14, 0.3, 0.13), subsurf=2)
    part("cube", f"shin.{side}", "Sole", (s * 0.1, 0.05, 0.025), (0.145, 0.31, 0.045), subsurf=1)

# The phone, in the right hand. At rest the screen faces +Y; with the forearm
# raised forward it tilts up toward the hood.
part("cube", "forearm.R", "Phone", (-0.2, 0.01, 0.84), (0.1, 0.018, 0.18), subsurf=0)
part("cube", "forearm.R", "Screen", (-0.2, 0.021, 0.84), (0.088, 0.004, 0.165), subsurf=0)

# Join into one mesh (one skinned draw per material).
body = PARTS[0]
with bpy.context.temp_override(active_object=body, selected_editable_objects=PARTS, object=body):
    bpy.ops.object.join()
body.name = "Runner"
body.data.name = "Runner"


# ---------------------------------------------------------------- rig

arm_data = bpy.data.armatures.new("RunnerRig")
rig = bpy.data.objects.new("RunnerRig", arm_data)
scene.collection.objects.link(rig)
bpy.context.view_layer.objects.active = rig
bpy.ops.object.mode_set(mode="EDIT")

BONES = {
    "hips": ((0, 0, 0.95), (0, 0, 1.1), None),
    "spine": ((0, 0, 1.1), (0, 0, 1.33), "hips"),
    "chest": ((0, 0, 1.33), (0, 0, 1.5), "spine"),
    "head": ((0, 0, 1.5), (0, 0, 1.82), "chest"),
}
for side, s in (("L", 1), ("R", -1)):
    BONES[f"upperArm.{side}"] = ((s * 0.25, -0.02, 1.46), (s * 0.26, -0.02, 1.17), "chest")
    BONES[f"forearm.{side}"] = ((s * 0.26, -0.02, 1.17), (s * 0.26, -0.02, 0.86), f"upperArm.{side}")
    BONES[f"thigh.{side}"] = ((s * 0.1, 0, 0.94), (s * 0.1, 0, 0.51), "hips")
    BONES[f"shin.{side}"] = ((s * 0.1, 0, 0.51), (s * 0.1, 0, 0.06), f"thigh.{side}")

for name, (head, tail, parent) in BONES.items():
    b = arm_data.edit_bones.new(name)
    b.head, b.tail = head, tail
    b.roll = 0
    if parent:
        b.parent = arm_data.edit_bones[parent]
        b.use_connect = False

# Remember each bone's local axes (in rest pose) to pose by intent below.
AXES = {b.name: (b.x_axis.copy(), b.z_axis.copy()) for b in arm_data.edit_bones}
bpy.ops.object.mode_set(mode="OBJECT")

body.parent = rig
mod = body.modifiers.new("rig", "ARMATURE")
mod.object = rig


# ---------------------------------------------------------------- posing

FWD = Vector((0, 1, 0))


def pose(pb, fwd=0.0, side=0.0, towards_center=True):
    """Rotate a bone so its tail swings forward by `fwd` degrees and toward
    the body's centre line by `side` degrees, whatever the bone's local axes."""
    x_axis, z_axis = AXES[pb.name]
    # Rotating about local X moves the tail toward local +Z.
    s_fwd = 1 if z_axis.dot(FWD) >= 0 else -1
    # Rotating about local Z moves the tail toward local -X.
    centre = Vector((-math.copysign(1, pb.bone.head_local.x) if pb.bone.head_local.x else 0, 0, 0))
    s_side = 1 if (-x_axis).dot(centre) >= 0 else -1
    pb.rotation_mode = "XYZ"
    pb.rotation_euler = (math.radians(fwd) * s_fwd, 0, math.radians(side) * s_side)


def key(frame, poses, hips_y=0.0):
    for pb in rig.pose.bones:
        f, sd = poses.get(pb.name, (0, 0))
        pose(pb, f, sd)
        pb.keyframe_insert("rotation_euler", frame=frame)
    hips = rig.pose.bones["hips"]
    hips.location = (0, hips_y, 0)  # bone-local: Y runs along the bone, i.e. up
    hips.keyframe_insert("location", frame=frame)


# The phone hold, shared by most animations.
HOLD = {
    "upperArm.L": (38, 20),
    "upperArm.R": (38, 22),
    "forearm.L": (92, 12),
    "forearm.R": (88, 10),
}
HUNCH = {"spine": (12, 0), "chest": (10, 0), "head": (28, 0)}


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
    p = dict(HOLD)
    p.update(HUNCH)
    p["spine"] = (16, 0)
    p["thigh.L"] = (48 * math.sin(ph), 0)
    p["thigh.R"] = (-48 * math.sin(ph), 0)
    p["shin.L"] = (-(12 + 70 * max(0.0, math.cos(ph))), 0)
    p["shin.R"] = (-(12 + 70 * max(0.0, -math.cos(ph))), 0)
    bounce = 3 * math.sin(2 * ph)
    p["upperArm.L"] = (HOLD["upperArm.L"][0] + bounce, HOLD["upperArm.L"][1])
    p["upperArm.R"] = (HOLD["upperArm.R"][0] + bounce, HOLD["upperArm.R"][1])
    key(f, p, hips_y=0.035 * abs(math.cos(ph)) - 0.02)

# idle: standing, thumb-scrolling, 60 frames.
action("idle")
for f in range(0, 61, 10):
    ph = 2 * math.pi * f / 60
    p = dict(HOLD)
    p.update(HUNCH)
    p["chest"] = (10 + 2 * math.sin(ph), 0)
    p["head"] = (30 + 3 * math.sin(ph * 2), 0)
    p["forearm.R"] = (88 + 4 * max(0.0, math.sin(ph * 3)), 10)  # scroll flick
    key(f, p, hips_y=-0.005 * math.sin(ph))

# jump: tuck, held.
action("jump")
for f in (0, 8):
    p = dict(HOLD)
    p.update(HUNCH)
    p["spine"] = (20, 0)
    p["thigh.L"] = (70, 0)
    p["shin.L"] = (-95, 0)
    p["thigh.R"] = (-15, 0)
    p["shin.R"] = (-60, 0)
    key(f, p)

# roll: curled into a ball, still looking at the phone.
action("roll")
for f in (0, 8):
    p = dict(HOLD)
    p["spine"] = (48, 0)
    p["chest"] = (30, 0)
    p["head"] = (25, 0)
    p["thigh.L"] = (105, 0)
    p["thigh.R"] = (100, 0)
    p["shin.L"] = (-135, 0)
    p["shin.R"] = (-135, 0)
    p["forearm.L"] = (110, 14)
    p["forearm.R"] = (106, 12)
    key(f, p, hips_y=-0.38)

# present: dopamine is gone. The arms drop, the head comes up. 36 frames.
action("present")
for f, k in ((0, 0.0), (12, 0.45), (24, 0.85), (36, 1.0)):
    def lerp(a, b):
        return a + (b - a) * k

    p = {
        "upperArm.L": (lerp(38, 4), lerp(20, 4)),
        "upperArm.R": (lerp(38, 4), lerp(22, 4)),
        "forearm.L": (lerp(92, 8), lerp(12, 0)),
        "forearm.R": (lerp(88, 10), lerp(10, 0)),
        "spine": (lerp(12, 0), 0),
        "chest": (lerp(10, -2), 0),
        "head": (lerp(28, -12), 0),
    }
    key(f, p)

rig.animation_data.action = bpy.data.actions["idle"]


# ---------------------------------------------------------------- export

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
)
print(f"runner: wrote {OUT} ({os.path.getsize(OUT) // 1024} KB, {len(body.data.vertices)} verts)")


# ---------------------------------------------------------------- preview

if PREVIEW:
    os.makedirs(PREVIEW, exist_ok=True)
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "MATERIAL"
    scene.render.resolution_x = 512
    scene.render.resolution_y = 640
    cam_data = bpy.data.cameras.new("cam")
    cam_data.lens = 50
    cam = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    views = {"side": ((4.2, 0.4, 1.1), (0, 0, 0.95)), "back": ((0.9, -3.6, 2.1), (0, 0, 1.0))}
    for act_name, frame in (("idle", 0), ("run", 0), ("run", 4), ("jump", 0), ("roll", 0), ("present", 36)):
        rig.animation_data.action = bpy.data.actions[act_name]
        scene.frame_set(frame)
        for view, (loc, target) in views.items():
            cam.location = loc
            direction = Vector(target) - Vector(loc)
            cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
            scene.render.filepath = os.path.join(PREVIEW, f"{act_name}{frame}_{view}.png")
            bpy.ops.render.render(write_still=True)
    print(f"runner: previews in {PREVIEW}")
