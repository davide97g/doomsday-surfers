# Builds a realistic doomscroller from MPFB2 (MakeHuman for Blender, CC0
# output): a human with per-character proportions, a black-mirror void where
# the face should be, clothes, hair, a detailed phone (or two, or a tablet),
# the character's props, the MPFB `game_engine` rig and every animation clip
# of the contract (docs/assets-v2.md, "Characters").
#
#   blender -b -P assets/blender/human.py -- --character goblin [--out x.glb] [--preview dir]
#
# `bun run assets` builds all ten into public/assets/characters/<id>.glb.
#
# Blender is Z-up; MakeHuman builds the body facing -Y, so everything is turned
# to face +Y (the game's forward after the glTF Y-up conversion) before any
# garment, prop or clip is authored. +X is the character's right (`_r` bones).
#
# Pipeline, per character:
#   body      MPFB base mesh + macros (+ extra targets), lifted onto its shoe
#             soles, helpers removed, the skin under clothes cut away, the
#             face oval replaced by a smooth glossy dome (material `Void`)
#   clothes   MPFB system clothes and shoes (suits split into pieces,
#             recoloured over CC0 fabric sets, MPFB normal/AO maps kept) and
#             shell garments grown from the body (hoodie + parametric hood,
#             hood-down, cropped sweatshirt, muscle tee, polo collar, joggers,
#             pyjamas): faces picked by the rig's weights, offset, smoothed
#             until the anatomy is gone, kept off the skin, with rib bands,
#             pocket and drawstrings; a finer copy settles in a short cloth sim
#             and its folds bake high->low into the garment's normal map
#   props     phones (bevelled metal band, glass back, camera plateau, lenses,
#             buttons, emissive `Screen*`), tablet, selfie stick, ring lights,
#             caps, beanie, headphones, headset, AirPods, glasses, fanny pack,
#             tie, lanyard, mug, matcha, yoga mat, halo, mouse jiggler
#   atlas     everything but skin, hair, screens and the void baked into one
#             1024 atlas (albedo, normal, ORM, emissive when something glows)
#             via lib/bake.py; `Shoes` is the same atlas under its own name
#   rig       MPFB game_engine (UE names) with MPFB's weights; garments take
#             the body's weights, props are weighted 100 % to one bone
#   clips     authored procedurally at 30 fps: IK feet on designed foot
#             trajectories, IK arms holding the screen in front of the void,
#             IK thumbs on the screen, FK torso/head/fingers; every frame is
#             baked to plain keys (visual keying) and the constraints removed
#   export    lib/export.py (glb + gltf-transform meshopt/KTX2), under 35k
#             triangles (heaviest garments decimated if needed), 6 materials
#             and 1.8 MB (the normal atlas steps down to 768/512 if needed)

import math
import os
import sys
import time

import bmesh
import bpy
from mathutils import Euler, Matrix, Quaternion, Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

_d = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _d if os.path.isdir(os.path.join(_d, "lib")) else os.path.dirname(_d))
import lib  # noqa: E402
from lib import mat  # noqa: E402

T0 = time.time()
ROOT = lib.ROOT


def log(*parts):
    print("human:", *parts, flush=True)


CHAR = lib.arg("character", "goblin")
OUT = lib.arg("out", os.path.join(ROOT, "public", "assets", "characters", f"{CHAR}.glb"))
PREVIEW = lib.arg("preview")
STAGE = lib.arg("stage", "all")  # debug: stop after "clothes" or "anim"; "grip" = fast grip check + close-ups
FAST = lib.flag("fast")  # fewer bake samples, for iteration


# ================================================================ MPFB

def _mpfb(module, name):
    import importlib
    for pkg in ("bl_ext.blender_org.mpfb", "bl_ext.user_default.mpfb", "mpfb"):
        try:
            return getattr(importlib.import_module(f"{pkg}.services.{module}"), name)
        except ImportError:
            continue
    raise ImportError("MPFB2 is not installed/enabled (scripts/setup-assets.sh)")


HumanService = _mpfb("humanservice", "HumanService")
TargetService = _mpfb("targetservice", "TargetService")
LocationService = _mpfb("locationservice", "LocationService")
MPFB_DATA = LocationService.get_user_data()
MPFB_SYS = LocationService.get_mpfb_data()
if not os.path.isdir(os.path.join(MPFB_DATA, "clothes")):
    raise SystemExit(f"human: MakeHuman system assets missing in {MPFB_DATA} (run scripts/setup-assets.sh)")


def asset(rel):
    p = os.path.join(MPFB_DATA, rel)
    if not os.path.exists(p):
        raise FileNotFoundError(p)
    return p


# ================================================================ cast
#
# Art direction ported from runner.py's CHARACTERS (outfit, props, colours,
# how the screen is held) and the v2 plan (docs/assets-v2.md).
#
# body:     MPFB macros (0..1). age: 0 = 1 y, 0.1875 = 11 y, 0.5 = 25 y, 1 = 90 y.
# targets:  extra MPFB targets {path under data/targets: weight}.
# skin:     MPFB skin (skins/<id>/<id>.mhmat).
# hair:     (MPFB hair id, tint) or None.
# wear:     garments, in order (see GARMENTS).
# shoes:    (MPFB shoes id, tint) - the `Shoes` material.
# props:    see PROPS.
# hold:     how the arms carry the screen (see HOLDS).

def _age(years):
    if years < 11:
        return (years - 1) / 10 * 0.1875
    if years < 25:
        return 0.1875 + (years - 11) / 14 * 0.3125
    return 0.5 + (years - 25) / 65 * 0.5


RACE = {
    "white": dict(caucasian=0.9, african=0.05, asian=0.05),
    "black": dict(caucasian=0.1, african=0.85, asian=0.05),
    "asian": dict(caucasian=0.15, african=0.05, asian=0.8),
    "mixed": dict(caucasian=0.45, african=0.35, asian=0.2),
}

CHARACTERS = {
    "goblin": dict(  # Hoodie Goblin: craves Reels. Hood up, cinched, never leaves the house.
        body=dict(gender=1.0, age=_age(19), muscle=0.35, weight=0.32, height=0.62, proportions=0.55), race="white",
        skin="young_caucasian_male", hair=None,
        wear=("hoodie.up", "joggers"), shoes=("shoes05", "#b8bcc8"),
        props=("phone",), hold="scroll",
        colours={"hoodie": "#3b3354", "rib": "#2b2540", "pants": "#1d1d24"},
        phone={"frame": "#2c2c31", "back": "#17171b"},
    ),
    "bro": dict(  # Grindset Bro: Notifications. Gym tee, backwards cap, a phone per hand.
        body=dict(gender=1.0, age=_age(27), muscle=0.92, weight=0.6, height=0.5, proportions=0.7), race="black",
        skin="young_african_male", hair=None,
        wear=("tee.muscle", "joggers"), shoes=("shoes05", "#f4f4f4"),
        props=("phone", "phone.L", "cap.back", "airpods", "fannypack"), hold="double", loose=1.1,
        colours={"tee": "#cfd0d6", "pants": "#1e1e22", "rib_pants": "#1a1a1d", "accent": "#ff5a05"},
        phone={"frame": "#c9a86a", "back": "#e8dcc8"},
    ),
    "kid": dict(  # iPad Kid: Likes. Hood down, big headphones, the tablet.
        body=dict(gender=0.7, age=_age(8.5), muscle=0.5, weight=0.45, height=0.55, proportions=0.5), race="asian",
        skin="young_asian_male", hair=("short02", "#1c140e"),
        wear=("hoodie.down", "joggers"), shoes=("shoes06", None),
        props=("tablet", "headphones"), hold="tablet", loose=1.0,
        colours={"hoodie": "#e8902a", "rib": "#c46d12", "pants": "#1a2a55", "accent": "#10c8e0"},
        phone={"frame": "#b9bcc2", "back": "#9fa4ad"},
    ),
    "uncle": dict(  # Outrage Uncle: Outrage. Polo, dad jeans, cap, reading glasses, tablet at arm's length.
        body=dict(gender=1.0, age=_age(56), muscle=0.4, weight=0.72, height=0.52, proportions=0.4), race="white",
        targets={"stomach/stomach-pregnant-incr": 0.45}, skin="middleage_caucasian_male", hair=("short04", "#9a9690"),
        mpfb=(dict(id="male_casualsuit04", part="top", key="polo", tex="cotton_jersey"),
              dict(id="male_casualsuit06", part="bottom", key="jeans", tex="denim_fabric")),
        wear=("polo.collar",), shoes=("shoes01", None),
        props=("tablet.far", "cap", "glasses"), hold="far",
        colours={"polo": "#5c1822", "jeans": "#7890b4", "cap": "#1f2a44", "accent": "#1f2a44"},
        phone={"frame": "#3a3a40", "back": "#2a2a2e"},
    ),
    "influencer": dict(  # Influencer: Likes. Cropped sweatshirt, cream jeans, ring light, selfie stick.
        body=dict(gender=0.0, age=_age(24), muscle=0.4, weight=0.4, height=0.62, proportions=0.75, cupsize=0.55),
        race="white", skin="young_caucasian_female", hair=("long01", "#e6c07a"),
        mpfb=(dict(id="female_casualsuit01", part="bottom", key="jeans", tex="denim_fabric"),),
        wear=("sweat.crop",), shoes=("shoes05", "#ffffff"),
        props=("selfie", "ringlight"), hold="selfie",
        colours={"hoodie": "#f06a9a", "rib": "#d85585", "jeans": "#e9e0d2", "accent": "#f06a9a"},
        phone={"frame": "#e7c3c9", "back": "#f3d7dc"},
    ),
    "wellness": dict(  # Wellness Girlie: no craving. Yoga set, matcha, a mat on the back.
        body=dict(gender=0.0, age=_age(29), muscle=0.55, weight=0.35, height=0.58, proportions=0.75), race="asian",
        skin="young_asian_female", hair=("ponytail01", "#2a1a10"),
        mpfb=(dict(id="female_sportsuit01", part="top", key="croptop", tex="cotton_jersey"),
              dict(id="female_sportsuit01", part="bottom", key="leggings", tex="cotton_jersey")),
        wear=(), shoes=("shoes05", "#f4f1ec"),
        props=("phone", "matcha", "yogamat"), hold="sip",
        colours={"croptop": "#86a58e", "leggings": "#6f5f93", "accent": "#8d6fb5"},
        phone={"frame": "#dcdad4", "back": "#c9d6c9"},
    ),
    "doomer": dict(  # News Doomer: Notifications. Beanie, jacket, three phones of breaking news.
        body=dict(gender=1.0, age=_age(33), muscle=0.4, weight=0.45, height=0.6, proportions=0.5), race="asian",
        skin="young_asian_male", hair=None,
        mpfb=(dict(id="male_casualsuit05", part="top", key="jacket", tex="denim_fabric"),
              dict(id="male_casualsuit06", part="bottom", key="jeans", tex="denim_fabric")),
        wear=(), shoes=("shoes03", None),
        props=("phone", "phone.L.news", "phone.L.news2", "beanie"), hold="double",
        colours={"jacket": "#6b5634", "jeans": "#2a2d34", "beanie": "#1a1a1e", "accent": "#1a1a1e"},
        phone={"frame": "#2c2c31", "back": "#1d1e22"},
    ),
    "manager": dict(  # Middle Manager (Work): shirt, tie, lanyard, the mug.
        body=dict(gender=1.0, age=_age(46), muscle=0.4, weight=0.66, height=0.52, proportions=0.45), race="black",
        targets={"stomach/stomach-pregnant-incr": 0.25}, skin="middleage_african_male", hair=("afro01", "#1e1812"),
        mpfb=(dict(id="male_casualsuit03", part="top", key="shirt", tex="stretch_poplin"),
              dict(id="male_casualsuit06", part="bottom", key="trousers", tex="stretch_poplin")),
        wear=(), shoes=("shoes01", "#4a2e20"),
        props=("phone", "mug", "tie", "lanyard"), hold="sip",
        colours={"shirt": "#b9cde6", "trousers": "#1b1c20", "tie": "#a3202f", "accent": "#a3202f"},
        phone={"frame": "#3a3a40", "back": "#24252a"},
    ),
    "remote": dict(  # Remote Worker (Work): hoodie over pyjamas, headset, slippers, mouse jiggler.
        body=dict(gender=0.0, age=_age(31), muscle=0.4, weight=0.52, height=0.5, proportions=0.5), race="black",
        skin="young_african_female", hair=("bob02", "#2a1c14"),
        wear=("hoodie.down", "pyjama"), shoes=("shoes02", "#e9a3b8"),
        props=("phone", "headset", "jiggler"), hold="scroll",
        colours={"hoodie": "#6e6e76", "rib": "#5a5a62", "pants": "#6f8fc9", "accent": "#f06010"},
        phone={"frame": "#8a8a90", "back": "#3a3c44"},
    ),
    "linkedin": dict(  # LinkedIn Lunatic (Work): navy suit, white sneakers, selfie ring, halo.
        body=dict(gender=1.0, age=_age(34), muscle=0.6, weight=0.45, height=0.56, proportions=0.8), race="white",
        skin="young_caucasian_male2", hair=("short04", "#4a3422"),
        mpfb=(dict(id="male_elegantsuit01", part="top", key="suit", two_tone=("#1b2440", "#f4f4f6")),
              dict(id="male_elegantsuit01", part="bottom", key="chinos", tex="cotton_jersey")),
        wear=(), shoes=("shoes05", "#fafafa"),
        props=("selfie.ring", "halo"), hold="selfie",
        colours={"chinos": "#bca98c", "accent": "#e8e8ec"},
        phone={"frame": "#1c1c20", "back": "#15161a"},
    ),
}
C = CHARACTERS[CHAR]


# ================================================================ helpers

scene = lib.reset_scene(30)


def link(obj):
    scene.collection.objects.link(obj)
    return obj


def select_only(*objs):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0] if objs else None


def tris(obj):
    return sum(len(p.vertices) - 2 for p in obj.data.polygons)


def centroid(obj, name, min_w=0.5):
    g = obj.vertex_groups[name].index
    pts = [v.co.copy() for v in obj.data.vertices if any(x.group == g and x.weight > min_w for x in v.groups)]
    return sum(pts, Vector()) / len(pts)


def delete_verts(obj, pred):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    doomed = [v for v in bm.verts if pred(v)]
    bmesh.ops.delete(bm, geom=doomed, context="VERTS")
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


def smoothstep(e0, e1, x):
    t = min(1.0, max(0.0, (x - e0) / (e1 - e0)))
    return t * t * (3 - 2 * t)


# ================================================================ body

def make_body():
    macro = TargetService.get_default_macro_info_dict()
    macro.update(C["body"])
    macro["race"] = dict(RACE[C.get("race", "white")])
    basemesh = HumanService.create_human(macro_detail_dict=macro, scale=0.1)
    targets = os.path.join(MPFB_SYS, "targets")
    for rel, w in C.get("targets", {}).items():
        TargetService.load_target(basemesh, os.path.join(targets, rel + ".target.gz"), weight=w)
    rig = HumanService.add_builtin_rig(basemesh, "game_engine")
    return basemesh, rig


def split_parts(obj):
    """Connected pieces of an MPFB suit as separate objects (top first)."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    seen, parts = set(), []
    for f in bm.faces:
        if f in seen:
            continue
        stack, isl = [f], []
        seen.add(f)
        while stack:
            g = stack.pop()
            isl.append(g.index)
            for e in g.edges:
                for h in e.link_faces:
                    if h not in seen:
                        seen.add(h)
                        stack.append(h)
        parts.append(isl)
    bm.free()
    me = obj.data
    zs = [sum(me.polygons[i].center.z for i in isl) / len(isl) for isl in parts]
    big = [p for p in parts if len(p) > 150]
    big.sort(key=lambda isl: -max(me.polygons[i].center.z for i in isl))
    return big, parts


def keep_faces(obj, faces):
    keep = set(faces)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.index not in keep], context="FACES")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    bm.to_mesh(obj.data)
    bm.free()


def add_mpfb_assets(basemesh):
    """MPFB system clothes/shoes/hair, fitted to the body (before it turns).
    Suits come apart into their pieces (top = shirt/jacket, bottom = jeans...)
    so a character can wear a suit's jeans under something else."""
    out = {}
    items = [("shoes", f"clothes/{C['shoes'][0]}/{C['shoes'][0]}.mhclo", "Clothes", None)]
    for spec in C.get("mpfb", ()):
        items.append((spec["key"], f"clothes/{spec['id']}/{spec['id']}.mhclo", "Clothes", spec))
    if C.get("hair"):
        items.append(("hair", f"hair/{C['hair'][0]}/{C['hair'][0]}.mhclo", "Hair", None))
    for key, rel, kind, spec in items:
        o = HumanService.add_mhclo_asset(asset(rel), basemesh, asset_type=kind, subdiv_levels=0, material_type="MAKESKIN")
        o["mpfb_key"] = key
        if spec is not None and spec.get("part", "all") != "all":
            big, parts = split_parts(o)
            if spec["part"] == "top":
                # everything but the lowest big piece (jackets come with collars)
                faces = [i for isl in parts if isl not in big[-1:] for i in isl]
            else:
                faces = big[-1]
            keep_faces(o, faces)
        o.name = key
        out[key] = o
    return out


def face_forward(rig):
    """MakeHuman faces -Y; turn the rig and everything on it to face +Y."""
    objs = [rig] + [o for o in bpy.data.objects if o.parent == rig]
    rig.rotation_euler = (0, 0, math.pi)
    bpy.context.view_layer.update()
    select_only(*objs)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)


def stand_on_soles(rig):
    """MakeHuman puts the bare feet on the ground; shoe soles go below it.
    Lift everything so the lowest sole touches z = 0."""
    kids = [o for o in bpy.data.objects if o.parent == rig and o.type == "MESH"]
    body = next(o for o in kids if o.name.startswith("Human") or o.get("mpfb_key") is None)
    helpers = {body.vertex_groups["body"].index} if "body" in body.vertex_groups else None
    lo = 0.0
    for o in kids:
        for v in o.data.vertices:
            if o is body and helpers and not any(g.group in helpers for g in v.groups):
                continue
            lo = min(lo, v.co.z)
    if lo < -1e-4:
        objs = [rig] + kids
        rig.location.z -= lo
        bpy.context.view_layer.update()
        select_only(*objs)
        bpy.context.view_layer.objects.active = rig
        bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)
        log(f"soles: lifted {-lo * 100:.1f} cm")


def strip_helpers(basemesh):
    """Remove helper geometry (joint cubes, eye and teeth helpers, the
    tights/skirt helpers) and every clothes MASK."""
    body = basemesh.vertex_groups["body"].index
    delete_verts(basemesh, lambda v: not any(g.group == body for g in basemesh.data.vertices[v.index].groups))
    for m in list(basemesh.modifiers):
        if m.type == "MASK":
            basemesh.modifiers.remove(m)


def landmarks(b):
    """Head landmarks from MPFB's helper/extra groups (before the helpers go)."""
    L = {}
    L["eye"] = (centroid(b, "joint-l-eye") + centroid(b, "joint-r-eye")) / 2
    L["eye_dx"] = abs(centroid(b, "joint-l-eye").x - centroid(b, "joint-r-eye").x)
    L["lips"] = centroid(b, "lips")
    head = b.vertex_groups["head"].index
    body = b.vertex_groups["body"].index
    pts = [v.co for v in b.data.vertices
           if any(g.group == head and g.weight > 0.5 for g in v.groups) and any(g.group == body for g in v.groups)]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    L["head_lo"], L["head_hi"] = lo, hi
    ears = b.vertex_groups["ears"].index
    ear_pts = [v.co for v in b.data.vertices if any(g.group == ears and g.weight > 0.5 for g in v.groups)]
    L["ear_x"] = max(abs(p.x) for p in ear_pts)
    L["ear_y"] = sum(p.y for p in ear_pts) / len(ear_pts)
    L["ear_z"] = sum(p.z for p in ear_pts) / len(ear_pts)
    # Skull centre: between the ears, at eye height.
    L["head_c"] = Vector((0.0, L["ear_y"] + 0.012, (L["eye"].z + L["ear_z"]) / 2))
    L["top"] = hi.z
    d = L["eye"].z - L["lips"].z
    L["d"] = d
    L["brow"] = L["eye"].z + 0.36 * d
    L["chin"] = L["lips"].z - 0.78 * d
    return L


def face_oval(L):
    """The void's outline: front-projected egg from mid-forehead to under the
    chin, cheek to cheek (just in front of the ears)."""
    top = L["eye"].z + 0.40 * L["d"]
    bot = L["chin"]
    zc, az = (top + bot) / 2, (top - bot) / 2
    ax = 0.83 * L["ear_x"]

    def inside(co, grow=0.0):
        t = (co.z - zc) / (az + grow)
        k = 1.0 - 0.22 * max(0.0, -t)  # narrower toward the chin
        return (co.x / (ax * k + grow)) ** 2 + t * t <= 1.0

    return zc, az, ax, inside


def boundary_loops(bm):
    """Closed boundary loops as vertex lists, walked through the faces' loops
    (robust at vertices where two holes touch)."""

    def next_boundary(l):
        c = l.link_loop_next
        for _ in range(64):
            if c.edge.is_boundary:
                return c
            c = c.link_loop_radial_next.link_loop_next
        return None

    done, out = set(), []
    for e0 in bm.edges:
        if not e0.is_boundary or e0 in done:
            continue
        l = e0.link_loops[0]
        loop = []
        while l is not None and l.edge not in done:
            done.add(l.edge)
            loop.append(l.vert)
            l = next_boundary(l)
        out.append(loop)
    return out


def void_face(body, L, void_slot):
    """Replace the face with a smooth glossy dome (material slot `void_slot`),
    set a couple of millimetres into the skin like a screen.

    The faces inside the oval go; the jagged hole is bridged by a thin skin
    strip to an exact oval traced on the skin, and the dome fills that."""
    zc, az, ax, inside = face_oval(L)
    y_cut = L["ear_y"] + 0.02
    bm = bmesh.new()
    bm.from_mesh(body.data)
    tree = BVHTree.FromBMesh(bm)
    uv = bm.loops.layers.uv.active
    src_lay = bm.verts.layers.int.get("src_index")
    doomed = [f for f in bm.faces if f.calc_center_median().y > y_cut and inside(f.calc_center_median())]
    bmesh.ops.delete(bm, geom=doomed, context="FACES")
    # Drop crumbs (bits of the mouth cavity left floating).
    bm.faces.ensure_lookup_table()
    seen, islands = set(), []
    for f in bm.faces:
        if f in seen:
            continue
        stack, isl = [f], []
        seen.add(f)
        while stack:
            g = stack.pop()
            isl.append(g)
            for e in g.edges:
                for h in e.link_faces:
                    if h not in seen:
                        seen.add(h)
                        stack.append(h)
        islands.append(isl)
    islands.sort(key=len)
    for isl in islands[:-1]:
        if len(isl) < 400:
            bmesh.ops.delete(bm, geom=isl, context="FACES")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")

    def angle(co):
        t = (co.z - zc) / az
        return math.atan2(t, co.x / (ax * (1.0 - 0.22 * max(0.0, -t))))

    loops = boundary_loops(bm)
    near = [lp for lp in loops if sum(1 for v in lp if v.co.y > y_cut - 0.01 and inside(v.co, 0.012)) > 0.8 * len(lp)]
    rim = max(near, key=len)
    n = len(rim)
    angs = [angle(v.co) for v in rim]
    # Walk counter-clockwise (increasing angle).
    turn = sum(((angs[(i + 1) % n] - angs[i] + math.pi) % (2 * math.pi)) - math.pi for i in range(n))
    if turn < 0:
        rim.reverse()
        angs.reverse()
    # The clean ring: the rim smoothed along the loop, pulled 3 % toward the
    # centre (so it lies inside the hole), snapped back onto the original face.
    pts = [v.co.copy() for v in rim]
    for _ in range(8):
        pts = [(pts[i - 1] + pts[i] * 2 + pts[(i + 1) % n]) / 4 for i in range(n)]
    oc = Vector((0.0, 0.0, zc))
    oval = []
    for p in pts:
        q = Vector((oc.x + (p.x - oc.x) * 0.97, p.y, oc.z + (p.z - oc.z) * 0.97))
        hit = tree.find_nearest(q, 0.05)[0]
        oval.append(bm.verts.new(hit if hit is not None else q))
    rim_uv = []
    for v in rim:
        lp = v.link_loops[0] if v.link_loops else None
        rim_uv.append(lp[uv].uv.copy() if (lp and uv) else None)
    strip = []
    for i in range(n):
        j = (i + 1) % n
        f = bm.faces.new((rim[i], rim[j], oval[j], oval[i]))
        f.material_index = 0
        f.smooth = True
        strip.append(f)
        if uv:
            for lp, src in zip(f.loops, (rim_uv[i], rim_uv[j], rim_uv[j], rim_uv[i])):
                if src is not None:
                    lp[uv].uv = src

    # Visor surface: an ellipsoidal cap over the (x, z) plane.
    rx, rz = ax * 1.3, az * 1.3
    y_front = L["eye"].y + 0.03

    def g(x, z):
        return math.sqrt(max(0.0, 1.0 - (x / rx) ** 2 - ((z - zc) / rz) ** 2))

    gi = [g(v.co.x, v.co.z) for v in oval]
    ybar = sum(v.co.y for v in oval) / n
    ry = (y_front - ybar) / max(0.05, 1.0 - sum(gi) / n)
    y0 = y_front - ry

    def y_ell(x, z):
        return y0 + ry * g(x, z)

    qc = (0.0, zc + 0.08 * az)
    rings = [oval]
    us = (0.0, 0.03, 0.09, 0.19, 0.32, 0.47, 0.62, 0.77, 0.9)
    for k, u in enumerate(us):
        if k == 0:
            continue
        ring = []
        for b in oval:
            x = qc[0] + (b.co.x - qc[0]) * (1 - u)
            z = qc[1] + (b.co.z - qc[1]) * (1 - u)
            y = y_ell(x, z) + (b.co.y - y_ell(b.co.x, b.co.z)) * (1 - u) ** 2
            p = Vector((x, y, z))
            if k == 1:
                # Inset step: the screen sits 2.5 mm into the skin.
                p += (L["head_c"] - p).normalized() * 0.0025
            ring.append(bm.verts.new(p))
        rings.append(ring)
    tip = bm.verts.new(Vector((qc[0], y_ell(*qc), qc[1])))
    cap = []
    for k in range(len(rings) - 1):
        a, b2 = rings[k], rings[k + 1]
        for i in range(n):
            j = (i + 1) % n
            cap.append(bm.faces.new((a[i], a[j], b2[j], b2[i])))
    last = rings[-1]
    for i in range(n):
        cap.append(bm.faces.new((last[i], last[(i + 1) % n], tip)))
    bm.normal_update()
    for group in (strip, cap):
        outward = sum((f.normal.dot(f.calc_center_median() - L["head_c"]) for f in group), 0.0)
        for f in group:
            if outward < 0:
                f.normal_flip()
    for f in cap:
        f.material_index = void_slot
        f.smooth = True
    for i in range(n):
        for r in (oval, rings[1]):
            e = bm.edges.get((r[i], r[(i + 1) % n]))
            if e:
                e.smooth = False
    bm.normal_update()
    L["void_rim"] = [(v.co.copy(), angle(v.co)) for v in oval]
    # The new face rides on the head bone.
    dl = bm.verts.layers.deform.verify()
    hi = body.vertex_groups["head"].index
    for v in oval + [v for r in rings[1:] for v in r] + [tip]:
        v[dl].clear()
        v[dl][hi] = 1.0
    if src_lay is not None:
        for v in oval + [v for r in rings[1:] for v in r] + [tip]:
            v[src_lay] = -1
    bm.to_mesh(body.data)
    bm.free()
    body.data.update()
    log(f"void face: rim {n} verts, {len(cap)} faces")


# ================================================================ images

CACHE = os.path.join(ROOT, "tools", "cache", "human", CHAR)
os.makedirs(CACHE, exist_ok=True)


def mhmat_texture(mhmat, key="diffuseTexture"):
    folder = os.path.dirname(mhmat)
    with open(mhmat, encoding="utf-8", errors="replace") as f:
        for line in f:
            parts = line.strip().split(None, 1)
            if len(parts) == 2 and parts[0] == key:
                p = os.path.join(folder, os.path.basename(parts[1].strip()))
                return p if os.path.exists(p) else None
    return None


def resized(path, size=1024, name=None, data=False):
    """A copy of `path` scaled to fit `size`, saved in the build cache (PNG)."""
    name = name or os.path.splitext(os.path.basename(path))[0]
    out = os.path.join(CACHE, f"{name}_{size}.png")
    if not os.path.exists(out) or os.path.getmtime(out) < os.path.getmtime(path):
        src = bpy.data.images.load(path)
        w, h = src.size
        k = min(1.0, size / max(w, h))
        if k < 1:
            src.scale(max(1, int(w * k)), max(1, int(h * k)))
        src.filepath_raw = out
        src.file_format = "PNG"
        src.save()
        bpy.data.images.remove(src)
    img = bpy.data.images.load(out, check_existing=True)
    img.name = name
    img.colorspace_settings.name = "Non-Color" if data else "sRGB"
    return img


def skin_material(skin_id):
    mhmat = asset(f"skins/{skin_id}/{skin_id}.mhmat")
    tex = mhmat_texture(mhmat)
    m = mat.new_material("Skin")
    nt = m.node_tree
    p = mat.principled(m)
    img = nt.nodes.new("ShaderNodeTexImage")
    img.image = resized(tex, 1024, "skin")
    img.location = (-500, 200)
    nt.links.new(img.outputs["Color"], p.inputs["Base Color"])
    p.inputs["Roughness"].default_value = 0.5
    p.inputs["Specular IOR Level"].default_value = 0.45
    m.diffuse_color = (0.6, 0.45, 0.38, 1)
    return m


# ================================================================ garments
#
# Shell garments are grown from the body: faces picked by the rig's weights
# (the dominant bone of each vertex, cut by planes along the bones), pushed out
# along the normals, smoothed until the anatomy is gone, kept a few mm off the
# skin, and finished with hems, cuffs and seams. They keep the body's UVs and
# its MPFB weights (1:1 vertices), so they deform exactly like the skin.

import numpy as np  # noqa: E402

TORSO = {"pelvis", "spine_01", "spine_02", "spine_03", "clavicle_l", "clavicle_r"}
ARMS = {"upperarm_l", "upperarm_r", "lowerarm_l", "lowerarm_r"}
LEGS = {"thigh_l", "thigh_r", "calf_l", "calf_r"}
HEADS = {"neck_01", "head"}


class Source:
    """The pristine body (after helpers are gone, before anything is cut):
    positions, normals, dominant bones, adjacency and a BVH."""

    def __init__(self, body, rig, L):
        self.obj, self.rig, self.L = body, rig, L
        me = body.data
        n = len(me.vertices)
        self.co = np.empty(n * 3, np.float32)
        me.vertices.foreach_get("co", self.co)
        self.co = self.co.reshape(n, 3).astype(np.float64)
        self.no = np.empty(n * 3, np.float32)
        me.vertices.foreach_get("normal", self.no)
        self.no = self.no.reshape(n, 3).astype(np.float64)
        names = {g.index: g.name for g in body.vertex_groups}
        # Garments grow from a body without nipples.
        for gi in [g.index for g in body.vertex_groups if g.name in ("nipple", "nippleTip")]:
            for v in me.vertices:
                w = next((g.weight for g in v.groups if g.group == gi), 0.0)
                if w > 0:
                    self.co[v.index] -= self.no[v.index] * 0.005 * w
        bones = {b.name for b in rig.data.bones}
        self.dom = [None] * n
        self.w = [dict() for _ in range(n)]
        for v in me.vertices:
            best, bw = None, 0.0
            for g in v.groups:
                nm = names[g.group]
                if nm in bones and g.weight > 0:
                    self.w[v.index][nm] = g.weight
                    if g.weight > bw:
                        best, bw = nm, g.weight
            self.dom[v.index] = best
        e = np.empty(len(me.edges) * 2, np.int64)
        me.edges.foreach_get("vertices", e)
        self.edges = e.reshape(-1, 2)
        self.faces = [tuple(p.vertices) for p in me.polygons]
        bm = bmesh.new()
        bm.from_mesh(me)
        # Garments never follow the ears: they're left out of the skin BVH.
        skip = [body.vertex_groups[n].index for n in ("ears", "nipple", "nippleTip") if n in body.vertex_groups]
        dl = bm.verts.layers.deform.active
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if any(v[dl].get(g, 0.0) > 0.3 for g in skip)], context="VERTS")
        self.tree = BVHTree.FromBMesh(bm)
        bm.free()
        self.bone = {b.name: (b.head_local.copy(), b.tail_local.copy()) for b in rig.data.bones}

    def along(self, i, bone):
        h, t = self.bone[bone]
        d = t - h
        return (Vector(self.co[i]) - h).dot(d) / d.length_squared

    def neighbours(self, keep):
        """Rings of neighbours: returns, per vertex, whether all verts within
        two edges are in `keep` (a bool array)."""
        k = keep.copy()
        for _ in range(2):
            bad = ~k
            nb = np.zeros(len(k), bool)
            a, b = self.edges[:, 0], self.edges[:, 1]
            np.logical_or.at(nb, a, bad[b])
            np.logical_or.at(nb, b, bad[a])
            k = k & ~nb
        return k


def smooth_positions(P, edges, fixed, iters, lam=0.5, boundary=None):
    """Laplacian smoothing (umbrella) of P; `fixed` verts stay; `boundary`
    verts (bool) only average with other boundary verts (keeps openings)."""
    n = len(P)
    a, b = edges[:, 0], edges[:, 1]
    if boundary is None:
        to_a = to_b = np.ones(len(a), bool)
    else:
        to_a = ~boundary[a] | boundary[b]
        to_b = ~boundary[b] | boundary[a]
    cnt = np.zeros(n)
    np.add.at(cnt, a[to_a], 1)
    np.add.at(cnt, b[to_b], 1)
    m = (cnt > 0) & ~fixed
    for _ in range(iters):
        acc = np.zeros_like(P)
        np.add.at(acc, a[to_a], P[b[to_a]])
        np.add.at(acc, b[to_b], P[a[to_b]])
        P[m] += lam * (acc[m] / cnt[m, None] - P[m])
    return P


def keep_off(P, src, gap, idx, exact=None):
    """Push shell verts out so each is at least gap[i] off the skin (exactly
    gap[i] where `exact`); gap < 0 leaves a vertex alone."""
    for i in range(len(P)):
        if gap[i] < 0:
            continue
        p = Vector(P[i])
        hit, nrm, _, _ = src.tree.find_nearest(p, 0.3)
        if hit is None:
            continue
        d = (p - hit).dot(nrm)
        if d < gap[i] or (exact is not None and exact[i]):
            P[i] = tuple(p + nrm * (gap[i] - d))
    return P


def grow_shell(src, name, keep_v, offset, gap, smooth=30, rounds=4, boundary_smooth=True):
    """A garment shell over the source faces whose verts all pass keep_v.
    offset/gap: per source-vertex arrays (metres). Returns the object; its
    int attribute "src" maps each vertex to the source vertex."""
    keep = np.array(keep_v, bool)
    bm = bmesh.new()
    bm.from_mesh(src.obj.data)
    lay = bm.verts.layers.int.new("src")
    for v in bm.verts:
        v[lay] = v.index
    bm.faces.ensure_lookup_table()
    doomed = [f for f in bm.faces if not all(keep[v.index] for v in f.verts)]
    bmesh.ops.delete(bm, geom=doomed, context="FACES")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    # Keep the biggest piece (drop specks the cut left behind).
    bm.faces.ensure_lookup_table()
    seen, islands = set(), []
    for f in bm.faces:
        if f in seen:
            continue
        stack, isl = [f], []
        seen.add(f)
        while stack:
            g = stack.pop()
            isl.append(g)
            for e in g.edges:
                for h in e.link_faces:
                    if h not in seen:
                        seen.add(h)
                        stack.append(h)
        islands.append(isl)
    islands.sort(key=len)
    for isl in islands[:-1]:
        bmesh.ops.delete(bm, geom=isl, context="FACES")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    bm.verts.ensure_lookup_table()
    ids = np.array([v[lay] for v in bm.verts])
    P = src.co[ids] + src.no[ids] * np.asarray(offset)[ids, None]
    edges = np.array([(e.verts[0].index, e.verts[1].index) for e in bm.edges])
    bnd = np.array([v.is_boundary for v in bm.verts])
    g = np.asarray(gap)[ids].copy()
    # Openings sit at their offset from the skin (smoothing a loop shrinks it).
    exact = bnd.copy()
    g[bnd] = np.asarray(offset)[ids][bnd]
    fixed = np.zeros(len(P), bool)
    for r in range(rounds):
        P = smooth_positions(P, edges, fixed, smooth, 0.6, bnd if boundary_smooth else None)
        P = keep_off(P, src, g, ids, exact)
    for v, p in zip(bm.verts, P):
        v.co = p
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = link(bpy.data.objects.new(name, me))
    for gname in [vg.name for vg in src.obj.vertex_groups]:
        obj.vertex_groups.new(name=gname)
    # Weights come with the vertices (bmesh keeps the deform layer).
    for p in me.polygons:
        p.use_smooth = True
    return obj


def oval_radius(L, co):
    """Normalised radius in the face oval (1 on the void's edge), front only."""
    zc, az, ax, _ = face_oval(L)
    t = (co[2] - zc) / az
    k = 1.0 - 0.22 * max(0.0, -t)
    return math.sqrt((co[0] / (ax * k)) ** 2 + t * t)


def g_joggers(src, cuff=0.8, loose=1.3):
    n = len(src.co)
    waist_z = src.bone["pelvis"][0].z + 0.085
    keep = np.zeros(n, bool)
    off = np.zeros(n)
    gap = np.zeros(n)
    for i in range(n):
        d = src.dom[i]
        co = src.co[i]
        if d in ("thigh_l", "thigh_r"):
            ok = True
            t = src.along(i, d)
            off[i], gap[i] = (0.026 + 0.006 * t) * loose, (0.02 + 0.008 * t) * loose
        elif d in ("calf_l", "calf_r"):
            t = src.along(i, d)
            ok = t < cuff
            k = smoothstep(cuff - 0.45, cuff, t)
            off[i] = (0.03 - 0.022 * k) * loose
            gap[i] = (0.027 - 0.02 * k) * loose
        elif d in ("pelvis", "spine_01"):
            ok = co[2] < waist_z
            off[i], gap[i] = 0.016, 0.01
        else:
            ok = False
        keep[i] = ok
    return keep, off, gap


def make_hood(src, torso, name="hood", puff=1.0, rows=26, cols=88):
    """The hood, up: an annulus of fabric from the face opening (a clean egg
    hugging the void) to a collar loop lying on the hoodie's shoulders,
    bulging over the skull (kept outside a capsule round the head and ears),
    smoothed like cloth. Rows run concentric with the opening."""
    L = src.L
    hc = L["head_c"]
    zc, az, ax, _ = face_oval(L)
    rx = L["ear_x"] + 0.028 * puff
    ry_b = hc.y - L["head_lo"].y + 0.04 * puff
    ry_f = L["eye"].y - hc.y + 0.004
    rz = L["top"] - hc.z + 0.03 * puff

    def capsule_r(d):
        """Distance from hc to the capsule along unit direction d."""
        ry = ry_f if d.y > 0 else ry_b
        peak = 1.0 + 0.09 * puff * max(0.0, -d.y) * max(0.0, d.z)
        if d.z >= 0:
            q = (d.x / rx) ** 2 + (d.y / (ry * peak)) ** 2 + (d.z / (rz * peak)) ** 2
        else:
            q = (d.x / rx) ** 2 + (d.y / ry) ** 2
        return 1.0 / math.sqrt(max(q, 1e-9))

    ring = sorted(L["void_rim"], key=lambda pa: pa[1])

    def void_point(a):
        """The void's edge at oval angle a (interpolated along its rim)."""
        a = (a + math.pi) % (2 * math.pi) - math.pi
        n = len(ring)
        for k in range(n):
            p0, a0 = ring[k - 1]
            p1, a1 = ring[k]
            if k == 0:
                a0 -= 2 * math.pi
            if a0 <= a <= a1:
                t = (a - a0) / max(a1 - a0, 1e-6)
                return p0.lerp(p1, t)
        return ring[0][0]

    tb = bmesh.new()
    tb.from_mesh(torso.data)
    ttree = BVHTree.FromBMesh(tb)
    tb.free()
    neck = src.bone["neck_01"][0]
    na, nb = cols, rows
    R, K = [], []
    for i in range(na):
        a = 2 * math.pi * i / na
        vp = void_point(a)
        out_d = (vp - hc)
        out_d.y *= 0.4  # outward, mostly sideways/up/down from the face
        R.append(vp + out_d.normalized() * 0.006 + Vector((0, 0.012, 0)))
        psi = a + math.pi / 2  # rim top -> collar back, rim bottom -> collar front
        cx, cy = 0.1, (0.075 if math.cos(psi) > 0 else 0.095)
        k = Vector((neck.x + math.sin(psi) * cx, neck.y + math.cos(psi) * cy,
                    neck.z - 0.045 * max(0.0, math.cos(psi)) - 0.015))
        hit, nrm, _, _ = ttree.find_nearest(k, 0.3)
        K.append(hit + nrm * 0.006 if hit is not None else k)

    def constrain(p, w_cap=1.0):
        d = p - hc
        w = smoothstep(hc.z - 0.1, hc.z - 0.035, p.z) * w_cap
        if w > 0 and d.length > 1e-6:
            r = capsule_r(d.normalized())
            if d.length < r:
                p = hc + d.normalized() * (d.length + (r - d.length) * w)
        hit, nrm, _, _ = src.tree.find_nearest(p, 0.3)
        if hit is not None:
            gap = 0.018
            dd = (p - hit).dot(nrm)
            if dd < gap:
                p = p + nrm * (gap - dd)
        return p

    # Each column: a quadratic Bezier from the rim, out over the head (via a
    # control point on the side of the capsule this column belongs to), down
    # to the collar; then pushed onto the capsule and relaxed a little.
    P = np.zeros((nb + 1, na, 3))
    for i in range(na):
        a = 2 * math.pi * i / na
        m = Vector((math.cos(a), -0.5, math.sin(a) + 0.15)).normalized()
        far = smoothstep(-0.6, 0.2, math.sin(a))  # the chin columns barely bulge
        ctrl = hc + m * capsule_r(m) * 1.25
        mid = (R[i] + K[i]) / 2
        ctrl = mid + (ctrl - mid) * far
        for j in range(nb + 1):
            t = j / nb
            p = R[i] * (1 - t) ** 2 + ctrl * (2 * t * (1 - t)) + K[i] * t * t
            P[j, i] = constrain(p, smoothstep(0.0, 0.25, t)) if 0 < j < nb else p
    for _ in range(3):
        for _ in range(6):
            Q = P.copy()
            Q[1:-1] = (P[:-2] + P[2:] + np.roll(P[1:-1], 1, axis=1) + np.roll(P[1:-1], -1, axis=1)) / 4
            P[1:-1] = P[1:-1] + 0.5 * (Q[1:-1] - P[1:-1])
        for j in range(1, nb):
            t = j / nb
            for i in range(na):
                P[j, i] = constrain(Vector(P[j, i]), smoothstep(0.0, 0.25, t))
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new("UVMap")
    V = [[bm.verts.new(P[j, i]) for i in range(na)] for j in range(nb + 1)]
    # The rolled rim: a lip turned in toward the head.
    lip = [bm.verts.new(V[0][i].co + (hc - V[0][i].co).normalized() * 0.012 - Vector((0, 0.004, 0))) for i in range(na)]
    for j in range(nb):
        for i in range(na):
            i2 = (i + 1) % na
            f = bm.faces.new((V[j][i], V[j][i2], V[j + 1][i2], V[j + 1][i]))
            for lp, (u, v) in zip(f.loops, ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1))):
                lp[uv].uv = (u / na, 0.06 + 0.94 * v / nb)
    for i in range(na):
        i2 = (i + 1) % na
        f = bm.faces.new((lip[i], lip[i2], V[0][i2], V[0][i]))
        for lp, (u, v) in zip(f.loops, ((i, 0.0), (i + 1, 0.0), (i + 1, 0.06), (i, 0.06))):
            lp[uv].uv = (u / na, v)
    bm.normal_update()
    out = sum((f.normal.dot(f.calc_center_median() - hc) for f in bm.faces), 0.0)
    if out < 0:
        for f in bm.faces:
            f.normal_flip()
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = link(bpy.data.objects.new(name, me))
    for p in me.polygons:
        p.use_smooth = True
    transfer_weights(src.obj, obj)
    return obj


def hood_down(src, torso, name="hooddown"):
    """The hood, down: a soft pouch lying on the upper back, its opening
    rolled toward the neck."""
    S = src.L["top"] / 1.72
    tb = bmesh.new()
    tb.from_mesh(torso.data)
    tree = BVHTree.FromBMesh(tb)
    tb.free()
    neck = src.bone["neck_01"][0]
    cz = neck.z - 0.085 * S
    hw, hh = 0.13 * S, 0.11 * S
    nu, nv = 16, 10
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new("UVMap")
    grid = []
    for j in range(nv + 1):
        v = j / nv
        row = []
        for i in range(nu + 1):
            u = i / nu
            a = math.pi * (u - 0.5) * 1.1
            # A half-disc hanging from the collar: the top edge follows the neck.
            r = 0.2 + 0.8 * v
            x = math.sin(a) * hw * r
            z = cz + hh * 0.9 - math.cos(a) * hh * r * 1.25 * (0.6 + 0.4 * v)
            hit = tree.ray_cast(Vector((x, -0.6, z)), Vector((0, 1, 0)), 1.0)
            ok = hit[0] is not None and hit[1].y < -0.3
            base = hit[0] if ok else Vector((x, neck.y - 0.1 * S, z))
            nrm = hit[1] if ok else Vector((0, -1, 0))
            puff = (0.004 + 0.03 * math.sin(math.pi * v) * (1 - (2 * u - 1) ** 2) ** 0.5) * S
            row.append(bm.verts.new(base + nrm * puff))
        grid.append(row)
    for j in range(nv):
        for i in range(nu):
            f = bm.faces.new((grid[j][i], grid[j][i + 1], grid[j + 1][i + 1], grid[j + 1][i]))
            for lp, (uu, vv) in zip(f.loops, ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1))):
                lp[uv].uv = (uu / nu, vv / nv)
    bm.normal_update()
    out = sum((f.normal.dot(Vector((0, -1, 0))) for f in bm.faces), 0.0)
    if out < 0:
        for f in bm.faces:
            f.normal_flip()
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = link(bpy.data.objects.new(name, me))
    for p in me.polygons:
        p.use_smooth = True
    transfer_weights(src.obj, obj)
    return obj


def polo_trims(src, polo):
    """A polo's collar (flared band round the MPFB tee's neckline) and its
    placket with two buttons."""
    if polo is None:
        return []
    out = []
    loops = shell_loops(polo)
    neck = max(loops, key=lambda lp: sum(v.co.z for v in lp) / len(lp))
    m = fabric("polo_collar", colour("polo"), "cotton_jersey", uv=True, tiling=(8, 1))
    out.append(band(src, polo, neck, (0, -0.2, 1), 0.03, -0.35, "collar", m, rows=2, lip=0.004))
    pb = bmesh.new()
    pb.from_mesh(polo.data)
    tree = BVHTree.FromBMesh(pb)
    pb.free()
    top = min(neck, key=lambda v: -v.co.y).co  # front of the neckline
    strip = []
    for k in range(6):
        z = top.z - 0.01 - 0.018 * k
        row = []
        for x in (-0.013, 0.013):
            hit = tree.ray_cast(Vector((x, 0.5, z)), Vector((0, -1, 0)), 1.0)
            row.append(hit[0] + hit[1] * 0.0025 if hit[0] is not None else Vector((x, top.y, z)))
        strip.append(row)
    bm = bmesh.new()
    uvl = bm.loops.layers.uv.new("UVMap")
    V = [[bm.verts.new(p) for p in row] for row in strip]
    for k in range(len(V) - 1):
        f = bm.faces.new((V[k][0], V[k + 1][0], V[k + 1][1], V[k][1]))
        for lp, (u, v) in zip(f.loops, ((0, k), (0, k + 1), (1, k + 1), (1, k))):
            lp[uvl].uv = (u, v / 5)
    bm.normal_update()
    for f in bm.faces:
        if f.normal.y < 0:
            f.normal_flip()
    me = bpy.data.meshes.new("placket")
    bm.to_mesh(me)
    bm.free()
    me.materials.append(m)
    pl = link(bpy.data.objects.new("placket", me))
    transfer_weights(src.obj, pl)
    out.append(pl)
    bm_ = prop_mat("button", "#e8e4dc", rough=0.35)
    for k in (1, 3):
        c = (Vector(strip[k][0]) + Vector(strip[k][1])) / 2 + Vector((0, 0.0015, 0))
        b = tube("button", [c, c + Vector((0, 0.002, 0))], 0.0045, 10, bm_)
        transfer_weights(src.obj, b)
        out.append(b)
    return out


def transfer_weights(source, obj, exclude=()):
    """Copy the skin weights of the nearest body surface (runner.py's weigh())."""
    for vg in source.vertex_groups:
        if vg.name not in obj.vertex_groups:
            obj.vertex_groups.new(name=vg.name)
    mod = obj.modifiers.new("weights", "DATA_TRANSFER")
    mod.object = source
    mod.use_vert_data = True
    mod.data_types_verts = {"VGROUP_WEIGHTS"}
    mod.vert_mapping = "POLYINTERP_NEAREST"
    mod.layers_vgroup_select_src = "ALL"
    mod.layers_vgroup_select_dst = "NAME"
    with bpy.context.temp_override(object=obj, active_object=obj):
        bpy.ops.object.modifier_apply(modifier=mod.name)
    for name in exclude:
        vg = obj.vertex_groups.get(name)
        if vg:
            obj.vertex_groups.remove(vg)


def g_top(src, hem_z, sleeve="long", cuff=0.84, loose=1.0, drape=0.012, fit=None):
    """Tops grown from the torso and arms: long sleeves to `cuff` along the
    forearm, "short" to `cuff` along the upper arm; crew neck at the neck's
    base. fit: (torso off, gap, arm off, gap) for tight tees."""
    n = len(src.co)
    chest_z = src.bone["spine_03"][0].z
    neck_z = src.bone["neck_01"][0].z + 0.004
    keep = np.zeros(n, bool)
    off = np.zeros(n)
    gap = np.zeros(n)
    for i in range(n):
        d = src.dom[i]
        co = src.co[i]
        if d in TORSO or d == "neck_01":
            ok = co[2] > hem_z and (d != "neck_01" or co[2] < neck_z)
            low = smoothstep(chest_z, hem_z, co[2])
            if fit:
                off[i], gap[i] = fit[0], fit[1]
            else:
                off[i] = (0.024 + drape * low) * loose
                gap[i] = (0.018 + drape * low) * loose
        elif d in ARMS:
            t = src.along(i, d)
            if sleeve == "long":
                ok = not (d.startswith("lowerarm") and t > cuff)
            else:
                ok = d.startswith("upper") and t < cuff
            if fit:
                off[i], gap[i] = fit[2], fit[3]
            elif d.startswith("upper"):
                off[i], gap[i] = 0.022 * loose, 0.017 * loose
            else:
                k = smoothstep(cuff - 0.25, cuff, t)
                off[i], gap[i] = (0.021 - 0.01 * k) * loose, (0.016 - 0.009 * k) * loose
        else:
            ok = False
        keep[i] = ok
    return dict(keep=keep, off=off, gap=gap)


def hem_hip(src):
    return src.bone["thigh_l"][0].z - 0.035


def hem_waist(src):
    return src.bone["pelvis"][0].z + 0.13


GARMENTS = {
    "hoodie.up": lambda src: dict(g_top(src, hem_hip(src)), trims=("cuffs", "hem", "pocket"), hood="up"),
    "hoodie.down": lambda src: dict(g_top(src, hem_hip(src)), trims=("cuffs", "hem", "pocket", "collar"), hood="down"),
    "sweat.crop": lambda src: dict(g_top(src, hem_waist(src), loose=1.1, drape=0.0), trims=("cuffs", "hem", "collar")),
    "tee.muscle": lambda src: dict(g_top(src, hem_hip(src) + 0.02, sleeve="short", cuff=0.42, fit=(0.007, 0.005, 0.006, 0.004)),
                                   trims=("sleeves", "collar.thin", "hem.thin"), smooth=6, rounds=2),
    "joggers": lambda src: dict(zip(("keep", "off", "gap"), g_joggers(src, loose=C.get("loose", 1.3))), trims=("anklecuffs",)),
    "pyjama": lambda src: dict(zip(("keep", "off", "gap"), g_joggers(src, cuff=0.9, loose=1.45)), trims=("anklehems",)),
}


# ================================================================ posing
#
# Rotations are given as 3x3 matrices "D" in the armature's rest-aligned axes
# (X right, Y forward, Z up), applied at a bone's head on top of its parent's
# motion: the local pose is rest^-1 @ D @ rest. The torso chain (pelvis ..
# head, clavicles) is solved in Python (FK); legs and arms use IK constraints
# on target empties, hands and feet copy the empties' rotation; every frame is
# then baked to plain local keys (visual keying) and the constraints go.

def Rx(deg):
    return Matrix.Rotation(math.radians(deg), 3, "X")


def Ry(deg):
    return Matrix.Rotation(math.radians(deg), 3, "Y")


def Rz(deg):
    return Matrix.Rotation(math.radians(deg), 3, "Z")


def Rax(axis, deg):
    return Matrix.Rotation(math.radians(deg), 3, Vector(axis).normalized())


def pitch(deg):
    """Lean forward (top toward +Y) by deg."""
    return Rx(-deg)


def roll(deg):
    """Tilt toward the character's right (+X) by deg (top goes +X)."""
    return Ry(deg)


def yaw(deg):
    """Turn toward the character's left by deg (seen from above, CCW)."""
    return Rz(deg)


I3 = Matrix.Identity(3)
TORSO_CHAIN = ["pelvis", "spine_01", "spine_02", "spine_03", "neck_01", "head", "clavicle_l", "clavicle_r"]
FINGERS = ("thumb", "index", "middle", "ring", "pinky")


class Rig:
    def __init__(self, obj):
        self.obj = obj
        bones = obj.data.bones
        self.rest = {b.name: b.matrix_local.to_3x3().normalized() for b in bones}
        self.head = {b.name: b.head_local.copy() for b in bones}
        self.tail = {b.name: b.tail_local.copy() for b in bones}
        self.parent = {b.name: (b.parent.name if b.parent else None) for b in bones}
        self.names = [b.name for b in bones]
        for pb in obj.pose.bones:
            pb.rotation_mode = "QUATERNION"
        # Palm normals and finger bend axes (armature rest space).
        self.palm = {}
        for s in ("l", "r"):
            f = (self.head[f"middle_01_{s}"] - self.head[f"hand_{s}"]).normalized()
            k = (self.head[f"pinky_01_{s}"] - self.head[f"index_01_{s}"]).normalized()
            n = f.cross(k).normalized()
            if s == "l":
                n = -n
            self.palm[s] = n

    def fk(self, D, pelvis_off=Vector()):
        """World delta rotations W and head positions P of the torso chain."""
        W, P = {}, {}
        for b in TORSO_CHAIN:
            par = self.parent[b]
            d = D.get(b, I3)
            if b == "pelvis":
                W[b] = d
                P[b] = self.head[b] + pelvis_off
            else:
                W[b] = W[par] @ d
                P[b] = P[par] + W[par] @ (self.head[b] - self.head[par])
        return W, P

    def world_point(self, W, P, bone, rest_point):
        """Where a point attached (rigidly) to `bone` in rest goes."""
        return P[bone] + W[bone] @ (Vector(rest_point) - self.head[bone])

    def local_q(self, name, D):
        R = self.rest[name]
        return (R.inverted() @ D @ R).to_quaternion()

    def finger_curl(self, side, finger, angles, spread=0.0):
        """Local quaternions curling a finger toward the palm (per joint deg)."""
        out = {}
        n = self.palm[side]
        for j, ang in enumerate(angles, start=1):
            b = f"{finger}_0{j}_{side}"
            d = (self.tail[b] - self.head[b]).normalized()
            axis = d.cross(n).normalized()  # rotating by +ang moves the tip toward n
            D = Rax(axis, ang)
            if j == 1 and spread:
                D = Rax(n, spread if side == "r" else -spread) @ D
            out[b] = self.local_q(b, D)
        return out


def make_empty(name, size=0.03):
    e = link(bpy.data.objects.new(name, None))
    e.empty_display_size = size
    e.rotation_mode = "QUATERNION"
    return e


class Solver:
    """IK targets and constraints for the four limbs."""

    def __init__(self, rig):
        self.rig = rig
        obj = rig.obj
        self.t, self.pole = {}, {}
        for s in ("l", "r"):
            for limb, chain_end, rot_bone in (("foot", f"calf_{s}", f"foot_{s}"), ("hand", f"lowerarm_{s}", f"hand_{s}")):
                key = f"{limb}_{s}"
                t = make_empty(f"ik_{key}")
                pole = make_empty(f"pole_{key}")
                self.t[key], self.pole[key] = t, pole
                pb = obj.pose.bones[chain_end]
                ik = pb.constraints.new("IK")
                ik.target, ik.pole_target = t, pole
                ik.chain_count = 2
                ik.use_tail = True
                ik.use_stretch = False
                ik.iterations = 200
                cr = obj.pose.bones[rot_bone].constraints.new("COPY_ROTATION")
                cr.target = t
                cr.target_space = cr.owner_space = "WORLD"
                for bn in (chain_end, self._up(chain_end)):
                    obj.pose.bones[bn].ik_stretch = 0.0
            # The thumb reaches its tip target (on the screen, round a cup...).
            t = make_empty(f"ik_thumb_{s}", 0.01)
            self.t[f"thumb_{s}"] = t
            ik = obj.pose.bones[f"thumb_03_{s}"].constraints.new("IK")
            ik.target = t
            ik.chain_count = 3
            ik.use_tail = True
            ik.use_stretch = False
            ik.iterations = 200
        self.calibrate()

    def _up(self, b):
        return self.rig.parent[b]

    def place(self, key, pos, W_delta, pole_pos):
        """Target: bone head of hand/foot at pos, its rest frame turned by
        W_delta (3x3, armature axes)."""
        bone = ("hand_" if key.startswith("hand") else "foot_") + key[-1]
        R = W_delta @ self.rig.rest[bone]
        m = R.to_4x4()
        m.translation = pos
        self.t[key].matrix_world = m
        self.pole[key].location = pole_pos

    def calibrate(self):
        """Find each chain's pole_angle so the knee/elbow points at the pole."""
        obj = self.rig.obj
        rig = self.rig
        for key in self.t:
            s = key[-1]
            if key.startswith("thumb"):
                continue
            if key.startswith("foot"):
                upper, lower, end = f"thigh_{s}", f"calf_{s}", f"foot_{s}"
                bend = Vector((0, 1, 0))
            else:
                upper, lower, end = f"upperarm_{s}", f"lowerarm_{s}", f"hand_{s}"
                bend = Vector((0.3 if s == "r" else -0.3, -1, -0.3)).normalized()
            hip, knee, ankle = rig.head[upper], rig.head[lower], rig.head[end]
            # A target pulled 15 % toward the root makes the chain bend.
            tgt = hip + (ankle - hip) * 0.8
            self.place(key, tgt, I3, knee + bend * 0.5)
            ik = obj.pose.bones[lower].constraints[0]
            best, best_d = 0.0, -9
            for ang in (-180, -135, -90, -45, 0, 45, 90, 135):
                ik.pole_angle = math.radians(ang)
                bpy.context.view_layer.update()
                k = obj.matrix_world @ obj.pose.bones[lower].head
                mid = (hip + tgt) / 2
                d = (k - mid).normalized().dot(bend)
                if d > best_d:
                    best, best_d = ang, d
            # Refine around the best.
            for ang in [best + x for x in range(-40, 41, 5)]:
                ik.pole_angle = math.radians(ang)
                bpy.context.view_layer.update()
                k = obj.matrix_world @ obj.pose.bones[lower].head
                d = (k - (hip + tgt) / 2).normalized().dot(bend)
                if d > best_d:
                    best, best_d = ang, d
            ik.pole_angle = math.radians(best)
            log(f"ik {key}: pole angle {best} (fit {best_d:.3f})")

    def clear(self):
        obj = self.rig.obj
        for pb in obj.pose.bones:
            for c in list(pb.constraints):
                pb.constraints.remove(c)
        for e in list(self.t.values()) + list(self.pole.values()):
            bpy.data.objects.remove(e)

    def thumb(self, side, pos):
        self.t[f"thumb_{side}"].location = pos


def bake_clip(rig, solver, name, frames, pose_fn, loop=False):
    """Author a clip: pose_fn(frame) sets FK channels and IK targets; each
    frame's evaluated pose (constraints included) is keyed as local
    loc/rot on every bone, so the clip plays without any constraint."""
    obj = rig.obj
    act = bpy.data.actions.new(name)
    act.use_fake_user = True
    obj.animation_data_create()
    obj.animation_data.action = act
    keys = {b: [] for b in rig.names}
    for f in range(frames + 1):
        ff = f % frames if loop else f
        pose_fn(ff)
        bpy.context.view_layer.update()
        for pb in obj.pose.bones:
            m = obj.convert_space(pose_bone=pb, matrix=pb.matrix, from_space="POSE", to_space="LOCAL")
            loc, q, _ = m.decompose()
            keys[pb.name].append((loc, q))
    # Clear the live pose, then write the keys (quaternions kept continuous).
    for pb in obj.pose.bones:
        pb.location = (0, 0, 0)
        pb.rotation_quaternion = (1, 0, 0, 0)
    for pb in obj.pose.bones:
        prev = None
        for f, (loc, q) in enumerate(keys[pb.name]):
            if prev is not None and prev.dot(q) < 0:
                q = -q
            prev = q
            pb.location = loc
            pb.rotation_quaternion = q
            pb.keyframe_insert("location", frame=f, group=pb.name)
            pb.keyframe_insert("rotation_quaternion", frame=f, group=pb.name)
    track = obj.animation_data.nla_tracks.new()
    track.name = name
    strip = track.strips.new(name, 0, act)
    strip.name = name
    track.mute = True  # never blend into the clips baked after it
    obj.animation_data.action = None
    log(f"clip {name}: {frames} frames")
    return act


# ================================================================ props
#
# Props are modelled in their own frame, then placed in a hand's rest frame
# (the grip) and weighted 100 % to that hand. A grip is (finger curls, the
# prop's transform in the hand frame); clips pose the fingers with the same
# curls, so the fingers close on the prop in every frame.

PROP_MATS = {}


def prop_mat(key, color, rough=0.5, metal=0.0, **kw):
    """Source materials for the atlas bake (flat colours; textures via pbr)."""
    if key not in PROP_MATS:
        PROP_MATS[key] = mat.flat("src_" + key, color, rough=rough, metal=metal, **kw)
    return PROP_MATS[key]


def rrect(w, h, r, seg=6, inset=0.0):
    """Rounded rectangle loop (x, y), counter-clockwise, `inset` inward."""
    w, h, r = w / 2 - inset, h / 2 - inset, max(0.0005, r - inset)
    pts = []
    for cx, cy, a0 in ((w - r, h - r, 0), (-w + r, h - r, 90), (-w + r, -h + r, 180), (w - r, -h + r, 270)):
        for k in range(seg + 1):
            a = math.radians(a0 + 90 * k / seg)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def loft(bm, rings, closed=True):
    """Faces between consecutive vertex rings (lists of BMVerts)."""
    faces = []
    for ra, rb in zip(rings, rings[1:]):
        n = len(ra)
        for i in range(n if closed else n - 1):
            j = (i + 1) % n
            faces.append(bm.faces.new((ra[i], ra[j], rb[j], rb[i])))
    return faces


def build_phone(name, w=0.0765, h=0.1605, t=0.0082, r=0.0105, screen="Screen", colors=None):
    """A modern flagship-style slab (invented, no brand): bevelled metal band,
    glass back, a camera plateau with three lenses and a flash, side buttons,
    a black bezel and an emissive screen with an island cut-out.
    Frame: X width, Y up, Z out of the screen; centre at the origin."""
    colors = colors or {}
    m_frame = prop_mat(name + "_frame", colors.get("frame", "#8a8a90"), rough=0.32, metal=1.0)
    m_back = prop_mat(name + "_back", colors.get("back", "#1c1d22"), rough=0.22, metal=0.0)
    m_glass = prop_mat("lens_glass", "#050608", rough=0.05, metal=0.3)
    m_ring = prop_mat(name + "_ring", colors.get("frame", "#8a8a90"), rough=0.25, metal=1.0)
    m_bezel = prop_mat("bezel", "#020203", rough=0.08)
    m_flash = prop_mat("flash", "#d8cfae", rough=0.3)
    scr = bpy.data.materials.get(screen) or mat.emissive_screen(screen, (0.62, 0.8, 1.0), 5.0)
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new("UVMap")
    mats = [m_frame, m_back, m_glass, m_ring, m_bezel, m_flash, scr]
    MI = {m.name: i for i, m in enumerate(mats)}
    prof = [  # (inset, z) from the back glass round the band to the front glass
        (0.0011, -t / 2), (0.0005, -t / 2 + 0.0001), (0.0001, -t / 2 + 0.0011), (0.0, -t / 4), (0.0, t / 4),
        (0.0001, t / 2 - 0.0011), (0.0005, t / 2 - 0.0001), (0.0011, t / 2),
    ]
    rings = []
    for inset, z in prof:
        rings.append([bm.verts.new((x, y, z)) for x, y in rrect(w, h, r, 6, inset)])
    band = loft(bm, rings)
    nring = len(rings[0])
    for k, f in enumerate(band):
        row = k // nring
        f.material_index = MI[m_back.name] if row == 0 else (MI[m_bezel.name] if row == len(prof) - 2 else MI[m_frame.name])
    # Back glass: a flat cap.
    back = bm.faces.new(list(reversed(rings[0])))
    back.material_index = MI[m_back.name]
    # Front: bezel inset down to the screen, the screen as its own face.
    scr_ring = [bm.verts.new((x, y, t / 2 + 0.0002)) for x, y in rrect(w, h, r, 6, 0.0026)]
    for f in loft(bm, [rings[-1], scr_ring]):
        f.material_index = MI[m_bezel.name]
    sc = bm.faces.new(scr_ring)
    sc.material_index = MI[scr.name]
    # The island: a black pill on the screen near the top.
    pill = rrect(0.021, 0.0062, 0.0031, 5)
    pv = [bm.verts.new((x, y + h / 2 - 0.0105, t / 2 + 0.00035)) for x, y in pill]
    pf = bm.faces.new(pv)
    pf.material_index = MI[m_bezel.name]
    # Camera plateau on the back, top corner (+X seen from the front is the
    # phone's right; the camera sits top-left seen from the back = +X).
    cs = 0.036
    cx, cy = w / 2 - 0.0045 - cs / 2, h / 2 - 0.0045 - cs / 2
    base = [bm.verts.new((cx + x, cy + y, -t / 2 - 0.0001)) for x, y in rrect(cs, cs, 0.0085, 5)]
    top = [bm.verts.new((cx + x, cy + y, -t / 2 - 0.0013)) for x, y in rrect(cs, cs, 0.0085, 5, 0.0004)]
    for f in loft(bm, [base, top]):
        f.material_index = MI[m_back.name]
    plate = bm.faces.new(list(reversed(top)))
    plate.material_index = MI[m_back.name]

    def disc(x, y, z0, z1, rad, m_side, m_top, seg=20, lens=True):
        a = [bm.verts.new((x + rad * math.cos(2 * math.pi * i / seg), y + rad * math.sin(2 * math.pi * i / seg), z0)) for i in range(seg)]
        b = [bm.verts.new((x + rad * math.cos(2 * math.pi * i / seg), y + rad * math.sin(2 * math.pi * i / seg), z1)) for i in range(seg)]
        for f in loft(bm, [a, b]):
            f.material_index = MI[m_side.name]
        if lens:  # the glass sits a little into the ring
            c = [bm.verts.new((x + rad * 0.78 * math.cos(2 * math.pi * i / seg), y + rad * 0.78 * math.sin(2 * math.pi * i / seg), z1)) for i in range(seg)]
            d = [bm.verts.new((x + rad * 0.72 * math.cos(2 * math.pi * i / seg), y + rad * 0.72 * math.sin(2 * math.pi * i / seg), z1 + 0.0004)) for i in range(seg)]
            for f in loft(bm, [b, c]):
                f.material_index = MI[m_ring.name]
            for f in loft(bm, [c, d]):
                f.material_index = MI[m_glass.name]
            cap = bm.faces.new(list(reversed(d)))
        else:
            cap = bm.faces.new(list(reversed(b)))
        cap.material_index = MI[m_top.name]

    zt = -t / 2 - 0.0013
    lr = 0.0072
    for dx, dy in ((-0.0085, 0.0085), (-0.0085, -0.0085), (0.0085, 0.0)):
        disc(cx - dx, cy + dy, zt, zt - 0.0016, lr, m_ring, m_glass)
    disc(cx - 0.0085, cy + 0.0, zt, zt - 0.0003, 0.0024, m_flash, m_flash, 12, lens=False)
    disc(cx + 0.0005, cy - 0.0125, zt, zt - 0.0002, 0.0014, m_glass, m_glass, 10, lens=False)

    # Side buttons: action + volume on the left edge, the long side key on the right.
    def button(x, y, bh, side):
        bw, bd = 0.0009, 0.0032
        x0 = x + side * 0.0
        v = []
        for dy in (-bh / 2, bh / 2):
            for dz in (-bd / 2, bd / 2):
                v.append(bm.verts.new((x0, y + dy, dz)))
                v.append(bm.verts.new((x0 + side * bw, y + dy * 0.92, dz * 0.8)))
        # v index: dy(0/1)*4 + dz(0/1)*2 + out(0/1)
        q = lambda a, b, c, d: bm.faces.new((v[a], v[b], v[c], v[d]))  # noqa: E731
        fs = [q(1, 5, 7, 3), q(0, 1, 3, 2), q(4, 6, 7, 5), q(0, 4, 5, 1), q(2, 3, 7, 6)]
        for f in fs:
            f.material_index = MI[m_frame.name]
    button(-w / 2, h / 2 - 0.028, 0.006, -1)
    button(-w / 2, h / 2 - 0.042, 0.011, -1)
    button(-w / 2, h / 2 - 0.056, 0.011, -1)
    button(w / 2, h / 2 - 0.05, 0.017, 1)
    bm.normal_update()
    for f in bm.faces:  # consistent outward winding (the phone is convex-ish)
        if f.normal.dot(f.calc_center_median()) < 0 and f.material_index not in (MI[m_back.name],):
            pass
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for m in mats:
        me.materials.append(m)
    obj = link(bpy.data.objects.new(name, me))
    from lib import mesh as lmesh
    lmesh.smooth(obj, angle=35)
    lmesh.uv_smart(obj, angle=60, margin=0.01)
    lmesh.uv_fit_faces(obj, material=screen)
    return obj


def hand_frame(rig, side):
    """(wrist, F toward the knuckles, N out of the palm, T toward the thumb)."""
    wrist = rig.head[f"hand_{side}"]
    F = (rig.head[f"middle_01_{side}"] - wrist).normalized()
    N = rig.palm[side]
    N = (N - F * N.dot(F)).normalized()
    T = F.cross(N).normalized()
    if side == "l":
        T = -T
    return wrist, F, N, T


def frame_matrix(origin, X, Y, Z):
    m = Matrix.Identity(4)
    for i, v in enumerate((X, Y, Z)):
        m[0][i], m[1][i], m[2][i] = v
    m.translation = origin
    return m


# Grips: finger curls (MCP, PIP, DIP per finger), thumb (01, 02, 03), and the
# prop's frame in the hand: along F (knuckles), N (out of the palm), T (thumb),
# plus a roll of the prop about N.
GRIPS = {
    "phone": dict(curl={"index": (6, 86, 24), "middle": (8, 90, 24), "ring": (11, 92, 24), "pinky": (15, 92, 22)},
                  spread={"index": 3, "middle": 0, "ring": -3, "pinky": -7},
                  thumb=(30, 12, 8), at=(0.118, 0.022, 0.014), turn=-8, tip=(0.012, -0.016, 0.0118)),
    "tablet": dict(curl={"index": (10, 30, 12), "middle": (12, 32, 12), "ring": (14, 34, 12), "pinky": (16, 34, 12)},
                   spread={"index": 5, "middle": 0, "ring": -4, "pinky": -9},
                   thumb=(20, 5, 5), at=(0.205, 0.02, 0.0), turn=0, tip=(0.1, 0.0, 0.009)),
    "fist": dict(curl={"index": (80, 95, 55), "middle": (85, 95, 55), "ring": (88, 95, 55), "pinky": (90, 95, 50)},
                 spread={"index": 2, "middle": 0, "ring": -2, "pinky": -4}, thumb=(40, 30, 25), at=(0.06, 0.018, 0.0), turn=0,
                 tip=(0.0, 0.02, 0.018)),
    "cup": dict(curl={"index": (40, 55, 30), "middle": (44, 58, 30), "ring": (48, 60, 30), "pinky": (52, 60, 28)},
                spread={"index": 4, "middle": 0, "ring": -4, "pinky": -8}, thumb=(40, 15, 10), at=(0.07, 0.045, 0.01), turn=0,
                tip=(0.0, 0.045, 0.04)),
    "relaxed": dict(curl={"index": (18, 30, 16), "middle": (22, 34, 18), "ring": (26, 38, 18), "pinky": (30, 40, 18)},
                    spread={"index": 3, "middle": 0, "ring": -3, "pinky": -6}, thumb=(10, 8, 6), at=(0, 0, 0), turn=0),
}


def grip_matrix(rig, side, grip):
    """The prop frame (4x4, armature rest space) for a grip on hand `side`:
    X across the prop (away from the wrist), Y along it (toward the thumb),
    Z out of the palm."""
    g = GRIPS[grip]
    wrist, F, N, T = hand_frame(rig, side)
    a, b, c = g["at"]
    X = -F if side == "r" else F
    Z = N
    Y = Z.cross(X).normalized()
    R = Rax(Z, g["turn"] if side == "r" else -g["turn"]) @ Matrix((X, Y, Z)).transposed()
    origin = wrist + F * a + N * b + T * c
    return frame_matrix(origin, R.col[0], R.col[1], R.col[2])


def _rots(axis, deg):
    """Rotation matrices (k, 3, 3) about a unit axis by angles (k,) in degrees
    (right-handed, like Matrix.Rotation)."""
    a = np.radians(np.asarray(deg, np.float64))
    x, y, z = axis
    K = np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])
    return np.eye(3) + np.sin(a)[:, None, None] * K + (1 - np.cos(a))[:, None, None] * (K @ K)


def slab_sdf(p, w, h, t, r):
    """Signed distance from points (..., 3) in a prop frame to a rounded slab
    (w x h outline with corner radius r, t thick, centred): (distance, the
    distance to the outline alone)."""
    q = np.abs(p[..., :2]) - np.array([w / 2 - r, h / 2 - r])
    dxy = np.linalg.norm(np.maximum(q, 0), axis=-1) + np.minimum(q.max(axis=-1), 0) - r
    dz = np.abs(p[..., 2]) - t / 2
    o = np.stack([dxy, dz], -1)
    return np.linalg.norm(np.maximum(o, 0), axis=-1) + np.minimum(o.max(axis=-1), 0), dxy


def solve_grip(rig, src, grip, dims, wrap=True):
    """Fit a holding grip to this character's actual hand. The prop slides
    along the fingers ('at' a) and rests on the palm skin ('at' b); each
    finger's three curls are searched so its skin (linear-blend skinned like
    the game) touches the prop with every phalanx, never goes into it or
    across its screen, and (wrap) hooks its tip round the far edge. Rewrites
    GRIPS[grip] 'at' and 'curl' (the right hand is solved; the rig is
    symmetric)."""
    g = GRIPS[grip]
    w, h, t, r = dims
    side = "r"
    wrist, F, N, T = (np.array(v) for v in hand_frame(rig, side))
    n = np.array(rig.palm[side])
    co = src.co
    fingers = {}
    for f in FINGERS[1:]:
        bones = [f"{f}_0{j}_{side}" for j in (1, 2, 3)]
        idx = [i for i, wd in enumerate(src.w) if sum(wd.get(b, 0.0) for b in bones) > 0.02]
        Wt = np.array([[src.w[i].get(b, 0.0) for b in bones] for i in idx])
        heads = [np.array(rig.head[b]) for b in bones]
        axes = []
        for b in bones:
            d = np.array(rig.tail[b] - rig.head[b])
            ax = np.cross(d / np.linalg.norm(d), n)
            axes.append(ax / np.linalg.norm(ax))
        seg = [np.array([src.dom[i] == b for i in idx]) for b in bones]
        spread = _rots(n, [g["spread"][f]])[0]
        fingers[f] = (co[idx], Wt, heads, axes, seg, spread, np.array(rig.tail[bones[2]]))
    relaxed = {f: np.array(GRIPS["relaxed"]["curl"][f], np.float64) for f in FINGERS[1:]}
    moving = set(f"{f}_0{j}_{side}" for f in FINGERS for j in (1, 2, 3))
    palm = co[[i for i, wd in enumerate(src.w) if src.dom[i] == f"hand_{side}"
               and sum(v for b, v in wd.items() if b in moving) < 0.1]]
    # The thumb web (round the thumb's first knuckle) barely moves when the
    # thumb reaches over: the prop's near edge had better stay out of it.
    knuckle = np.array(rig.head[f"thumb_02_{side}"])
    web = co[[i for i in range(len(co)) if src.dom[i] in (f"thumb_01_{side}", f"thumb_02_{side}")
              and np.linalg.norm(co[i] - knuckle) < 0.015]]

    def frame(a, b):
        X = -F
        Z = N
        Y = np.cross(Z, X)
        R = np.array(Rax(Vector(Z), g["turn"]) @ Matrix((X, Y, Z)).transposed())
        return wrist + F * a + N * b + T * g["at"][2], R

    def pose(f, th):
        P, Wt, (h1, h2, h3), (a1, a2, a3), _, S, tail = fingers[f]
        D1 = S @ _rots(a1, th[:, 0])
        D12 = D1 @ _rots(a2, th[:, 1])
        D123 = D12 @ _rots(a3, th[:, 2])
        o2 = D1 @ (h2 - h1)
        o3 = o2 + D12 @ (h3 - h2)
        p1 = h1 + np.einsum("kij,vj->kvi", D1, P - h1)
        p2 = h1 + o2[:, None] + np.einsum("kij,vj->kvi", D12, P - h2)
        p3 = h1 + o3[:, None] + np.einsum("kij,vj->kvi", D123, P - h3)
        w0 = 1 - Wt.sum(1)
        skin = P * w0[:, None] + p1 * Wt[:, 0, None] + p2 * Wt[:, 1, None] + p3 * Wt[:, 2, None]
        return skin, h1 + o3 + D123 @ (tail - h3)

    def cost(f, th, o, R, parts=False):
        seg = fingers[f][4]
        skin, tip = pose(f, th)
        loc = (skin - o) @ R
        tip = (tip - o) @ R
        d, dxy = slab_sdf(loc, w, h, t, r)
        c = {}
        c["into"] = 4e6 * (np.maximum(0, -0.0005 - d) ** 2).sum(1)  # half a mm is skin give
        over = (loc[..., 2] > t / 2 - 0.001) & (dxy < -0.006)  # across the screen, past its rim
        c["screen"] = 1e5 * (np.where(over, -dxy - 0.006, 0) ** 2).sum(1)
        c["touch"] = sum(3e4 * np.maximum(0, d[:, s].min(1) - 0.0015) ** 2 for s in seg if s.any())
        c["hook"] = np.zeros(len(th))
        base = (fingers[f][2][0] - o) @ R
        if wrap and abs(base[1]) < h / 2 - 0.006:  # a finger alongside the prop hooks its far edge
            c["hook"] = 3e4 * (np.maximum(0, tip[:, 0] + w / 2) ** 2 + np.maximum(0, -t / 2 - tip[:, 2]) ** 2)
        # Anatomy (the last knuckle follows the middle one); a finger with
        # nothing to hold rests relaxed.
        c["pose"] = 1e-4 * (th[:, 2] - 0.65 * th[:, 1]) ** 2 + 1e-5 * ((th - relaxed[f]) ** 2).sum(1)
        return c if parts else sum(c.values())

    def grid(lo, hi, step):
        axes = [np.arange(l, u + 1e-6, step) for l, u in zip(lo, hi)]
        return np.stack(np.meshgrid(*axes, indexing="ij"), -1).reshape(-1, 3)

    best = None
    if wrap:  # the far edge near the middle finger's second knuckle, fingers round it
        a0 = float(np.dot(np.array(rig.head[f"middle_02_{side}"]) - wrist, F)) - w / 2
        cands = np.arange(a0 - 0.015, a0 + 0.015 + 1e-6, 0.0025)
    else:  # too wide to wrap: fingers flat on the back
        cands = [g["at"][0]]
    for a in cands:
        # The prop rests on the palm skin under it, 0.8 mm off.
        b = g["at"][1]
        for _ in range(4):
            o, R = frame(a, b)
            d, _ = slab_sdf((palm - o) @ R, w, h, t, r)
            b += 0.0008 - d.min()
        o, R = frame(a, b)
        d, _ = slab_sdf((web - o) @ R, w, h, t, r)
        total, curls, parts = 1e4 * float((np.maximum(0, -0.0005 - d) ** 2).sum()), {}, {}
        parts["web"] = total
        for f in fingers:
            th = grid((-10, 0, 0), (70, 110, 90), 10)
            c = cost(f, th, o, R)
            k = th[c.argmin()]
            th = grid(k - 7.5, k + 7.5, 2.5)
            c = cost(f, th, o, R)
            k = th[c.argmin()][None]
            curls[f] = tuple(float(v) for v in k[0])
            total += float(c.min())
            for key, v in cost(f, k, o, R, parts=True).items():
                parts[key] = parts.get(key, 0.0) + float(v[0])
        if lib.flag("gripdebug"):
            log(f"  grip a {a:.4f} b {b:.4f}: cost {total:.3f} ("
                + " ".join(f"{k} {v:.2f}" for k, v in parts.items()) + ") "
                + " ".join(f"{f}:{c[0]:.0f}/{c[1]:.0f}/{c[2]:.0f}" for f, c in curls.items()))
        if best is None or total < best[0]:
            best = (total, a, b, curls)
    total, a, b, curls = best
    g["at"] = (float(a), float(b), g["at"][2])
    g["curl"] = curls
    log(f"{CHAR}: grip {grip}: at ({a:.3f}, {b:.4f}), curls "
        + ", ".join(f"{f} {c[0]:.0f}/{c[1]:.0f}/{c[2]:.0f}" for f, c in curls.items()) + f", cost {total:.3f}")


def weigh_to(obj, bone):
    obj.vertex_groups.clear()
    vg = obj.vertex_groups.new(name=bone)
    vg.add(list(range(len(obj.data.vertices))), 1.0, "REPLACE")


def place_prop(obj, m):
    obj.data.transform(m)
    obj.matrix_world = Matrix.Identity(4)


# ================================================================ clips

def spline(keys, t, loop=False):
    """Catmull-Rom through [(t, value), ...] (values: float or tuple);
    `loop` wraps t into [0, 1) with the keys treated as periodic."""
    ts = [k[0] for k in keys]
    scalar = not isinstance(keys[0][1], (tuple, list, Vector))
    vals = [Vector((k[1], 0.0)) if scalar else Vector(k[1]) for k in keys]
    n = len(keys)
    if loop:
        t = t % 1.0
        ext_t = [ts[-1] - 1.0] + ts + [ts[0] + 1.0, ts[1] + 1.0]
        ext_v = [vals[-1]] + vals + [vals[0], vals[1]]
    else:
        t = min(max(t, ts[0]), ts[-1])
        ext_t = [ts[0] - (ts[1] - ts[0])] + ts + [ts[-1] + (ts[-1] - ts[-2])]
        ext_v = [vals[0] * 2 - vals[1]] + vals + [vals[-1] * 2 - vals[-2]]
    for i in range(1, len(ext_t) - 2):
        if ext_t[i] <= t <= ext_t[i + 1]:
            t0, t1, t2, t3 = ext_t[i - 1:i + 3]
            p0, p1, p2, p3 = ext_v[i - 1:i + 3]
            u = (t - t1) / max(t2 - t1, 1e-9)
            # Non-uniform Catmull-Rom tangents.
            m1 = (p2 - p0) / max(t2 - t0, 1e-9) * (t2 - t1)
            m2 = (p3 - p1) / max(t3 - t1, 1e-9) * (t2 - t1)
            h00, h10 = 2 * u ** 3 - 3 * u ** 2 + 1, u ** 3 - 2 * u ** 2 + u
            h01, h11 = -2 * u ** 3 + 3 * u ** 2, u ** 3 - u ** 2
            v = p1 * h00 + m1 * h10 + p2 * h01 + m2 * h11
            return v[0] if scalar else v
    v = vals[-1]
    return v[0] if scalar else v


def ease(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def lerp(a, b, t):
    return a + (b - a) * t


def rot_between(a, b):
    return Vector(a).normalized().rotation_difference(Vector(b).normalized()).to_matrix()


def slerp_m(A, B, t):
    return A.to_quaternion().slerp(B.to_quaternion(), t).to_matrix()


HOLDS = {
    # right hand holds the main screen; (forward, down, right) of its centre
    # from the void, metres; left: what the left hand does.
    "scroll": dict(phone=(0.23, 0.25, 0.04), left="free", elbow_r=(0.3, -0.25, -0.4), elbow_l=(-0.3, -0.25, -0.4)),
    "double": dict(phone=(0.28, 0.24, 0.12), left="phone", phone_l=(0.28, 0.25, -0.13), elbow_r=(0.4, -0.2, -0.3), elbow_l=(-0.4, -0.2, -0.3)),
    "tablet": dict(phone=(0.33, 0.17, 0.0), left="tablet", elbow_r=(0.35, -0.2, -0.35), elbow_l=(-0.35, -0.2, -0.35)),
    "far": dict(phone=(0.5, 0.22, 0.03), left="tablet", elbow_r=(0.3, -0.1, -0.35), elbow_l=(-0.3, -0.1, -0.35), neck_back=10),
    "selfie": dict(phone=(0.66, -0.12, 0.1), left="free", elbow_r=(0.45, -0.1, -0.35), elbow_l=(-0.2, -0.3, -0.35), stick=True),
    "sip": dict(phone=(0.27, 0.23, 0.06), left="cup", cup=(0.22, 0.3, -0.12), elbow_r=(0.25, -0.2, -0.35), elbow_l=(-0.25, -0.2, -0.35)),
}


class Animator:
    """Poses the rig from high-level intent: torso angles, pelvis offset,
    foot targets, and the screen hold (the phone kept in front of the void)."""

    def __init__(self, rig, solver, L, attach):
        self.rig, self.solver, self.L = rig, solver, L
        self.attach = attach  # {"r": (grip, G 4x4), "l": (...)} props in hand frames
        self.hold = HOLDS[C["hold"]]
        obj = rig.obj
        self.pb = obj.pose.bones
        r = rig
        self.hip = {s: r.head[f"thigh_{s}"] for s in "lr"}
        self.ankle_rest = {s: r.head[f"foot_{s}"] for s in "lr"}
        self.leg = (r.head["thigh_l"] - r.head["foot_l"]).length
        self.eye_rest = L["eye"].copy()
        self.S = self.leg / 0.80  # clips are authored for a 1.72 m adult
        # Clips put ankles at heights authored for bare feet at z = 0.067 m;
        # shoes lift the rest ankle, so the targets follow.
        self.foot_dz = (self.ankle_rest["l"].z + self.ankle_rest["r"].z) / 2 - 0.067 * self.S
        self.hand_rest = {s: Matrix(obj.data.bones[f"hand_{s}"].matrix_local) for s in "lr"}

    # ---------------------------------------------------------------- pieces

    def fingers(self, side, grip, thumb_extra=(0, 0, 0), open_=0.0):
        g = GRIPS[grip]
        rel = GRIPS["relaxed"] if open_ >= 0 else GRIPS["fist"]
        k = abs(open_)
        for f in FINGERS[1:]:
            curl = [lerp(c, r, k) for c, r in zip(g["curl"][f], rel["curl"][f])]
            for b, q in self.rig.finger_curl(side, f, curl, g["spread"][f]).items():
                self.pb[b].rotation_quaternion = q
        # The thumb is IK (hand_to / hand_free place its tip).

    def thumb(self, side, angles):
        """Thumb: 01 swings across the palm (opposition), 02/03 curl."""
        r = self.rig
        n = r.palm[side]
        for j, ang in enumerate(angles, start=1):
            b = f"thumb_0{j}_{side}"
            d = (r.tail[b] - r.head[b]).normalized()
            axis = d.cross(n).normalized()
            if j == 1:
                wrist, F, N, T = hand_frame(r, side)
                axis = F if side == "r" else -F  # roll the thumb over the palm
                axis = (axis * 0.6 + d.cross(n).normalized() * 0.4).normalized()
            self.pb[b].rotation_quaternion = r.local_q(b, Rax(axis, ang))

    def reset(self):
        for pb in self.pb:
            pb.location = (0, 0, 0)
            pb.rotation_quaternion = (1, 0, 0, 0)

    def sc(self, v):
        return Vector(v) * self.S

    def foot(self, side, pos, yaw_deg=0.0, pitch_deg=0.0, roll_deg=0.0, toe=0.0, knee=None, scaled=True):
        """Ankle target (authored for the adult: scaled to this body)."""
        if scaled:
            pos = self.sc(pos) + Vector((0, 0, self.foot_dz))
            if knee is not None:
                knee = self.sc(knee) + Vector((0, 0, self.foot_dz))
        W = Rz(yaw_deg) @ Rx(pitch_deg) @ Ry(roll_deg)
        if knee is None:
            mid = (self.hip[side] + Vector(pos)) / 2
            knee = mid + Rz(yaw_deg) @ Vector((0.06 if side == "r" else -0.06, 0.6, 0.0))
        self.solver.place(f"foot_{side}", Vector(pos), W, knee)
        self.pb[f"ball_{side}"].rotation_quaternion = self.rig.local_q(f"ball_{side}", Rx(toe))

    def hand_to(self, side, M_prop, pole, flick=0.0, raw=False):
        """Put the hand so the prop it holds sits at world frame M_prop; the
        thumb tip goes to the grip's spot on the prop (a flick scrolls it up
        the screen)."""
        grip, G = self.attach[side]
        if side == "r" and "selfie_phone" in self.attach and not raw:
            # M_prop is where the phone on the stick goes: hold the stick below it.
            M_prop = M_prop @ (G.inverted() @ self.attach["selfie_phone"]).inverted()
        M_hand = M_prop @ G.inverted() @ self.hand_rest[side]
        R = M_hand.to_3x3().normalized() @ self.rig.rest[f"hand_{side}"].inverted()
        self.solver.place(f"hand_{side}", M_hand.translation, R, pole)
        tip = Vector(GRIPS[grip].get("tip", (0, 0, 0.02)))
        if side == "l":
            tip.x = -tip.x
        if flick:
            tip += Vector((0.004, 0.026, 0.006)) * flick
        # Holding a phone, the thumb's first bone lifts out of the palm (FK)
        # so the rest of it (IK) comes over the phone's edge, not through it.
        lift = GRIPS[grip].get("thumb_lift", 0.0)
        r = self.rig
        b = f"thumb_01_{side}"
        d = (r.tail[b] - r.head[b]).normalized()
        self.pb[b].rotation_quaternion = r.local_q(b, Rax(d.cross(r.palm[side]), lift)) if lift else Quaternion()
        for c in self.pb[f"thumb_03_{side}"].constraints:
            if c.type == "IK":
                c.chain_count = 2 if lift else 3
        self.solver.thumb(side, M_prop @ tip)
        self.M_hand = M_hand

    def thumb_relaxed(self, side, M_hand):
        """Thumb tip where a relaxed thumb rests, in the hand's current frame."""
        r = self.rig
        wrist, F, N, T = hand_frame(r, side)
        tip_rest = r.tail[f"thumb_03_{side}"] + N * 0.012 + F * 0.01
        rest = self.hand_rest[side]
        self.pb[f"thumb_01_{side}"].rotation_quaternion = Quaternion()
        for c in self.pb[f"thumb_03_{side}"].constraints:
            if c.type == "IK":
                c.chain_count = 3
        self.solver.thumb(side, M_hand @ (rest.inverted() @ tip_rest))

    def hand_free(self, side, pos, W, pole):
        self.solver.place(f"hand_{side}", Vector(pos), W, pole)
        M = (W @ self.rig.rest[f"hand_{side}"]).to_4x4()
        M.translation = Vector(pos)
        self.thumb_relaxed(side, M)

    swing = None
    sip = 0.0

    def free_hand(self, side, P, fwd, right, swing=None):
        """The hand that holds nothing: hanging relaxed, or (swing -1..1) a
        runner's arm, elbow at ~90 degrees, pumping fore and aft."""
        sgn = 1 if side == "r" else -1
        sh = self.rig.world_point(self.W, P, f"clavicle_{side}", self.rig.tail[f"clavicle_{side}"])
        out = right * sgn
        fwd, right = fwd * self.S, right * self.S
        out = out * self.S
        if swing is None:
            c = sh + fwd * 0.06 - Vector((0, 0, 0.56 * self.S)) + out * 0.05
            fingers = fwd * 0.15 - Vector((0, 0, 1)) + out * 0.05
            palm = -out
            pole = sh + fwd * -0.3 - Vector((0, 0, 0.25)) + out * 0.2
            open_ = 0.0
        else:
            c = sh + fwd * (0.08 + 0.24 * swing) - Vector((0, 0, (0.44 - 0.12 * max(0.0, swing)) * self.S)) + out * (0.05 - 0.04 * max(0.0, swing))
            fingers = fwd * (0.7 + 0.3 * swing) - Vector((0, 0, 0.4)) - out * 0.3
            palm = -out + Vector((0, 0, 0.3))
            pole = sh - fwd * 0.4 - Vector((0, 0, 0.25)) + out * 0.25
            open_ = -0.6
        self.hand_aim(side, c, fingers, palm, pole)
        self.fingers(side, "relaxed", open_=open_)

    def hand_aim(self, side, pos, fingers_dir, palm_dir, pole):
        """Hand at pos with its fingers along fingers_dir and palm facing palm_dir."""
        wrist, F, N, T = hand_frame(self.rig, side)
        F2 = Vector(fingers_dir).normalized()
        N2 = Vector(palm_dir)
        N2 = (N2 - F2 * N2.dot(F2)).normalized()
        rest = Matrix((F, N, F.cross(N))).transposed()
        tgt = Matrix((F2, N2, F2.cross(N2))).transposed()
        self.hand_free(side, pos, tgt @ rest.inverted(), pole)

    # ---------------------------------------------------------------- the pose

    def pose(self, D, pelvis_off=Vector(), look=1.0, screen=None, flick=0.0, arms=None, left=None,
             neck=0.0, head_extra=I3, fingers_open=0.0):
        """D: {bone: 3x3} for pelvis/spine/clavicles; screen: override of the
        hold's (forward, down, right); arms(W, P, eye, M_phone) may replace
        the hold entirely (returns nothing, places the hands itself)."""
        rig, hold = self.rig, self.hold
        D = dict(D)
        D.setdefault("neck_01", pitch(neck))
        pelvis_off = self.sc(pelvis_off)
        W, P = rig.fk(D, pelvis_off)
        # Provisional eye, then the screen in front of it (in the chest's yaw).
        eye = rig.world_point(W, P, "head", self.eye_rest)
        chest = W["spine_03"]
        fwd = chest @ Vector((0, 1, 0))
        fwd.z = 0
        fwd = fwd.normalized() if fwd.length > 1e-6 else Vector((0, 1, 0))
        right = fwd.cross(Vector((0, 0, 1))).normalized()
        f_, d_, r_ = [x * (0.5 + 0.5 * self.S) for x in (screen if screen is not None else hold["phone"])]
        target = eye + fwd * f_ - Vector((0, 0, d_)) + right * r_
        # The neck takes a third of the turn toward the screen, the head the rest.
        to_t = (target - eye).normalized()
        face = W["head"] @ Vector((0, 1, 0))
        R1 = slerp_m(I3, rot_between(face, to_t), 0.33 * look)
        W3 = W["spine_03"]
        D["neck_01"] = W3.inverted() @ R1 @ W3 @ D["neck_01"]
        W, P = rig.fk(D, pelvis_off)
        eye = rig.world_point(W, P, "head", self.eye_rest)
        to_t = (target - eye).normalized()
        Wn = W["neck_01"]
        face = Wn @ Vector((0, 1, 0))
        R2 = slerp_m(I3, rot_between(face, to_t), look)
        D["head"] = Wn.inverted() @ R2 @ Wn @ head_extra
        W, P = rig.fk(D, pelvis_off)
        eye = rig.world_point(W, P, "head", self.eye_rest)
        # Channels.
        for b in TORSO_CHAIN:
            self.pb[b].rotation_quaternion = rig.local_q(b, D.get(b, I3))
        self.pb["pelvis"].location = rig.rest["pelvis"].inverted() @ pelvis_off
        # The screen faces the void, its long side up (tilted with the look).
        n = (eye - target).normalized()
        up = Vector((0, 0, 1))
        up = (up - n * up.dot(n)).normalized()
        xax = up.cross(n).normalized()
        M_phone = frame_matrix(target, xax, up, n)
        self.M_phone, self.W, self.P, self.eye = M_phone, W, P, eye
        if arms is not None:
            arms(W, P, eye, M_phone)
        else:
            self.default_arms(W, P, eye, M_phone, flick, left, fwd, right)
        return W, P

    def default_arms(self, W, P, eye, M_phone, flick, left, fwd, right):
        hold = self.hold
        er = Vector(hold["elbow_r"])
        el = Vector(hold["elbow_l"])
        chest = P["spine_03"]
        pole_r = chest + right * er.x + fwd * er.y + Vector((0, 0, er.z))
        pole_l = chest + right * el.x + fwd * el.y + Vector((0, 0, el.z))
        self.hand_to("r", M_phone, pole_r, flick)
        grip_r = self.attach["r"][0]
        self.fingers("r", grip_r)
        mode = left or hold["left"]
        if mode == "phone":
            f_, d_, r_ = hold["phone_l"]
            tgt = eye + fwd * f_ - Vector((0, 0, d_)) + right * r_
            n = (eye - tgt).normalized()
            up = Vector((0, 0, 1))
            up = (up - n * up.dot(n)).normalized()
            M = frame_matrix(tgt, up.cross(n).normalized(), up, n)
            self.hand_to("l", M, pole_l)
            self.fingers("l", self.attach["l"][0])
        elif mode == "tablet":
            # The left hand holds the tablet's left edge (a second grip on it).
            self.hand_to("l", M_phone, pole_l)
            self.fingers("l", "tablet")
        elif mode == "cup":
            f_, d_, r_ = [x * self.S for x in hold["cup"]]
            tgt = eye + fwd * f_ - Vector((0, 0, d_)) + right * r_
            M = frame_matrix(tgt, fwd, Vector((0, 0, 1)), right)
            if self.sip:
                # A sip: the cup comes up to the void and tips toward it.
                k = ease(self.sip)
                mouth = eye + fwd * 0.1 * self.S - Vector((0, 0, 0.07 * self.S)) - right * 0.01
                R = Rax(right, 35 * k) @ M.to_3x3()
                M = R.to_4x4()
                M.translation = tgt.lerp(mouth, k)
            self.hand_to("l", M, pole_l)
            self.fingers("l", "cup")
        elif mode == "under":
            # Cradling the phone's lower left corner: fingers up along its
            # left edge, palm toward its back.
            px, py, pz = M_phone.col[0].xyz, M_phone.col[1].xyz, M_phone.col[2].xyz
            c = M_phone.translation - px * 0.07 - py * 0.1 - pz * 0.025
            self.hand_aim("l", c, px * 0.55 + py * 0.8, pz * 0.8 + px * 0.4, pole_l)
            self.fingers("l", "cup", open_=0.35)
        else:  # free: hangs, or pumps when running
            self.free_hand("l", P, fwd, right, self.swing)


def clip_run(A, f, n=16):
    """One full stride: right touchdown at 0, left at 0.5. Sprint mechanics
    (forward lean, knee drive, heel recovery, pelvis bob/sway/yaw, spine
    counter-rotation) while the phone never leaves the face."""
    ph = f / n
    drop = 0.07  # a runner is lower than standing
    bob = -drop + 0.028 * math.cos(4 * math.pi * (ph - 0.4))
    sway = 0.012 * math.cos(2 * math.pi * (ph - 0.12))
    yw = 9.0 * math.cos(2 * math.pi * ph)
    rl = -4.0 * math.sin(2 * math.pi * (ph + 0.13))
    lean = 12.0 + 1.5 * math.cos(4 * math.pi * (ph - 0.25))
    D = {
        "pelvis": yaw(yw) @ roll(rl) @ pitch(lean * 0.55),
        "spine_01": yaw(-yw * 0.45) @ roll(-rl * 0.5) @ pitch(4),
        "spine_02": yaw(-yw * 0.45) @ pitch(5),
        "spine_03": yaw(-yw * 0.3) @ pitch(8),
        "clavicle_l": Rx(2 * math.sin(2 * math.pi * ph)),
        "clavicle_r": I3,
    }
    off = Vector((sway, -0.02, bob))
    # Foot paths relative to the root (y forward, z ankle height).
    stance_end = 0.32
    swing = [(0.32, (-0.38, 0.1)), (0.43, (-0.43, 0.3)), (0.55, (-0.24, 0.5)), (0.68, (0.1, 0.46)),
             (0.8, (0.36, 0.28)), (0.91, (0.36, 0.13)), (1.0, (0.27, 0.078))]
    pitches = [(0.0, 8), (0.1, 0), (0.2, -8), (0.32, -30), (0.45, -62), (0.6, -35), (0.75, -5),
               (0.88, 12), (1.0, 8)]
    for side, sh in (("r", 0.0), ("l", 0.5)):
        p_ = (ph + sh) % 1.0
        if p_ < stance_end:
            k = p_ / stance_end
            y = lerp(0.27, -0.38, k)
            z = 0.085 + 0.03 * max(0.0, k - 0.55) / 0.45
        else:
            y, z = spline(swing, p_)
        x = 0.1 if side == "r" else -0.1
        toe = 30 * smoothstep(0.18, 0.32, p_) * (1 - smoothstep(0.32, 0.45, p_))
        A.foot(side, (x, y, z), yaw_deg=(-4 if side == "r" else 4), pitch_deg=spline(pitches, p_, loop=True), toe=toe)
    flick = max(0.0, math.sin(2 * math.pi * ph * 2)) ** 3  # two flicks per stride
    A.swing = math.cos(2 * math.pi * ph)  # the free arm opposes the left leg
    A.pose(D, off, flick=flick, neck=6)
    A.swing = None


def clip_idle(A, f, n=60):
    ph = f / n
    breathe = math.sin(2 * math.pi * ph)
    shift = 0.012 * math.sin(2 * math.pi * ph)
    D = {
        "pelvis": roll(1.5 * math.sin(2 * math.pi * ph)) @ pitch(-2),
        "spine_01": pitch(1 + 0.5 * breathe),
        "spine_02": pitch(3 + 0.6 * breathe),
        "spine_03": pitch(8 + 0.8 * breathe),
    }
    off = Vector((shift, 0.0, -0.012 - 0.004 * breathe))
    A.foot("r", (0.12, 0.03, 0.068), yaw_deg=-8, pitch_deg=0)
    A.foot("l", (-0.12, -0.03, 0.068), yaw_deg=10, pitch_deg=0)
    # Three flicks of the thumb, a pause, one more.
    fl = 0.0
    for c in (0.12, 0.3, 0.45, 0.8):
        fl = max(fl, math.exp(-((ph - c) / 0.035) ** 2))
    A.sip = smoothstep(0.52, 0.62, ph) * (1 - smoothstep(0.72, 0.82, ph))
    A.pose(D, off, flick=fl, neck=16)
    A.sip = 0.0


def clip_jump(A, f, n=20):
    t = f / n
    tuck = spline([(0, 0.0), (0.2, 0.6), (0.5, 1.0), (0.75, 0.7), (1.0, 0.15)], t)
    D = {"pelvis": pitch(10 + 8 * tuck), "spine_01": pitch(6 + 6 * tuck), "spine_02": pitch(5 + 5 * tuck), "spine_03": pitch(8)}
    off = Vector((0, -0.02, -0.06 + 0.02 * tuck))
    # Right leg drove off the ground, left trails, then both tuck and reach down.
    ry, rz = spline([(0, (0.1, 0.35)), (0.3, (0.18, 0.5)), (0.55, (0.15, 0.52)), (0.8, (0.12, 0.35)), (1.0, (0.12, 0.12))], t)
    ly, lz = spline([(0, (-0.35, 0.2)), (0.3, (-0.15, 0.4)), (0.55, (0.02, 0.48)), (0.8, (0.05, 0.3)), (1.0, (0.02, 0.1))], t)
    A.foot("r", (0.1, ry, rz), pitch_deg=spline([(0, -20), (0.5, -30), (1.0, 5)], t), yaw_deg=-4)
    A.foot("l", (-0.1, ly, lz), pitch_deg=spline([(0, -60), (0.5, -35), (1.0, 0)], t), yaw_deg=4)
    A.pose(D, off, neck=8)


def clip_fall(A, f, n=12):
    ph = f / n
    w = math.sin(2 * math.pi * ph)
    D = {"pelvis": pitch(4), "spine_01": pitch(2), "spine_02": pitch(2 + w), "spine_03": pitch(4)}
    off = Vector((0, 0, -0.02))
    A.foot("r", (0.11, 0.1 + 0.06 * w, 0.2 - 0.04 * w), pitch_deg=-25, yaw_deg=-4)
    A.foot("l", (-0.11, -0.06 - 0.06 * w, 0.25 + 0.04 * w), pitch_deg=-40, yaw_deg=4)
    A.pose(D, off, neck=4, screen=(0.3, 0.2, 0.05))


def clip_land(A, f, n=8):
    t = f / n
    squat = spline([(0, 0.2), (0.35, 1.0), (1.0, 0.25)], t)
    D = {"pelvis": pitch(10 + 18 * squat), "spine_01": pitch(4 + 6 * squat), "spine_02": pitch(4 + 4 * squat), "spine_03": pitch(8)}
    off = Vector((0, -0.04 * squat, -0.04 - 0.24 * squat))
    A.foot("r", (0.12, 0.08, 0.075), pitch_deg=0, yaw_deg=-6)
    A.foot("l", (-0.12, -0.08, 0.075), pitch_deg=0, yaw_deg=6)
    A.pose(D, off, neck=8)


def clip_roll(A, f, n=18):
    """Knee slide under a barrier: drop onto the left shin, right leg out in
    front, lean back, phone held up over the chest."""
    t = f / n
    k = spline([(0, 0.0), (0.22, 1.0), (0.78, 1.0), (1.0, 0.1)], t)
    lean = -38 * k
    D = {"pelvis": pitch(lean * 0.4) @ yaw(-12 * k), "spine_01": pitch(lean * 0.2), "spine_02": pitch(lean * 0.15 + 4 * k),
         "spine_03": pitch(lean * 0.1 + 8 * k)}
    off = Vector((0, -0.05 * k, -0.44 * k - 0.05 * (1 - k)))
    A.foot("r", (lerp(0.1, 0.12, k), lerp(0.1, 0.6, k), lerp(0.078, 0.085, k)), pitch_deg=lerp(0, 30, k), yaw_deg=-8)
    # Left leg folded under: shin skimming the ground, foot behind the pelvis.
    A.foot("l", (lerp(-0.1, -0.13, k), lerp(-0.1, -0.5, k), lerp(0.078, 0.17, k)), pitch_deg=lerp(0, -75, k), yaw_deg=10,
           knee=Vector((-0.2, 0.3, 0.3)))
    A.pose(D, off, neck=lerp(8, -4, k), screen=(lerp(0.27, 0.34, k), lerp(0.23, 0.02, k), 0.05))


def clip_grind(A, f, n=24):
    """Surf stance on a rail: side-on (facing +X), knees bent, left arm out,
    the phone out in the right hand, the void still on it."""
    ph = f / n
    w = math.sin(2 * math.pi * ph)
    D = {"pelvis": yaw(-62) @ pitch(6) @ roll(2 * w), "spine_01": yaw(12) @ pitch(4), "spine_02": yaw(12) @ pitch(4),
         "spine_03": yaw(14) @ pitch(8 + 2 * w)}
    off = Vector((0.0, 0.0, -0.13 + 0.015 * w))
    A.foot("l", (0.0, 0.25, 0.075), yaw_deg=-80, pitch_deg=0, knee=Vector((0.4, 0.3, 0.45)))
    A.foot("r", (0.0, -0.25, 0.075), yaw_deg=-75, pitch_deg=0, knee=Vector((0.4, -0.3, 0.45)))

    def arms(W, P, eye, M_phone):
        fwd = Vector((0, 1, 0))
        A.hand_to("r", M_phone, P["spine_03"] + Vector((0.3, 0.3, -0.35)))
        A.fingers("r", A.attach["r"][0])
        sh = P["clavicle_l"]
        c = sh + A.sc((-0.1, 0.45, 0.05 + 0.04 * w))  # out for balance (to the front: +Y is ahead)
        if A.attach["l"][0] in ("cup", "phone"):
            # Whatever the left hand holds stays upright out there.
            M = frame_matrix(c, Vector((0, 1, 0)), Vector((0, 0, 1)), Vector((1, 0, 0)))
            if A.attach["l"][0] == "phone":
                M = frame_matrix(c, Vector((1, 0, 0)), Vector((0, 0, 1)), Vector((0, -1, 0)))
            A.hand_to("l", M, sh + Vector((-0.3, 0.1, -0.3)))
            A.fingers("l", A.attach["l"][0])
        else:
            A.hand_free("l", c, W["spine_03"] @ Rz(80) @ Ry(20), sh + Vector((-0.3, 0.1, -0.3)))
            A.fingers("l", "relaxed")

    A.pose(D, off, neck=6, screen=(0.32, 0.18, 0.1), arms=arms if A.hold["left"] != "tablet" else None)


def clip_fly(A, f, n=24):
    """Jetpack: body pitched forward, legs trailing, phone up."""
    ph = f / n
    w = math.sin(2 * math.pi * ph)
    D = {"pelvis": pitch(38 + 2 * w), "spine_01": pitch(2), "spine_02": pitch(-4), "spine_03": pitch(-6)}
    off = Vector((0, 0, 0.0 + 0.02 * w))
    hz = A.hip["r"].z / A.S
    A.foot("r", (0.1, -0.42 - 0.03 * w, hz - 0.62), pitch_deg=-70, yaw_deg=-4, knee=Vector((0.15, 0.3, hz - 0.5)))
    A.foot("l", (-0.1, -0.36 + 0.03 * w, hz - 0.55), pitch_deg=-60, yaw_deg=4, knee=Vector((-0.15, 0.3, hz - 0.4)))
    A.pose(D, off, neck=-12, screen=(0.3, 0.12, 0.05))


def clip_stumble(A, f, n=12):
    """A side bump: lurch to the right, a catching step, recover."""
    t = f / n
    k = spline([(0, 0.0), (0.25, 1.0), (0.6, 0.6), (1.0, 0.0)], t)
    D = {"pelvis": roll(10 * k) @ yaw(-6 * k) @ pitch(8), "spine_01": roll(-6 * k) @ pitch(3), "spine_02": roll(-6 * k) @ pitch(4),
         "spine_03": roll(-4 * k) @ pitch(8 + 6 * k)}
    off = Vector((0.08 * k, -0.02, -0.07 - 0.04 * k))
    step = spline([(0, (0.1, 0.1, 0.078)), (0.3, (0.3, 0.05, 0.18)), (0.55, (0.34, 0.02, 0.078)), (1.0, (0.12, 0.05, 0.078))], t)
    A.foot("r", step, yaw_deg=-10, pitch_deg=0)
    A.foot("l", (-0.1, -0.1, 0.078), yaw_deg=6, pitch_deg=-10 * k, toe=15 * k)
    A.pose(D, off, neck=8, screen=(0.27, 0.23 - 0.05 * k, 0.045 + 0.08 * k))


def clip_kicks(A, f, n=22):
    """Front flip: take-off, tuck, a full forward turn round the hips, open."""
    t = f / n
    ang = 360.0 * ease((t - 0.08) / 0.84)
    tuck = spline([(0, 0.0), (0.15, 0.7), (0.3, 1.0), (0.7, 1.0), (0.88, 0.5), (1.0, 0.1)], t)
    com = Vector((0, 0.0, A.hip["r"].z + 0.05 * A.S))
    R = pitch(ang)
    pel_rest = A.rig.head["pelvis"]
    off = (com + R @ (pel_rest - com) - pel_rest) / A.S + Vector((0, 0, 0.1 * tuck))
    D = {"pelvis": R @ pitch(18 * tuck), "spine_01": pitch(12 * tuck), "spine_02": pitch(10 * tuck), "spine_03": pitch(10 + 6 * tuck)}
    # Feet in the flipping frame: tucked to the butt, then reaching down.
    S = A.S

    def fp(x, y, z):
        return com + R @ (Vector((x * S, y * S, z)) - com) + Vector((0, 0, 0.1 * tuck * S))
    ky = lerp(0.1, 0.22, tuck)
    kz = lerp(0.1 * S, A.hip["r"].z - 0.3 * S, tuck)
    A.foot("r", fp(0.1, ky, kz), pitch_deg=-10, yaw_deg=-4, knee=fp(0.12, 0.8, A.hip["r"].z), scaled=False)
    A.foot("l", fp(-0.1, ky - 0.03, kz + 0.02 * S), pitch_deg=-10, yaw_deg=4, knee=fp(-0.12, 0.8, A.hip["r"].z), scaled=False)
    # The footing rotation follows the flip (ankles keep their angle to the shin).
    for s in "lr":
        tgt = A.solver.t[f"foot_{s}"]
        m = tgt.matrix_world.copy()
        rot = (R @ m.to_3x3()).to_4x4()
        rot.translation = m.translation
        tgt.matrix_world = rot
    A.pose(D, off, neck=10, screen=(0.24, 0.24, 0.04), look=1.0)


def clip_present(A, f, n=36):
    """Death: the dopamine is gone. The arms drop, the head comes up."""
    t = ease(f / n)
    D = {"pelvis": pitch(lerp(2, 0, t)), "spine_01": pitch(lerp(3, 0, t)), "spine_02": pitch(lerp(4, -1, t)),
         "spine_03": pitch(lerp(9, -2, t))}
    off = Vector((0, 0, lerp(-0.012, 0.0, t)))
    A.foot("r", (0.12, 0.03, 0.068), yaw_deg=-8)
    A.foot("l", (-0.12, -0.03, 0.068), yaw_deg=10)

    def arms(W, P, eye, M_phone):
        fwd, right = Vector((0, 1, 0)), Vector((1, 0, 0))
        # The phone sinks from the face to the thigh, screen turned in; the
        # other hand falls to the side.
        sh = A.rig.world_point(W, P, "clavicle_r", A.rig.tail["clavicle_r"])
        start = M_phone
        raw = False
        if "selfie_phone" in A.attach:
            # The stick comes down with the arm and hangs from the fist.
            G = A.attach["r"][1]
            start = M_phone @ (G.inverted() @ A.attach["selfie_phone"]).inverted()
            ax = Vector((0.0, 0.35, -1.0)).normalized()
            low = frame_matrix(sh + A.sc((0.04, 0.05, -0.6)), ax.cross(Vector((-1, 0, 0))).normalized(), ax, Vector((-1, 0, 0)))
            raw = True
        else:
            low = frame_matrix(sh + A.sc((0.03, 0.07, -0.66)), Vector((0, 0, 1)), Vector((0, 1, 0)), Vector((-1, 0, 0)))
        pos = start.translation.lerp(low.translation, t)
        R = slerp_m(start.to_3x3().normalized(), low.to_3x3().normalized(), t)
        m = R.to_4x4()
        m.translation = pos
        A.hand_to("r", m, sh + Vector((0.25, -0.3, -0.3)), raw=raw)
        A.fingers("r", A.attach["r"][0])
        mode = A.hold["left"]
        if mode in ("phone", "cup") and A.attach["l"][0] != "relaxed":
            tl = A.M_left if hasattr(A, "M_left") else m
            shl = A.rig.world_point(W, P, "clavicle_l", A.rig.tail["clavicle_l"])
            lowl = frame_matrix(shl + A.sc((-0.03, 0.07, -0.66)), Vector((0, 0, -1)), Vector((0, 1, 0)), Vector((1, 0, 0)))
            if A.attach["l"][0] == "cup":  # the cup hangs upright by the thigh
                lowl = frame_matrix(shl + A.sc((-0.04, 0.1, -0.62)), Vector((0, 1, 0)), Vector((0, 0, 1)), Vector((1, 0, 0)))
            A.hand_to("l", lowl, shl + Vector((-0.25, -0.3, -0.3)))
            A.fingers("l", A.attach["l"][0])
        else:
            A.free_hand("l", P, fwd, right, None)

    # The look drifts off the screen to straight ahead (slightly up).
    A.pose(D, off, neck=lerp(10, -4, t), look=1.0 - t, arms=arms, head_extra=pitch(-6 * t))


CLIPS = [("run", 16, True, clip_run), ("idle", 60, True, clip_idle), ("jump", 20, False, clip_jump),
         ("fall", 12, True, clip_fall), ("land", 8, False, clip_land), ("roll", 18, False, clip_roll),
         ("grind", 24, True, clip_grind), ("fly", 24, True, clip_fly), ("stumble", 12, False, clip_stumble),
         ("kicks", 22, False, clip_kicks), ("present", 36, False, clip_present)]


def animate(rig, solver, L, attach):
    A = Animator(rig, solver, L, attach)
    for name, n, loop, fn in CLIPS:
        def pose_fn(f, fn=fn, n=n):
            A.reset()
            fn(A, f, n)
        bake_clip(rig, solver, name, n, pose_fn, loop=loop)
    return A


# ================================================================ equip

def bone_child(obj, rig_obj, bone, M):
    obj.parent = rig_obj
    obj.parent_type = "BONE"
    obj.parent_bone = bone
    bpy.context.view_layer.update()
    obj.matrix_world = M


def attach_mesh(obj, rig_obj, bone):
    weigh_to(obj, bone)
    obj.parent = rig_obj
    obj.modifiers.new("Armature", "ARMATURE").object = rig_obj


def p_phone(rig, rig_obj, attach, pieces, side="r", screen="Screen", colors=None, name="phone", grip="phone", light=True):
    ph = build_phone(name, screen=screen, colors=colors or C.get("phone"))
    G = grip_matrix(rig, side, grip)
    place_prop(ph, G)
    attach_mesh(ph, rig_obj, f"hand_{side}")
    attach[side] = (grip, G)
    pieces.append(ph)
    if light:
        e = link(bpy.data.objects.new("PhoneLight", None))
        e.empty_display_size = 0.02
        bone_child(e, rig_obj, f"hand_{side}", G @ Matrix.Translation((0, 0, 0.025)))
    return ph


# ---------------------------------------------------------------- shapes

def mesh_from(name, bm, material=None):
    me = bpy.data.meshes.new(name)
    bm.normal_update()
    bm.to_mesh(me)
    bm.free()
    if material is not None:
        me.materials.append(material)
    o = link(bpy.data.objects.new(name, me))
    for p in me.polygons:
        p.use_smooth = True
    return o


def torus(name, centre, R, r, normal=(0, 0, 1), seg=40, sides=10, material=None, arc=1.0):
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new("UVMap")
    n = Vector(normal).normalized()
    a = n.orthogonal().normalized()
    b = n.cross(a)
    closed = arc >= 0.999
    cnt = seg if closed else seg + 1
    rings = []
    for i in range(cnt):
        t = 2 * math.pi * arc * i / seg
        d = a * math.cos(t) + b * math.sin(t)
        c = Vector(centre) + d * R
        rings.append([bm.verts.new(c + (d * math.cos(2 * math.pi * k / sides) + n * math.sin(2 * math.pi * k / sides)) * r)
                      for k in range(sides)])
    for i in range(cnt if closed else cnt - 1):
        i2 = (i + 1) % cnt
        for k in range(sides):
            k2 = (k + 1) % sides
            f = bm.faces.new((rings[i][k], rings[i2][k], rings[i2][k2], rings[i][k2]))
            for lp, (u, v) in zip(f.loops, ((i, k), (i + 1, k), (i + 1, k + 1), (i, k + 1))):
                lp[uv].uv = (u / seg, v / sides)
    if not closed:
        bm.faces.new(rings[0])
        bm.faces.new(rings[-1][::-1])
    return mesh_from(name, bm, material)


def rbox(name, size, centre, bevel=0.005, material=None, rot=None, segments=3):
    from lib import mesh as lmesh
    o = lmesh.box(name, size, (0, 0, 0), bevel=bevel, segments=segments)
    m = (rot.to_4x4() if rot is not None else Matrix.Identity(4))
    m.translation = Vector(centre)
    o.data.transform(m)
    o.location = (0, 0, 0)
    if material is not None:
        o.data.materials.append(material)
    for p in o.data.polygons:
        p.use_smooth = True
    lmesh.smooth(o, angle=40)
    return o


def cyl(name, a, b, r, material=None, verts=16, r2=None):
    """Cylinder from point a to point b."""
    a, b = Vector(a), Vector(b)
    from lib import mesh as lmesh
    o = lmesh.cylinder(name, radius=r, depth=(b - a).length, verts=verts, radius2=r2)
    m = (Vector((0, 0, 1)).rotation_difference((b - a).normalized())).to_matrix().to_4x4()
    m.translation = (a + b) / 2
    o.data.transform(m)
    o.location = (0, 0, 0)
    if material is not None:
        o.data.materials.append(material)
    lmesh.smooth(o, angle=40)
    return o


def dome(name, centre, rx, ry, rz, cut, seg=36, rings=12, material=None, squash_back=1.0):
    """Ellipsoid cap down to a rim whose height (relative to centre) is
    cut(azimuth direction) - cap and beanie crowns. Returns (obj, rim verts)."""
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new("UVMap")
    c = Vector(centre)
    tip = bm.verts.new(c + Vector((0, 0, rz)))
    V = []
    for j in range(1, rings + 1):
        row = []
        for i in range(seg):
            az = 2 * math.pi * i / seg
            dh = Vector((math.sin(az), math.cos(az), 0.0))
            ryy = ry if dh.y > 0 else ry * squash_back
            el0 = math.asin(max(-0.95, min(0.95, cut(dh) / rz)))
            el = lerp(math.pi / 2, el0, j / rings)
            row.append(bm.verts.new(c + Vector((rx * math.cos(el) * dh.x, ryy * math.cos(el) * dh.y, rz * math.sin(el)))))
        V.append(row)
    for i in range(seg):
        bm.faces.new((tip, V[0][i], V[0][(i + 1) % seg]))
    for j in range(rings - 1):
        for i in range(seg):
            i2 = (i + 1) % seg
            f = bm.faces.new((V[j][i], V[j + 1][i], V[j + 1][i2], V[j][i2]))
            for lp, (u, v) in zip(f.loops, ((i, j), (i, j + 1), (i + 1, j + 1), (i + 1, j))):
                lp[uv].uv = (u / seg, v / rings)
    bm.normal_update()
    for f in bm.faces:
        if f.normal.dot(f.calc_center_median() - c) < 0:
            f.normal_flip()
    rim = [type("V", (), {"co": v.co.copy()})() for v in V[-1]]
    obj = mesh_from(name, bm, material)
    return obj, rim


def hug_skull(obj, c, src, lift):
    """Push a hat's verts out so they clear the skull by `lift` everywhere
    (an ellipsoid alone sinks into the forehead). Returns its new rim."""
    for v in obj.data.vertices:
        d = v.co - c
        if d.length < 1e-6:
            continue
        dn = d.normalized()
        hit = src.tree.ray_cast(c + dn * 0.4, -dn, 0.4)[0]
        if hit is not None:
            r = (hit - c).length + lift
            if r > d.length:
                v.co = c + dn * r
    obj.data.update()


def head_fit(L, lift=0.0):
    """Centre and radii of a hat that sits on this skull."""
    hc = L["head_c"]
    c = Vector((0.0, hc.y - 0.004, hc.z))
    rx = L["ear_x"] - 0.004 + lift
    ry = (L["eye"].y - hc.y) + 0.012 + lift
    ryb = (hc.y - L["head_lo"].y) + lift
    rz = L["top"] - hc.z + lift
    return c, rx, ry, ryb, rz


def on_head(o, rig_obj):
    attach_mesh(o, rig_obj, "head")
    return o


# ---------------------------------------------------------------- props

def p_phone2(rig, rig_obj, attach, pieces, L, src, side="l", screen="ScreenAlt"):
    return p_phone(rig, rig_obj, attach, pieces, side=side, screen=screen, name="phone_l", light=False)


def p_phone_news2(rig, rig_obj, attach, pieces, L, src):
    """A second phone fanned behind the first in the same (left) hand."""
    ph = build_phone("phone_l2", screen="ScreenNews", colors=C.get("phone"))
    G = grip_matrix(rig, "l", "phone")
    M = G @ Matrix.Translation((0.012, 0.018, -0.0095)) @ Rz(14).to_4x4()
    place_prop(ph, M)
    attach_mesh(ph, rig_obj, "hand_l")
    pieces.append(ph)


PROP_DIMS = {"phone": (0.0765, 0.1605, 0.0082, 0.0105), "tablet": (0.25, 0.178, 0.0064, 0.016)}  # w, h, t, corner


def p_tablet(rig, rig_obj, attach, pieces, L, src, grip="tablet"):
    w, h, t, r = PROP_DIMS["tablet"]
    tb = build_phone("tablet", w=w, h=h, t=t, r=r, colors=C.get("phone"))
    tb.data.transform(Rz(0).to_4x4())
    G = grip_matrix(rig, "r", grip)
    place_prop(tb, G)
    attach_mesh(tb, rig_obj, "hand_r")
    attach["r"] = (grip, G)
    attach["l"] = (grip, grip_matrix(rig, "l", grip))
    pieces.append(tb)
    e = link(bpy.data.objects.new("PhoneLight", None))
    bone_child(e, rig_obj, "hand_r", G @ Matrix.Translation((0, 0, 0.03)))


def selfie_frames(rig, side="r", length=0.52):
    G = grip_matrix(rig, side, "fist")
    # The phone at the stick's top, turned back at the holder, portrait.
    X, Y, Z = G.col[0].xyz, G.col[1].xyz, G.col[2].xyz
    # The stick runs down the back of the phone toward the holder: from the
    # phone, the hand is 'down' along the phone and a bit toward its screen.
    up = (Y * 0.8 + Z * 0.6).normalized()
    n = (-Y * 0.6 + Z * 0.8).normalized()
    top = G.translation + Y * length
    ph = frame_matrix(top + n * 0.012, up.cross(n).normalized(), up, n)
    return G, ph, top


def p_selfie(rig, rig_obj, attach, pieces, L, src, ring=False):
    G, ph_m, top = selfie_frames(rig)
    base = G.translation
    Y = G.col[1].xyz
    m_metal = prop_mat("stick", "#2a2b30", rough=0.35, metal=1.0)
    m_grip = prop_mat("stick_grip", "#111114", rough=0.8)
    parts = [cyl("stick_grip", base - Y * 0.06, base + Y * 0.05, 0.013, m_grip, 16),
             cyl("stick1", base + Y * 0.05, base + Y * 0.22, 0.0085, m_metal, 12),
             cyl("stick2", base + Y * 0.22, base + Y * 0.38, 0.0072, m_metal, 12),
             cyl("stick3", top - Y * 0.14, top, 0.006, m_metal, 12)]
    # A clamp holding the phone.
    clamp = rbox("clamp", (0.03, 0.09, 0.012), ph_m @ Vector((0, 0, -0.012)), 0.003, m_grip, ph_m.to_3x3())
    parts.append(clamp)
    phone = build_phone("phone", colors=C.get("phone"))
    place_prop(phone, ph_m)
    parts.append(phone)
    if ring:
        ringl = torus("selfie_ring", ph_m @ Vector((0, 0, 0.004)), 0.1, 0.009, ph_m.to_3x3().col[2], 44, 8,
                      bpy.data.materials.get("Screen"))
        parts.append(ringl)
        rim = torus("selfie_ring_body", ph_m @ Vector((0, 0, -0.004)), 0.1, 0.013, ph_m.to_3x3().col[2], 44, 8,
                    prop_mat("ring_body", "#e8e8ec", rough=0.4))
        parts.append(rim)
        for k in (-1, 1):
            parts.append(cyl("ring_arm", ph_m @ Vector((k * 0.03, 0, -0.012)), ph_m @ Vector((k * 0.098, 0, -0.004)), 0.003, m_metal, 8))
    for o in parts:
        attach_mesh(o, rig_obj, "hand_r")
        pieces.append(o)
    attach["r"] = ("fist", G)
    attach["selfie_phone"] = ph_m
    e = link(bpy.data.objects.new("PhoneLight", None))
    bone_child(e, rig_obj, "hand_r", ph_m @ Matrix.Translation((0, 0, 0.03)))


def p_ringlight(rig, rig_obj, attach, pieces, L, src):
    """A ring light on a pole out of a little backpack, always on, over the head."""
    back_y = min(v[1] for v in src.co if v[2] > src.bone["spine_03"][0].z) if False else None
    sp = src.bone["spine_03"][0]
    tb = BVHTree.FromObject(src.obj, bpy.context.evaluated_depsgraph_get())
    hit = tb.ray_cast(Vector((0, -0.6, sp.z + 0.04)), Vector((0, 1, 0)), 1.0)[0]
    y = (hit.y if hit is not None else sp.y - 0.12) - 0.07
    m_bag = fabric("backpack", colour("accent"), "cotton_jersey", rough=0.7)
    bag = rbox("backpack", (0.24, 0.09, 0.26), (0, y, sp.z + 0.02), 0.035, m_bag)
    m_metal = prop_mat("pole", "#d0d0d6", rough=0.3, metal=1.0)
    pole = cyl("pole", (0, y - 0.01, sp.z + 0.12), (0, y - 0.02, L["top"] + 0.2), 0.009, m_metal, 12)
    c = Vector((0, y + 0.02, L["top"] + 0.24))
    n = Vector((0, 0.7, -0.35)).normalized()
    ring = torus("ringlight", c, 0.17, 0.013, n, 48, 10, bpy.data.materials.get("Screen") or mat.emissive_screen("Screen"))
    body = torus("ringlight_body", c - n * 0.006, 0.17, 0.02, n, 48, 10, prop_mat("ring_body", "#f2f2f4", rough=0.4))
    arm = cyl("ringarm", (0, y - 0.02, L["top"] + 0.2), c - Vector((0, 0, 0.17)), 0.007, m_metal, 10)
    for o in (bag, pole, ring, body, arm):
        attach_mesh(o, rig_obj, "spine_03")
        pieces.append(o)


HATS = []


def trim_hair(hair):
    """Hair under a hat's crown goes (the sides and back stay out under it)."""
    if hair is None or not HATS:
        return
    def under(p):
        for c, rx, ry, ryb, rz, cut in HATS:
            v = p - c
            dh = Vector((v.x, v.y, 0.0))
            dh = dh.normalized() if dh.length > 1e-6 else Vector((0, 1, 0))
            ryy = ry if v.y > 0 else ryb
            q = (v.x / rx) ** 2 + (v.y / ryy) ** 2 + (max(v.z, 0.0) / rz) ** 2
            if v.z > cut(dh) - 0.004 and q < 1.08:
                return True
        return False
    delete_verts(hair, lambda v: under(v.co))


def hat_lift():
    return 0.009 + (0.017 if C.get("hair") else 0.0)


def p_cap(rig, rig_obj, attach, pieces, L, src, backwards=False):
    c, rx, ry, ryb, rz = head_fit(L, hat_lift())
    rim_front = L["eye"].z + 0.038 - c.z
    rim_back = L["eye"].z - 0.005 - c.z

    def cut(d):
        return lerp(rim_back, rim_front, (d.y + 1) / 2)

    m = fabric("cap", colour("cap", colour("accent")), "cotton_jersey", rough=0.8)
    crown, rim = dome("cap_crown", c, rx, ry, rz, cut, 32, 9, m, squash_back=ryb / ry)
    hug_skull(crown, c, src, hat_lift())
    HATS.append((c, rx, ry, ryb, rz, cut))
    parts = [crown]
    # Brim: a curved plate out of the front (or the back, worn backwards).
    side = -1.0 if backwards else 1.0
    z0 = c.z + (rim_back if backwards else rim_front)
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new("UVMap")
    rows = []
    for j in range(5):
        t = j / 4
        row = []
        for i in range(13):
            a = math.radians(-68 + 136 * i / 12)
            r0y = ry if not backwards else ryb
            x = math.sin(a) * rx * (1.0 - 0.1 * t)
            yv = math.cos(a) * (r0y + 0.078 * t * (0.55 + 0.45 * math.cos(a)))
            z = z0 + 0.002 - (0.01 * t * t) - 0.012 * (1 - math.cos(a)) * t + (0.012 * t if backwards else 0.0)
            row.append(bm.verts.new((c.x + x, c.y + yv * side, z)))
        rows.append(row)
    for j in range(4):
        for i in range(12):
            f = bm.faces.new((rows[j][i], rows[j][i + 1], rows[j + 1][i + 1], rows[j + 1][i]))
            for lp, (u, v) in zip(f.loops, ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1))):
                lp[uv].uv = (u / 12, v / 4)
    brim = mesh_from("cap_brim", bm, m)
    sol = brim.modifiers.new("s", "SOLIDIFY")
    sol.thickness = 0.005
    from lib import mesh as lmesh
    lmesh.apply_modifiers(brim)
    parts.append(brim)
    parts.append(cyl("cap_button", c + Vector((0, 0, rz - 0.001)), c + Vector((0, 0, rz + 0.005)), 0.008, m, 12))
    # The snapback strap's opening over the forehead when it's backwards.
    if backwards:
        parts.append(rbox("cap_strap", (0.05, 0.006, 0.012), c + Vector((0, ry * 0.98, rim_front + 0.004)), 0.003,
                          prop_mat("strap_clip", "#202022", rough=0.4)))
    for o in parts:
        on_head(o, rig_obj)
        pieces.append(o)
    return c, rim_front


def p_cap_back(*a):
    return p_cap(*a, backwards=True)


def p_glasses(rig, rig_obj, attach, pieces, L, src):
    """Reading glasses pushed up and forgotten, on the front of the cap."""
    c, rx, ry, ryb, rz = head_fit(L, hat_lift() + 0.004)
    m = prop_mat("glasses", "#2a1c14", rough=0.3)
    zc = L["eye"].z + 0.075
    crown = next((o for o in pieces if o.name.startswith("cap_crown")), None)
    tree = BVHTree.FromObject(crown, bpy.context.evaluated_depsgraph_get()) if crown else src.tree

    def front(x, z, lift=0.004):
        hit = tree.ray_cast(Vector((x, c.y + 0.4, z)), Vector((0, -1, 0)), 0.6)
        return (hit[0] + hit[1] * lift) if hit[0] is not None else Vector((x, c.y + ry, z))

    parts = []
    for sgn in (1, -1):
        lc = front(sgn * 0.032, zc)
        n = (lc - c).normalized()
        parts.append(torus("lens_rim", lc, 0.021, 0.0028, n, 24, 6, m))
        side = front(sgn * rx * 0.8, zc + 0.01, 0.003)
        parts.append(tube("temple", [lc + Vector((sgn * 0.021, 0, 0)), side.lerp(lc, 0.5) + n * 0.004, side], 0.0022, 6, m))
    b0, b1 = front(-0.011, zc + 0.004, 0.006), front(0.011, zc + 0.004, 0.006)
    parts.append(cyl("bridge", b0, b1, 0.0025, m, 6))
    for o in parts:
        on_head(o, rig_obj)
        pieces.append(o)


def p_beanie(rig, rig_obj, attach, pieces, L, src):
    c, rx, ry, ryb, rz = head_fit(L, hat_lift() + 0.003)
    base = L["eye"].z + 0.028 - c.z
    m = fabric("beanie", colour("beanie", colour("accent")), "knitted_fleece", rough=0.95, normal=0.8, scale=0.06)
    bcut = lambda d: base - 0.04 * max(0.0, -d.y)  # noqa: E731
    zc_, az_, ax_, _ = face_oval(L)
    log(f"beanie: rim front z {c.z + base:.3f}, void top {zc_ + az_:.3f}, eye {L['eye'].z:.3f}, head top {L['top']:.3f}, c {c.z:.3f} rz {rz:.3f}")
    crown, rim = dome("beanie", c, rx, ry, rz + 0.012, bcut, 32, 11, m, squash_back=ryb / ry * 1.05)
    hug_skull(crown, c, src, hat_lift() + 0.004)
    rim = [type("V", (), {"co": v.co.copy()})() for v in crown.data.vertices[-32:]]
    HATS.append((c, rx, ry, ryb * 1.05, rz + 0.012, bcut))
    loop = [type("V", (), {"co": v.co.copy()})() for v in rim]
    cuff = band(src, crown, loop, (0, 0, 1), 0.035, -0.04, "beanie_cuff", rib_material("beanie_rib", colour("beanie")), rows=2)
    cuff.vertex_groups.clear()
    for o in (crown, cuff):
        on_head(o, rig_obj)
        pieces.append(o)


def p_headphones(rig, rig_obj, attach, pieces, L, src, small=False):
    c, rx, ry, ryb, rz = head_fit(L, 0.02 if not small else 0.012)
    acc = prop_mat("headphones", colour("accent"), rough=0.4)
    pad = prop_mat("earpad", "#1a1a1e", rough=0.8)
    zc = L["ear_z"] + 0.004
    yc = L["ear_y"]
    cup_r = 0.045 if not small else 0.028
    arc = []
    for k in range(25):
        th = math.radians(-90 + 180 * k / 24)
        arc.append(Vector((math.sin(th) * (rx + 0.014), yc - 0.004, zc + math.cos(th) * (c.z + rz - zc + 0.016))))
    parts = [tube("headband", arc, 0.011 if not small else 0.0055, 8, acc)]
    for sgn in (1, -1):
        x0 = sgn * (L["ear_x"] + 0.004)
        parts.append(cyl("cup", (x0 + sgn * 0.014, yc, zc), (x0 + sgn * (0.05 if not small else 0.026), yc, zc), cup_r, acc, 24))
        parts.append(cyl("pad", (x0 - sgn * 0.002, yc, zc), (x0 + sgn * 0.016, yc, zc), cup_r * 0.92, pad, 24))
    if small:  # the headset's mic boom toward the void
        tip = Vector((0.03, L["eye"].y + 0.012, L["lips"].z))
        pts = [Vector((L["ear_x"] + 0.03, yc + 0.01, zc - 0.01)), Vector((L["ear_x"] + 0.01, yc + 0.07, zc - 0.05)),
               Vector((0.06, L["eye"].y - 0.01, L["lips"].z)), tip]
        parts.append(tube("boom", pts, 0.0028, 6, prop_mat("boom", "#1a1a1e", rough=0.4)))
        parts.append(cyl("mic", tip - Vector((0.008, 0, 0)), tip + Vector((0.004, 0, 0)), 0.0065, acc, 10))
    for o in parts:
        on_head(o, rig_obj)
        pieces.append(o)


def p_headset(*a):
    return p_headphones(*a, small=True)


def p_airpods(rig, rig_obj, attach, pieces, L, src):
    m = prop_mat("airpod", "#f4f4f4", rough=0.25)
    for sgn in (1, -1):
        x = sgn * (L["ear_x"] - 0.004)
        c = Vector((x, L["ear_y"] + 0.012, L["ear_z"] - 0.002))
        bud = cyl("bud", c, c + Vector((sgn * 0.01, 0.002, 0)), 0.0085, m, 12)
        stem = cyl("stem", c + Vector((sgn * 0.004, 0.006, -0.002)), c + Vector((sgn * 0.004, 0.012, -0.03)), 0.0032, m, 8)
        for o in (bud, stem):
            on_head(o, rig_obj)
            pieces.append(o)


def body_ray(src, x, z, from_front=True, shells=()):
    objs = list(shells) or [src.obj]
    best = None
    for o in objs:
        tb = BVHTree.FromObject(o, bpy.context.evaluated_depsgraph_get())
        o_ = Vector((x, 0.6 if from_front else -0.6, z))
        hit = tb.ray_cast(o_, Vector((0, -1 if from_front else 1, 0)), 1.2)
        if hit[0] is not None and (best is None or (hit[0].y > best[0].y if from_front else hit[0].y < best[0].y)):
            best = hit
    return best


def p_fannypack(rig, rig_obj, attach, pieces, L, src):
    """Worn crossbody, high on the chest, the way it's done now."""
    sp = src.bone["spine_03"][0]
    hit = body_ray(src, 0.02, sp.z + 0.02, shells=SHELLS)
    y = hit[0].y + 0.035 if hit else 0.16
    rot = Ry(-20)
    m = fabric("fannypack", colour("accent"), "cotton_jersey", rough=0.6)
    m_zip = prop_mat("zip", "#1a1a1c", rough=0.4)
    parts = [rbox("pack", (0.22, 0.07, 0.1), (0.02, y, sp.z + 0.02), 0.03, m, rot),
             rbox("zip", (0.19, 0.006, 0.01), (0.02, y + 0.036, sp.z + 0.035), 0.003, m_zip, rot)]
    # Strap: over the left shoulder, round the back, under the right arm.
    pts = []
    for k in range(17):
        a = 2 * math.pi * k / 16
        pts.append(Vector((0.02 + 0.17 * math.cos(a), sp.y + 0.02 + 0.13 * math.sin(a), sp.z + 0.02 + 0.12 * math.cos(a + 0.4))))
    strap = tube("strap", pts, 0.009, 4, m_zip, cap=False)
    parts.append(strap)
    for o in parts:
        transfer_weights(src.obj, o)
        o.parent = rig_obj
        o.modifiers.new("Armature", "ARMATURE").object = rig_obj
        pieces.append(o)


def p_tie(rig, rig_obj, attach, pieces, L, src):
    shirt = [o for o in SHELLS if o.name.startswith("shirt")] or list(SHELLS)
    neck = src.bone["neck_01"][0]
    m = fabric("tie", colour("tie"), "stretch_poplin", rough=0.45)
    top_z = neck.z - 0.02
    pts, wid = [], []
    for k in range(9):
        t = k / 8
        z = top_z - 0.43 * t
        hit = body_ray(src, 0.0, z, shells=shirt)
        y = (hit[0].y if hit else 0.14) + 0.004 + 0.006 * t
        pts.append(Vector((0.0, y, z)))
        wid.append(0.018 + 0.02 * t if k < 8 else 0.0)
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new("UVMap")
    rows = []
    for p, w in zip(pts, wid):
        rows.append([bm.verts.new(p + Vector((-w, 0, 0))), bm.verts.new(p + Vector((0, 0.004, 0))), bm.verts.new(p + Vector((w, 0, 0)))])
    rows[-1] = [bm.verts.new(pts[-1] + Vector((0, 0.002, -0.012)))] * 3
    for k in range(len(rows) - 1):
        for i in range(2):
            vs = [rows[k][i], rows[k][i + 1], rows[k + 1][i + 1], rows[k + 1][i]]
            if len(set(vs)) < 3:
                continue
            f = bm.faces.new(list(dict.fromkeys(vs)))
            for lp in f.loops:
                lp[uv].uv = (i / 2, k / 8)
    tie = mesh_from("tie", bm, m)
    sol = tie.modifiers.new("s", "SOLIDIFY")
    sol.thickness = 0.003
    sol.offset = 1.0
    from lib import mesh as lmesh
    lmesh.apply_modifiers(tie)
    lmesh.clean(tie)
    knot = rbox("knot", (0.03, 0.02, 0.028), pts[0] + Vector((0, 0.006, 0.004)), 0.008, m)
    for o in (tie, knot):
        transfer_weights(src.obj, o)
        o.parent = rig_obj
        o.modifiers.new("Armature", "ARMATURE").object = rig_obj
        pieces.append(o)


def p_lanyard(rig, rig_obj, attach, pieces, L, src):
    """Company lanyard round the neck, the badge on the belly. Never removed."""
    shirt = [o for o in SHELLS if o.name.startswith("shirt")] or list(SHELLS)
    neck = src.bone["neck_01"][0]
    m = prop_mat("lanyard", "#1faa5a", rough=0.6)
    badge_z = neck.z - 0.3
    hit = body_ray(src, 0.035, badge_z, shells=shirt)
    by = (hit[0].y if hit else 0.16) + 0.012
    for sgn in (1, -1):
        pts = [Vector((sgn * 0.05, neck.y - 0.06, neck.z + 0.01)), Vector((sgn * 0.075, neck.y + 0.01, neck.z - 0.02)),
               Vector((sgn * 0.06, by - 0.02, neck.z - 0.13)), Vector((sgn * 0.02, by, badge_z + 0.055))]
        st = tube("lanyard", pts, 0.004, 4, m, cap=False)
        transfer_weights(src.obj, st)
        st.parent = rig_obj
        st.modifiers.new("Armature", "ARMATURE").object = rig_obj
        pieces.append(st)
    card = prop_mat("badge", "#f2f2f0", rough=0.3)
    b = rbox("badge", (0.06, 0.004, 0.085), (0.0, by, badge_z), 0.004, card)
    stripe = rbox("badge_stripe", (0.061, 0.0045, 0.018), (0.0, by + 0.0005, badge_z + 0.03), 0.002, m)
    photo = rbox("badge_photo", (0.022, 0.0045, 0.026), (-0.012, by + 0.0006, badge_z - 0.004), 0.002, prop_mat("badge_photo", "#6a6f7a"))
    for o in (b, stripe, photo):
        transfer_weights(src.obj, o)
        o.parent = rig_obj
        o.modifiers.new("Armature", "ARMATURE").object = rig_obj
        pieces.append(o)


def p_cup(rig, rig_obj, attach, pieces, L, src, kind="mug"):
    G = grip_matrix(rig, "l", "cup")
    parts = []
    if kind == "mug":
        m = prop_mat("mug", "#f3f1ec", rough=0.2)
        body = cyl("mug", (0, 0, -0.05), (0, 0, 0.05), 0.04, m, 24)
        parts.append(body)
        parts.append(cyl("coffee", (0, 0, 0.044), (0, 0, 0.046), 0.036, prop_mat("coffee", "#2a1810", rough=0.1), 20))
        handle = torus("mug_handle", (0, -0.048, 0.0), 0.026, 0.0065, (1, 0, 0), 20, 6, m, arc=0.55)
        for v in handle.data.vertices:  # rotate the half-torus to open toward the cup
            v.co = Vector((v.co.x, -0.048 - (v.co.y + 0.048) * -1 if False else v.co.y, v.co.z))
        parts.append(handle)
    else:  # iced matcha: cup, green, dome lid, straw
        m = prop_mat("matcha", "#8fb45a", rough=0.15)
        parts.append(cyl("matcha", (0, 0, -0.065), (0, 0, 0.06), 0.034, m, 24, r2=0.041))
        lid = prop_mat("lid", "#f0f2f0", rough=0.1)
        parts.append(cyl("lid", (0, 0, 0.06), (0, 0, 0.075), 0.042, lid, 24, r2=0.03))
        parts.append(cyl("straw", (0.006, 0.004, 0.05), (0.012, 0.01, 0.16), 0.0035, prop_mat("straw", "#5a8a3a", rough=0.3), 8))
    # The cup frame: its axis (Z) up along the hand's side, in the fingers.
    for o in parts:
        place_prop(o, G @ Rx(-90).to_4x4())
        attach_mesh(o, rig_obj, "hand_l")
        pieces.append(o)
    attach["l"] = ("cup", G)


def p_yogamat(rig, rig_obj, attach, pieces, L, src):
    sp = src.bone["spine_02"][0]
    hit = body_ray(src, 0.0, sp.z + 0.08, from_front=False, shells=list(SHELLS) + [src.obj])
    y = (hit[0].y if hit else sp.y - 0.12) - 0.065
    m = fabric("yogamat", colour("accent"), "cotton_jersey", rough=0.7)
    d = Vector((math.cos(math.radians(28)), 0, math.sin(math.radians(28))))
    c = Vector((0, y, sp.z + 0.08))
    roll = cyl("yogamat", c - d * 0.26, c + d * 0.26, 0.058, m, 24)
    strap = prop_mat("mat_strap", "#2a2a2e", rough=0.6)
    parts = [roll]
    for k in (-0.2, 0.2):
        parts.append(torus("mat_band", c + d * k, 0.061, 0.004, d, 24, 4, strap))
    pts = [c + d * 0.2 + Vector((0, 0.03, 0.05)), Vector((0.1, y + 0.1, src.bone["neck_01"][0].z - 0.02)),
           Vector((0.0, y + 0.18, sp.z + 0.2)), Vector((-0.12, y + 0.14, sp.z + 0.02)), c - d * 0.2 + Vector((0, 0.03, -0.04))]
    parts.append(tube("mat_strap", pts, 0.006, 4, strap, cap=False))
    for o in parts:
        attach_mesh(o, rig_obj, "spine_03")
        pieces.append(o)


def p_halo(rig, rig_obj, attach, pieces, L, src):
    """A glowing green ring behind the head: open to opportunities, always."""
    c = Vector((0, L["head_lo"].y - 0.06, L["eye"].z + 0.03))
    m = mat.flat("src_halo", "#2cff7a", rough=0.3, emission="#2cff7a", strength=4.0)
    ring = torus("halo", c, 0.15, 0.009, (0, 1, 0), 48, 8, m)
    on_head(ring, rig_obj)
    pieces.append(ring)


def p_jiggler(rig, rig_obj, attach, pieces, L, src):
    """A mouse jiggler clipped to the waistband, its green light always on."""
    z = src.bone["pelvis"][0].z + 0.02
    hit = body_ray(src, 0.15, z, shells=SHELLS)
    y = (hit[0].y if hit else 0.1) + 0.012
    box = rbox("jiggler", (0.055, 0.025, 0.034), (0.15, y, z), 0.008, prop_mat("jiggler", "#1d1e22", rough=0.4))
    led = cyl("led", (0.165, y + 0.012, z + 0.006), (0.165, y + 0.015, z + 0.006), 0.004,
              mat.flat("src_led", "#30ff80", emission="#30ff80", strength=6.0), 10)
    for o in (box, led):
        transfer_weights(src.obj, o)
        o.parent = rig_obj
        o.modifiers.new("Armature", "ARMATURE").object = rig_obj
        pieces.append(o)


SHELLS = []

PROPS = {
    "phone": lambda r, ro, at, pc, L, src: p_phone(r, ro, at, pc),
    "phone.L": p_phone2,
    "phone.L.news": lambda *a: p_phone2(*a, screen="ScreenNews"),
    "phone.L.news2": p_phone_news2,
    "tablet": p_tablet,
    "tablet.far": p_tablet,
    "selfie": p_selfie,
    "selfie.ring": lambda *a: p_selfie(*a, ring=True),
    "ringlight": p_ringlight,
    "cap": p_cap,
    "cap.back": p_cap_back,
    "glasses": p_glasses,
    "beanie": p_beanie,
    "headphones": p_headphones,
    "headset": p_headset,
    "airpods": p_airpods,
    "fannypack": p_fannypack,
    "tie": p_tie,
    "lanyard": p_lanyard,
    "mug": lambda *a: p_cup(*a, kind="mug"),
    "matcha": lambda *a: p_cup(*a, kind="matcha"),
    "yogamat": p_yogamat,
    "halo": p_halo,
    "jiggler": p_jiggler,
}


def equip(rig, rig_obj, L, src, shells):
    attach, pieces = {}, []
    if lib.arg("tip"):  # debug: try a thumb tip spot on the phone (prop frame, m)
        GRIPS["phone"]["tip"] = tuple(float(v) for v in lib.arg("tip").split(","))
    if lib.arg("lift"):  # debug: the thumb's lift out of the palm (deg)
        GRIPS["phone"]["thumb_lift"] = float(lib.arg("lift"))
    if any(p.startswith("phone") for p in C["props"]):
        solve_grip(rig, src, "phone", PROP_DIMS["phone"])
    if any(p.startswith("tablet") for p in C["props"]):
        solve_grip(rig, src, "tablet", PROP_DIMS["tablet"], wrap=False)
    SHELLS[:] = shells + [o for o in bpy.data.objects if o.get("mpfb_key") and o.get("mpfb_key") != "hair"]
    for prop in C["props"]:
        PROPS[prop](rig, rig_obj, attach, pieces, L, src)
    attach.setdefault("l", ("relaxed", Matrix.Identity(4)))
    attach.setdefault("r", ("relaxed", Matrix.Identity(4)))
    return attach, pieces


# ================================================================ folds
#
# Shell garments get their folds from a short cloth sim: a copy of the shell
# (one subdivision finer) is pinned where the garment hangs from (shoulders
# and collar for tops, the waistband for trousers), settles for a few dozen
# frames under gravity against the body, and its folds are baked as a normal
# map onto the game-res shell (high -> low, into the shell's atlas islands).

def cloth_settle(shell, src, pin, frames=26, name=None, shrink=0.03, bending=0.08):
    """A settled, finer copy of `shell` (the high-poly for the fold bake).
    pin(co) -> 0..1 pin weight. Returns the new object (no modifiers)."""
    from lib import mesh as lmesh
    hi = shell.copy()
    hi.data = shell.data.copy()
    hi.name = name or shell.name + "_hi"
    link(hi)
    hi.parent = None
    hi.modifiers.clear()
    hi.matrix_world = Matrix.Identity(4)
    sub = hi.modifiers.new("sub", "SUBSURF")
    sub.levels = 1
    lmesh.apply_modifiers(hi)
    vg = hi.vertex_groups.new(name="_pin")
    for v in hi.data.vertices:
        w = pin(v.co)
        if w > 0:
            vg.add([v.index], min(1.0, w), "REPLACE")
    if "_flat" not in src.obj:
        # The collider has no nipples (or the cloth would drape over them).
        for n in ("nippleTip", "nipple"):
            vg = src.obj.vertex_groups.get(n)
            if vg is None:
                continue
            for v in src.obj.data.vertices:
                w = next((g.weight for g in v.groups if g.group == vg.index), 0.0)
                if w > 0:
                    v.co -= v.normal * 0.006 * w
        src.obj.data.update()
        src.obj["_flat"] = True
    col = src.obj.modifiers.get("_collide") or src.obj.modifiers.new("_collide", "COLLISION")
    src.obj.collision.thickness_outer = 0.004
    src.obj.collision.cloth_friction = 8.0
    cl = hi.modifiers.new("cloth", "CLOTH")
    st = cl.settings
    st.quality = 6
    st.mass = 0.2
    st.tension_stiffness = st.compression_stiffness = 6.0
    st.shear_stiffness = 4.0
    st.bending_stiffness = bending
    st.air_damping = 1.0
    st.shrink_min = shrink  # a touch of shrink: the fabric has to gather
    st.vertex_group_mass = "_pin"
    st.pin_stiffness = 1.0
    cl.collision_settings.use_collision = True
    cl.collision_settings.distance_min = 0.004
    cl.collision_settings.use_self_collision = False
    cl.point_cache.frame_start = 1
    cl.point_cache.frame_end = frames
    scene.frame_start, scene.frame_end = 1, frames
    for f in range(1, frames + 1):
        scene.frame_set(f)
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(hi.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
    old = hi.data
    hi.modifiers.clear()
    hi.data = me
    bpy.data.meshes.remove(old)
    scene.frame_set(0)
    for p in me.polygons:
        p.use_smooth = True
    hi.hide_render = True  # out of the atlas AO; the fold bake selects it
    return hi


def pin_top(src):
    """Tops hang from the shoulders and the collar."""
    z0 = src.bone["spine_03"][1].z - 0.02
    return lambda co: smoothstep(z0 - 0.06, z0 + 0.02, co.z) if abs(co.x) < 0.24 else smoothstep(z0 - 0.02, z0 + 0.06, co.z)


def pin_waist(src):
    z0 = src.bone["pelvis"][0].z + 0.02
    return lambda co: smoothstep(z0 - 0.08, z0, co.z)


FOLDS = []  # (low, high) pairs baked after the atlas


def bake_folds(pairs, res):
    """Bake each high's folds into its low's islands of the atlas normal map."""
    from lib import bake
    normal = res.get("normal")
    if normal is None or not pairs:
        return
    px = bake.pixels(normal).copy()
    white = mat.flat("_mask", (1, 1, 1), emission=(1, 1, 1), strength=1.0)
    for low, high in pairs:
        tmp = bake.new_image("_fold_n", normal.size[0], "normal")
        bake.bake_map([low], "normal", tmp, uv_layer="UVMap", high=[high], cage_extrusion=0.025,
                      max_ray_distance=0.06, margin=2, samples=4)
        saved = list(low.data.materials)
        low.data.materials.clear()
        low.data.materials.append(white)
        mask = bake.new_image("_fold_m", normal.size[0], "emission", fill=(0, 0, 0, 1))
        bake.bake_map([low], "emission", mask, uv_layer="UVMap", margin=1, samples=1)
        low.data.materials.clear()
        for m in saved:
            low.data.materials.append(m)
        m_ = bake.pixels(mask)[..., 0] > 0.5
        new = bake.pixels(tmp)
        # Rays that missed the settled cloth (at openings) give wild normals:
        # keep the fabric's own there.
        m_ &= new[..., 2] > 0.68
        px[m_] = new[m_]
        bpy.data.images.remove(tmp)
        bpy.data.images.remove(mask)
        bpy.data.objects.remove(high)
    bake.set_pixels(normal, px)
    bake.save_png(normal, normal.filepath_raw or os.path.join(CACHE, "atlas", f"{CHAR}_outfit_normal.png"))
    bpy.data.materials.remove(white)
    log(f"folds baked for {len(pairs)} garments")


# ================================================================ look

KEEP = ("Skin", "Void", "Hair", "Screen", "ScreenAlt", "ScreenNews", "ScreenRing")


def colour(key, default="#808080"):
    return C.get("colours", {}).get(key, default)


_MEANS = {}


def tex_mean(tex):
    """Mean linear luminance of a texture set's colour map (so a tint reads
    as the colour asked for, whatever the set's own brightness)."""
    if tex not in _MEANS:
        path = mat.find_maps(tex)["color"]
        img = bpy.data.images.load(path)
        img.scale(32, 32)
        px = np.empty(32 * 32 * 4, np.float32)
        img.pixels.foreach_get(px)
        px = px.reshape(-1, 4)
        _MEANS[tex] = float(np.clip((px[:, 0] * 0.2126 + px[:, 1] * 0.7152 + px[:, 2] * 0.0722).mean(), 0.02, 1.0))
        bpy.data.images.remove(img)
    return _MEANS[tex]


def fabric(name, color, tex="jogging_melange", scale=0.12, rough=0.88, normal=0.35, value=1.0, uv=False, tiling=1.0):
    """A CC0 fabric set, box-mapped (no UV stretch on the body-grown shells),
    tinted to the character's colour: the set is greyed and normalised, so
    only its weave and heather modulate the tint."""
    m = mat.pbr("src_" + name, tex, mapping="UV" if uv else "BOX", box_scale=scale, tiling=tiling,
                roughness=rough, normal_strength=normal, ao_strength=0.5)
    nt = m.node_tree
    p = mat.principled(m)
    src = p.inputs["Base Color"].links[0].from_socket
    hsv = nt.nodes.new("ShaderNodeHueSaturation")
    hsv.inputs["Saturation"].default_value = 0.0
    hsv.inputs["Value"].default_value = value / tex_mean(tex)
    nt.links.new(src, hsv.inputs["Color"])
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = "MULTIPLY"
    mix.inputs["Factor"].default_value = 1.0
    nt.links.new(hsv.outputs["Color"], mix.inputs[6])
    mix.inputs[7].default_value = mat.rgba(color)
    nt.links.new(mix.outputs[2], p.inputs["Base Color"])
    return m


def retint(obj, color, saturation=0.15, value=1.0, rough=None):
    """Recolour an MPFB asset's material: desaturate its diffuse, multiply the tint."""
    for slot in obj.material_slots:
        m = slot.material
        if m is None:
            continue
        nt = m.node_tree
        p = mat.principled(m)
        src = p.inputs["Base Color"].links[0].from_socket if p.inputs["Base Color"].is_linked else None
        hsv = nt.nodes.new("ShaderNodeHueSaturation")
        hsv.inputs["Saturation"].default_value = saturation
        hsv.inputs["Value"].default_value = value
        if src is not None:
            nt.links.new(src, hsv.inputs["Color"])
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.blend_type = "MULTIPLY"
        mix.inputs["Factor"].default_value = 1.0
        nt.links.new(hsv.outputs["Color"], mix.inputs[6])
        mix.inputs[7].default_value = mat.rgba(color)
        nt.links.new(mix.outputs[2], p.inputs["Base Color"])
        if rough is not None:
            if p.inputs["Roughness"].is_linked:
                nt.links.remove(p.inputs["Roughness"].links[0])
            p.inputs["Roughness"].default_value = rough


def mpfb_images(obj):
    """The MPFB asset's texture paths by kind (diffuse, normal, ao)."""
    out = {}
    for slot in obj.material_slots:
        if slot.material is None:
            continue
        for n in slot.material.node_tree.nodes:
            if n.type == "TEX_IMAGE" and n.image is not None:
                name = os.path.basename(n.image.filepath).lower()
                kind = "normal" if "normal" in name else ("ao" if "_ao" in name else "diffuse")
                out.setdefault(kind, bpy.path.abspath(n.image.filepath))
    return out


def mpfb_material(obj, key, color=None, tex="cotton_jersey", two_tone=None, rough=0.82, weave=0.35):
    """Recolour an MPFB garment: the tint (x the CC0 weave, box-mapped) for
    albedo, or two colours split by the original's luminance (suit + shirt);
    MPFB's own normal and AO maps keep its seams, pockets and folds."""
    imgs = mpfb_images(obj)
    m = mat.new_material("src_" + key)
    nt = m.node_tree
    p = mat.principled(m)
    p.inputs["Roughness"].default_value = rough
    uvn = nt.nodes.new("ShaderNodeTexCoord")

    def img(path, data):
        n = nt.nodes.new("ShaderNodeTexImage")
        n.image = mat.image(path, data)
        nt.links.new(uvn.outputs["UV"], n.inputs["Vector"])
        return n

    if two_tone and "diffuse" in imgs:
        d = img(imgs["diffuse"], False)
        bw = nt.nodes.new("ShaderNodeRGBToBW")
        nt.links.new(d.outputs["Color"], bw.inputs["Color"])
        ramp = nt.nodes.new("ShaderNodeMapRange")
        ramp.inputs["From Min"].default_value = 0.12
        ramp.inputs["From Max"].default_value = 0.4
        nt.links.new(bw.outputs["Val"], ramp.inputs["Value"])
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.inputs[6].default_value = mat.rgba(two_tone[0])
        mix.inputs[7].default_value = mat.rgba(two_tone[1])
        nt.links.new(ramp.outputs["Result"], mix.inputs["Factor"])
        nt.links.new(mix.outputs[2], p.inputs["Base Color"])
    else:
        w = mat.find_maps(tex)["color"]
        tc = nt.nodes.new("ShaderNodeTexCoord")
        mp = nt.nodes.new("ShaderNodeMapping")
        mp.inputs["Scale"].default_value = (8.0, 8.0, 8.0)
        nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
        wv = nt.nodes.new("ShaderNodeTexImage")
        wv.image = mat.image(w, False)
        wv.projection = "BOX"
        wv.projection_blend = 0.3
        nt.links.new(mp.outputs["Vector"], wv.inputs["Vector"])
        hsv = nt.nodes.new("ShaderNodeHueSaturation")
        hsv.inputs["Saturation"].default_value = 0.0
        hsv.inputs["Value"].default_value = 1.0 / tex_mean(tex)
        nt.links.new(wv.outputs["Color"], hsv.inputs["Color"])
        weave_mix = nt.nodes.new("ShaderNodeMix")
        weave_mix.data_type = "RGBA"
        weave_mix.inputs["Factor"].default_value = weave
        weave_mix.inputs[6].default_value = (1, 1, 1, 1)
        nt.links.new(hsv.outputs["Color"], weave_mix.inputs[7])
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.blend_type = "MULTIPLY"
        mix.inputs["Factor"].default_value = 1.0
        nt.links.new(weave_mix.outputs[2], mix.inputs[6])
        mix.inputs[7].default_value = mat.rgba(color or "#808080")
        nt.links.new(mix.outputs[2], p.inputs["Base Color"])
    if "normal" in imgs:
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nt.links.new(img(imgs["normal"], True).outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], p.inputs["Normal"])
    if "ao" in imgs:
        nt.links.new(img(imgs["ao"], True).outputs["Color"], mat.gltf_output(m).inputs["Occlusion"])
    obj.data.materials.clear()
    obj.data.materials.append(m)
    return m


def hair_material(obj, tint):
    imgs = mpfb_images(obj)
    m = mat.new_material("Hair")
    nt = m.node_tree
    p = mat.principled(m)
    n = nt.nodes.new("ShaderNodeTexImage")
    n.image = resized(imgs["diffuse"], 1024, "hair")
    n.image.alpha_mode = "STRAIGHT"
    hsv = nt.nodes.new("ShaderNodeHueSaturation")
    hsv.inputs["Saturation"].default_value = 0.0
    hsv.inputs["Value"].default_value = 2.2
    nt.links.new(n.outputs["Color"], hsv.inputs["Color"])
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = "MULTIPLY"
    mix.inputs["Factor"].default_value = 1.0
    nt.links.new(hsv.outputs["Color"], mix.inputs[6])
    mix.inputs[7].default_value = mat.rgba(tint)
    nt.links.new(mix.outputs[2], p.inputs["Base Color"])
    p.inputs["Roughness"].default_value = 0.72
    p.inputs["Specular IOR Level"].default_value = 0.3
    mat.set_alpha(m, "CLIP", n.outputs["Alpha"])
    obj.data.materials.clear()
    obj.data.materials.append(m)
    return m


def dress_materials(shells, assets):
    cache = {}
    for sh in shells:
        if sh.data.materials and sh.data.materials[0] is not None:
            continue  # trims come with their own
        base = sh.name.split(".")[0]
        key = {"hoodie": "hoodie", "hood": "hoodie", "hooddown": "hoodie", "pocket": "hoodie", "joggers": "pants",
               "sweat": "hoodie", "tee": "tee", "pyjama": "pants"}.get(base, base)
        tex = {"hoodie": "jogging_melange", "pants": "jogging_melange"}.get(key, "cotton_jersey")
        if base == "pyjama":
            tex = "stretch_poplin"
        if key not in cache:
            cache[key] = fabric(key, colour(key), tex)
            if base == "pyjama":
                plaid(cache[key])
        sh.data.materials.append(cache[key])
    for spec in C.get("mpfb", ()):
        o = assets.get(spec["key"])
        if o is not None:
            mpfb_material(o, spec["key"], colour(spec["key"]), spec.get("tex", "cotton_jersey"), spec.get("two_tone"))
    shoes = assets.get("shoes")
    if shoes is not None and C["shoes"][1]:
        retint(shoes, C["shoes"][1], saturation=0.2, value=1.0, rough=0.6)
    if "hair" in assets:
        hair_material(assets["hair"], C["hair"][1])


def plaid(m):
    """Pyjama checks over the fabric: two sets of soft stripes, object space."""
    nt = m.node_tree
    p = mat.principled(m)
    src = p.inputs["Base Color"].links[0].from_socket
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Object"], sep.inputs["Vector"])
    acc = None
    for axis, freq in (("X", 14.0), ("Z", 14.0), ("Y", 14.0)):
        mul = nt.nodes.new("ShaderNodeMath")
        mul.operation = "MULTIPLY"
        mul.inputs[1].default_value = 2 * math.pi * freq
        nt.links.new(sep.outputs[axis], mul.inputs[0])
        sn = nt.nodes.new("ShaderNodeMath")
        sn.operation = "SINE"
        nt.links.new(mul.outputs[0], sn.inputs[0])
        pw = nt.nodes.new("ShaderNodeMath")
        pw.operation = "GREATER_THAN"
        pw.inputs[1].default_value = 0.55
        nt.links.new(sn.outputs[0], pw.inputs[0])
        if acc is None:
            acc = pw.outputs[0]
        else:
            add = nt.nodes.new("ShaderNodeMath")
            add.operation = "ADD"
            nt.links.new(acc, add.inputs[0])
            nt.links.new(pw.outputs[0], add.inputs[1])
            acc = add.outputs[0]
    k = nt.nodes.new("ShaderNodeMath")
    k.operation = "MULTIPLY_ADD"
    k.inputs[1].default_value = -0.22
    k.inputs[2].default_value = 1.0
    nt.links.new(acc, k.inputs[0])
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = "MULTIPLY"
    mix.inputs["Factor"].default_value = 1.0
    nt.links.new(src, mix.inputs[6])
    cmb = nt.nodes.new("ShaderNodeCombineColor")
    for ch in ("Red", "Green", "Blue"):
        nt.links.new(k.outputs[0], cmb.inputs[ch])
    nt.links.new(cmb.outputs["Color"], mix.inputs[7])
    nt.links.new(mix.outputs[2], p.inputs["Base Color"])


def bake_outfit(pieces, shoes):
    """Everything but skin/void/hair/screens into one 1024 atlas ("Outfit");
    `Shoes` is the same atlas under its own name (the renderer tints it)."""
    from lib import bake
    out_dir = os.path.join(CACHE, "atlas")
    weights = {p.name: p.get("atlas_weight", 1.0) for p in pieces}
    res = bake.bake_kit_atlas(pieces, 1024, out_dir, f"{CHAR}_outfit", keep_materials=KEEP, unwrap="keep",
                              weights=weights, samples=4 if FAST else 8, ao_samples=32 if FAST else 96,
                              ao_distance=0.25, ao_isolate=False, material_name="Outfit")
    outfit = res["material"]
    bake_folds(FOLDS, res)
    if shoes is not None:
        sm = outfit.copy()
        sm.name = "Shoes"
        # Not identical to Outfit, or the glb's dedup merges the two.
        mat.principled(sm).inputs["Specular IOR Level"].default_value = 0.55
        for i, m in enumerate(shoes.data.materials):
            if m == outfit:
                shoes.data.materials[i] = sm
    return outfit


HAND_BONES = {f"{f}_0{j}_{s}" for f in FINGERS for j in (1, 2, 3) for s in "lr"} | {"hand_l", "hand_r"}


def stiffen_ends(obj, hands=True, feet=True):
    """Move hand/finger weights to the forearm and foot weights to the calf
    (a sleeve cuff or a trouser hem must not twist with the wrist/ankle)."""
    names = {vg.index: vg.name for vg in obj.vertex_groups}
    to = {}
    for n in names.values():
        if hands and n in HAND_BONES:
            to[n] = "lowerarm_" + n[-1]
        if feet and (n.startswith("foot_") or n.startswith("ball_")):
            to[n] = "calf_" + n[-1]
    if not to:
        return
    for t in set(to.values()):
        if t not in obj.vertex_groups:
            obj.vertex_groups.new(name=t)
    idx = {vg.name: vg.index for vg in obj.vertex_groups}
    for v in obj.data.vertices:
        moved = {}
        for g in v.groups:
            n = names.get(g.group)
            if n in to and g.weight > 0:
                moved[to[n]] = moved.get(to[n], 0.0) + g.weight
                g.weight = 0.0
        for t, w in moved.items():
            vg = obj.vertex_groups[t]
            cur = next((g.weight for g in v.groups if g.group == idx[t]), 0.0)
            vg.add([v.index], cur + w, "REPLACE")


BUDGET = 34500


def fit_budget(body, parts, hair):
    """Over the triangle budget? Decimate the heaviest garments (MPFB suits
    first: their normal maps carry the detail), never the body or props."""
    total = tris(body) + sum(tris(o) for o in parts + hair)
    if total <= BUDGET:
        return total
    cands = sorted([o for o in parts if o.get("mpfb_key") not in (None, "shoes") or o.name.split(".")[0] in
                    ("hoodie", "joggers", "hood", "sweat", "tee", "pyjama")], key=tris, reverse=True)
    excess = total - BUDGET
    pool = sum(tris(o) for o in cands[:3])
    for o in cands[:3]:
        r = max(0.35, 1.0 - excess / pool * 1.08)
        m = o.modifiers.new("budget", "DECIMATE")
        m.ratio = r
        with bpy.context.temp_override(object=o, active_object=o):
            bpy.ops.object.modifier_move_to_index(modifier=m.name, index=0)
            bpy.ops.object.modifier_apply(modifier=m.name)
        log(f"budget: {o.name} decimated to {r:.2f} ({tris(o)} tris)")
    return tris(body) + sum(tris(o) for o in parts + hair)


def finish_mesh(body, parts, rig):
    """Join everything into one skinned mesh, clean the weights."""
    for o in [body] + parts:
        me = o.data
        if me.uv_layers:
            act = me.uv_layers.active
            for l in [l for l in me.uv_layers if l != act]:
                me.uv_layers.remove(l)
            me.uv_layers.active.name = "UVMap"
        for m in list(o.modifiers):
            if m.type != "ARMATURE":
                o.modifiers.remove(m)
    select_only(body, *parts)
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.join()
    body.name = body.data.name = f"{CHAR}"
    # Deform groups only (bones); drop MPFB's helper/extra groups.
    bones = {b.name for b in rig.data.bones}
    for vg in list(body.vertex_groups):
        if vg.name not in bones:
            body.vertex_groups.remove(vg)
    with bpy.context.temp_override(object=body, active_object=body):
        bpy.ops.object.vertex_group_limit_total(group_select_mode="ALL", limit=4)
        bpy.ops.object.vertex_group_normalize_all(group_select_mode="ALL", lock_active=False)
    # Unused material slots out.
    used = {p.material_index for p in body.data.polygons}
    for i in reversed(range(len(body.data.materials))):
        if i not in used:
            body.data.materials.pop(index=i)
    body.parent = rig
    mods = [m for m in body.modifiers if m.type == "ARMATURE"]
    for m in mods[1:]:
        body.modifiers.remove(m)
    if not mods:
        body.modifiers.new("Armature", "ARMATURE")
    body.modifiers[0].object = rig
    return body


# ================================================================ build

def build_body():
    basemesh, rig = make_body()
    assets = add_mpfb_assets(basemesh)
    face_forward(rig)
    rig.name = rig.data.name = "rig"
    TargetService.bake_targets(basemesh)  # the macros, into the mesh
    stand_on_soles(rig)
    L = landmarks(basemesh)
    strip_helpers(basemesh)
    basemesh.name = "Body"
    basemesh.data.materials.clear()
    basemesh.data.materials.append(skin_material(C["skin"]))
    basemesh.data.materials.append(mat.flat("Void", "#050507", rough=0.06, metal=1.0))
    for p in basemesh.data.polygons:
        p.material_index = 0
    return basemesh, rig, L, assets


def snapshot(body, rig, L):
    """The pristine body as a hidden object for garments to grow from."""
    at = body.data.attributes.new("src_index", "INT", "POINT")
    at.data.foreach_set("value", list(range(len(body.data.vertices))))
    me = body.data.copy()
    src = link(bpy.data.objects.new("BodySource", me))
    src.hide_render = True
    return Source(src, rig, L)


def rib_material(key, color, ribs=True):
    """Ribbed knit for hems and cuffs: the knit set plus vertical ribs (a
    sine bump along the band's U)."""
    m = fabric(key, color, "cotton_jersey", rough=0.9, normal=0.4, uv=True, tiling=(20, 2))
    if ribs:
        nt = m.node_tree
        p = mat.principled(m)
        tc = nt.nodes.new("ShaderNodeTexCoord")
        sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        nt.links.new(tc.outputs["UV"], sep.inputs["Vector"])
        mul = nt.nodes.new("ShaderNodeMath")
        mul.operation = "MULTIPLY"
        mul.inputs[1].default_value = 2 * math.pi * 90
        nt.links.new(sep.outputs["X"], mul.inputs[0])
        sn = nt.nodes.new("ShaderNodeMath")
        sn.operation = "SINE"
        nt.links.new(mul.outputs[0], sn.inputs[0])
        bump = nt.nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = 0.6
        bump.inputs["Distance"].default_value = 0.002
        nt.links.new(sn.outputs[0], bump.inputs["Height"])
        if p.inputs["Normal"].is_linked:
            nt.links.new(p.inputs["Normal"].links[0].from_socket, bump.inputs["Normal"])
        nt.links.new(bump.outputs["Normal"], p.inputs["Normal"])
    return m


def band(src, shell, loop, direction, length, squeeze, name, material, rows=3, lip=0.004):
    """A ribbed band continuing a garment past an opening (hem, cuff): the
    loop is carried `length` along `direction`, tightened by `squeeze`, and
    turned in at its end so the edge has thickness."""
    pts = [v.co.copy() for v in loop]
    n = len(pts)
    # Even out the loop (it follows the body's topology).
    for _ in range(4):
        pts = [(pts[i - 1] + pts[i] * 2 + pts[(i + 1) % n]) / 4 for i in range(n)]
    c = sum(pts, Vector()) / n
    d = Vector(direction).normalized()
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new("UVMap")
    rings = []
    for k in range(rows + 1):
        t = k / rows
        ring = []
        for p in pts:
            r = p - c
            axial = d * r.dot(d)
            radial = r - axial
            q = c + axial + radial * (1 - squeeze * t) + d * (length * t)
            if k == 0:
                q = q + radial.normalized() * 0.0015  # sits just over the garment edge
            ring.append(q)
        rings.append(ring)
    last = rings[-1]
    lipr = [q - (q - (c + d * length)).normalized() * lip * 1.0 for q in last]
    inner = [q - d * length * 0.5 for q in lipr]
    rings += [lipr, inner]
    V = [[bm.verts.new(q) for q in ring] for ring in rings]
    for k in range(len(V) - 1):
        for i in range(n):
            j = (i + 1) % n
            f = bm.faces.new((V[k][i], V[k][j], V[k + 1][j], V[k + 1][i]))
            for lp, (u, v) in zip(f.loops, ((i, k), (i + 1, k), (i + 1, k + 1), (i, k + 1))):
                lp[uv].uv = (u / n, v / (len(V) - 1))
    bm.normal_update()
    out = sum((f.normal.dot(f.calc_center_median() - c) for f in bm.faces[: n * rows]), 0.0)
    if out < 0:
        for f in bm.faces:
            f.normal_flip()
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(material)
    obj = link(bpy.data.objects.new(name, me))
    for p in me.polygons:
        p.use_smooth = True
    transfer_weights(src.obj, obj)
    return obj


def shell_loops(shell):
    bm = bmesh.new()
    bm.from_mesh(shell.data)
    loops = boundary_loops(bm)
    out = []
    for lp in loops:
        out.append([type("V", (), {"co": v.co.copy(), "index": v.index})() for v in lp])
    bm.free()
    return out


def pocket(src, shell, hem_z, name="pocket", w0=0.14, w1=0.105, h=0.155):
    S = src.L["top"] / 1.72
    w0, w1, h = w0 * S, w1 * S, h * S
    """Kangaroo pocket: a clean trapezoid panel projected onto the belly of
    the hoodie, 4 mm proud, with a stitched rim; the slanted side openings
    read in its outline."""
    tb = bmesh.new()
    tb.from_mesh(shell.data)
    tree = BVHTree.FromBMesh(tb)
    tb.free()
    nu, nv = 14, 7
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new("UVMap")
    grid = []
    for j in range(nv + 1):
        t = j / nv
        z = hem_z + 0.012 + h * t
        half = w0 + (w1 - w0) * t
        row = []
        for i in range(nu + 1):
            u = i / nu
            # The side openings slant in toward the top.
            x = (-half + 2 * half * u)
            hit = tree.ray_cast(Vector((x, 0.5, z)), Vector((0, -1, 0)), 1.0)
            if hit[0] is None or hit[1].y < 0.3:
                bm.free()
                log("pocket: no clean belly to sit on, skipped")
                return None
            row.append(bm.verts.new(hit[0] + hit[1] * 0.0045))
        grid.append(row)
    for j in range(nv):
        for i in range(nu):
            f = bm.faces.new((grid[j][i], grid[j][i + 1], grid[j + 1][i + 1], grid[j + 1][i]))
            for lp, (u, v) in zip(f.loops, ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1))):
                lp[uv].uv = (u / nu, v / nv)
    bm.normal_update()
    edges = [e for e in bm.edges if e.is_boundary]
    ret = bmesh.ops.extrude_edge_only(bm, edges=edges)
    for v in [g for g in ret["geom"] if isinstance(g, bmesh.types.BMVert)]:
        hit, nrm, _, _ = tree.find_nearest(v.co, 0.05)
        if hit is not None:
            v.co = hit - nrm * 0.001
    bm.normal_update()
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = link(bpy.data.objects.new(name, me))
    for p in me.polygons:
        p.use_smooth = True
    transfer_weights(src.obj, obj)
    return obj


def tube(name, pts, radius, sides=8, material=None, cap=True):
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new("UVMap")
    rings = []
    n = len(pts)
    for i, p in enumerate(pts):
        t = (pts[min(i + 1, n - 1)] - pts[max(i - 1, 0)]).normalized()
        a = t.orthogonal().normalized()
        b = t.cross(a)
        r = radius(i / (n - 1)) if callable(radius) else radius
        rings.append([bm.verts.new(p + (a * math.cos(2 * math.pi * k / sides) + b * math.sin(2 * math.pi * k / sides)) * r)
                      for k in range(sides)])
    for i in range(n - 1):
        for k in range(sides):
            k2 = (k + 1) % sides
            f = bm.faces.new((rings[i][k], rings[i][k2], rings[i + 1][k2], rings[i + 1][k]))
            for lp, (u, v) in zip(f.loops, ((k, i), (k + 1, i), (k + 1, i + 1), (k, i + 1))):
                lp[uv].uv = (u / sides, v / (n - 1))
    if cap:
        bm.faces.new(rings[0][::-1])
        bm.faces.new(rings[-1])
    bm.normal_update()
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    if material:
        me.materials.append(material)
    obj = link(bpy.data.objects.new(name, me))
    for p in me.polygons:
        p.use_smooth = True
    return obj


def drawstrings(src, hood, torso, color="#e6e3ea", aglet="#b9b9c0"):
    """Two cords out of the hood's bottom, down the chest, metal aglets."""
    tb = bmesh.new()
    tb.from_mesh(torso.data)
    tree = BVHTree.FromBMesh(tb)
    tb.free()
    rim = [v.co for v in hood.data.vertices]
    low = min(rim, key=lambda c: c.z + abs(c.x) * 2 - c.y * 0.5)
    out = []
    m_s = prop_mat("string", color, rough=0.85)
    m_a = prop_mat("aglet", aglet, rough=0.3, metal=1.0)
    for sgn in (1, -1):
        start = Vector((sgn * 0.028, low.y + 0.01, low.z + 0.01))
        pts = []
        for k in range(11):
            t = k / 10
            p = start + Vector((sgn * 0.006 * t, 0.0, -0.26 * t))
            hit, nrm, _, _ = tree.find_nearest(p, 0.3)
            if hit is not None:
                p = hit + nrm * (0.007 + 0.004 * (1 - t))
            pts.append(p)
        cord = tube("string", pts, 0.0034, 6, m_s)
        end = pts[-1]
        d = (pts[-1] - pts[-2]).normalized()
        tip = tube("aglet", [end + d * 0.002, end + d * 0.022], 0.0043, 8, m_a)
        for o in (cord, tip):
            transfer_weights(src.obj, o)
            out.append(o)
    return out


def dress(src, body, rig, assets):
    """Grow the character's shell garments; cut the skin they cover."""
    covered = np.zeros(len(src.co), bool)
    shells = []
    for gid in C["wear"]:
        if gid == "polo.collar":
            for t in polo_trims(src, assets.get("polo")):
                t.parent = rig
                t.modifiers.new("Armature", "ARMATURE").object = rig
                shells.append(t)
            continue
        if gid not in GARMENTS:
            continue
        spec = GARMENTS[gid](src)
        keep = spec["keep"]
        sh = grow_shell(src, gid, keep, spec["off"], spec["gap"], smooth=spec.get("smooth", 30),
                        rounds=spec.get("rounds", 4))
        sh.parent = rig
        sh.modifiers.new("Armature", "ARMATURE").object = rig
        shells.append(sh)
        covered |= src.neighbours(keep)
        log(f"garment {gid}: {tris(sh)} tris")
        trims = []
        want = spec.get("trims", ())
        base = gid.split(".")[0]
        key = {"hoodie": "hoodie", "sweat": "hoodie", "tee": "tee", "joggers": "pants", "pyjama": "pants"}[base]
        rib = rib_material("rib_" + key, colour("rib_" + key, colour("rib", colour(key))) if key != "pants" else colour("rib_pants", colour("pants")))
        loops = shell_loops(sh)
        neck_z = src.bone["neck_01"][0].z
        S = src.L["top"] / 1.72
        bnd = lambda s_, sh_, lp_, d_, ln, sq, nm, m_, **kw: band(s_, sh_, lp_, d_, ln * S, sq, nm, m_, **kw)  # noqa: E731
        for lp in loops:
            cc = sum((v.co for v in lp), Vector()) / len(lp)
            near_hand = min((cc - src.bone[f"hand_{s_}"][0]).length for s_ in "lr")
            near_elbow = min((cc - src.bone[f"lowerarm_{s_}"][0]).length for s_ in "lr")
            if "cuffs" in want and near_hand < 0.14:
                s_ = "r" if cc.x > 0 else "l"
                d = src.bone[f"hand_{s_}"][0] - src.bone[f"lowerarm_{s_}"][0]
                trims.append(bnd(src, sh, lp, d, 0.055, 0.28, "cuff", rib))
            elif "sleeves" in want and abs(cc.x) > 0.15 and cc.z > neck_z - 0.35:
                s_ = "r" if cc.x > 0 else "l"
                d = src.bone[f"lowerarm_{s_}"][0] - src.bone[f"upperarm_{s_}"][0]
                trims.append(bnd(src, sh, lp, d, 0.014, 0.0, "sleevehem", rib, rows=1, lip=0.002))
            elif ("hem" in want or "hem.thin" in want) and cc.z < src.bone["spine_02"][0].z and abs(cc.x) < 0.1:
                if "hem.thin" in want:
                    trims.append(bnd(src, sh, lp, (0, 0, -1), 0.012, 0.0, "hem", rib, rows=1, lip=0.002))
                else:
                    trims.append(bnd(src, sh, lp, (0, 0, -1), 0.065, 0.05, "hem", rib))
            elif ("collar" in want or "collar.thin" in want) and cc.z > neck_z - 0.12 and abs(cc.x) < 0.1:
                h = 0.012 if "collar.thin" in want else 0.022
                trims.append(bnd(src, sh, lp, (0, -0.15, 1), h, 0.12, "collar", rib, rows=1, lip=0.003))
            elif ("anklecuffs" in want or "anklehems" in want) and cc.z < 0.4:
                if "anklecuffs" in want:
                    trims.append(bnd(src, sh, lp, (0, 0, -1), 0.06, 0.1, "anklecuff", rib))
                else:
                    trims.append(bnd(src, sh, lp, (0, 0, -1), 0.02, 0.0, "anklehem", rib, rows=1, lip=0.003))
        if "pocket" in want:
            pk = pocket(src, sh, hem_hip(src))
            if pk is not None:
                trims.append(pk)
        for t in trims:
            t.parent = rig
            t.modifiers.new("Armature", "ARMATURE").object = rig
            shells.append(t)
        if spec.get("hood") == "up":
            hood = make_hood(src, sh)
            hood.parent = rig
            hood.modifiers.new("Armature", "ARMATURE").object = rig
            shells.append(hood)
            for o in drawstrings(src, hood, sh):
                o.parent = rig
                o.modifiers.new("Armature", "ARMATURE").object = rig
                shells.append(o)
            # The hood hides the head, all but the face.
            for i in range(len(src.co)):
                if src.dom[i] in HEADS and not covered[i]:
                    co = src.co[i]
                    front = co[1] > src.L["ear_y"] - 0.01
                    if not front or oval_radius(src.L, co) > 1.12:
                        covered[i] = True
            log(f"garment hood: {tris(hood)} tris")
        elif spec.get("hood") == "down":
            hd = hood_down(src, sh)
            hd.parent = rig
            hd.modifiers.new("Armature", "ARMATURE").object = rig
            shells.append(hd)
    # MPFB pieces: the suit's own delete group, but only near the piece that
    # was kept (suits are split up), plus any skin just under or poking
    # through it (tight jeans), plus the shoes' delete group.
    groups = {vg.name: vg.index for vg in src.obj.vertex_groups}
    member = {}
    for v in src.obj.data.vertices:
        for g in v.groups:
            if g.weight > 0.5:
                member.setdefault(g.group, set()).add(v.index)
    for o in list(assets.values()):
        key = o.get("mpfb_key")
        if key == "hair":
            continue
        ob = bmesh.new()
        ob.from_mesh(o.data)
        tree = BVHTree.FromBMesh(ob)
        edge_pts = [v.co.copy() for v in ob.verts if v.is_boundary]
        ob.free()
        kd = KDTree(max(1, len(edge_pts)))
        for k, c in enumerate(edge_pts):
            kd.insert(c, k)
        kd.balance()
        spec = next((sp for sp in C.get("mpfb", ()) if sp["key"] == key), None)
        gname = f"Delete.{spec['id']}" if spec else f"Delete.{C['shoes'][0]}"
        dgroup = member.get(groups.get(gname, -1), set())
        for i in range(len(src.co)):
            if covered[i]:
                continue
            p = Vector(src.co[i])
            hit, nrm, _, dist = tree.find_nearest(p, 0.05)
            if hit is None:
                continue
            # Skin near a garment's openings stays (you see into sleeves and
            # collars): only what's well inside goes.
            edge = kd.find(hit)[2] if edge_pts else 1.0
            behind = edge > 0.02 and (p - hit).dot(nrm) < 0.002
            if (i in dgroup and dist < 0.05 and edge > 0.045) or (behind and dist < 0.035) or (not spec and i in dgroup):
                covered[i] = True
    # The skin under clothes goes (no poke-through, fewer triangles).
    lay = body.data.attributes["src_index"]
    idx = [d.value for d in lay.data]
    delete_verts(body, lambda v: idx[v.index] >= 0 and covered[idx[v.index]])
    return shells


def main():
    if lib.flag("cpu"):  # Metal kernel compiles can crash with many Blenders running
        from lib import bake
        bake.setup_cycles(device="CPU")
    body, rig, L, assets = build_body()
    src = snapshot(body, rig, L)
    void_face(body, L, 1)
    shells = dress(src, body, rig, assets)
    log(f"{CHAR}: body {tris(body)} tris, height {L['top']:.3f} m ({time.time() - T0:.1f}s)")
    if STAGE == "clothes":
        if PREVIEW:
            from lib import preview
            preview.render_previews(PREVIEW, [body] + shells + list(assets.values()), prefix="clothes_")
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(CACHE, "clothes.blend"))
        return
    R = Rig(rig)
    attach, pieces = equip(R, rig, L, src, shells)
    from lib import mesh as lmesh
    for o in pieces:
        if not o.name.startswith(("phone", "tablet")):
            lmesh.uv_smart(o, angle=60, margin=0.02)
    trim_hair(assets.get("hair"))
    dress_materials(shells, assets)
    fit_budget(body, shells + [a for k, a in assets.items() if k != "hair"] + pieces,
               [assets["hair"]] if "hair" in assets else [])
    if not lib.flag("nofolds") and STAGE != "grip":
        for sh in shells:
            base = sh.name.split(".")[0]
            if base in ("hoodie", "sweat"):
                FOLDS.append((sh, cloth_settle(sh, src, pin_top(src), frames=30, shrink=0.025, bending=0.04)))
            elif base == "tee":
                FOLDS.append((sh, cloth_settle(sh, src, pin_top(src), frames=24, shrink=0.02, bending=0.05)))
            elif base in ("joggers", "pyjama"):
                FOLDS.append((sh, cloth_settle(sh, src, pin_waist(src))))
        log(f"{CHAR}: cloth settled ({time.time() - T0:.1f}s)")
    shoes = assets.get("shoes")
    outfit_parts = shells + [a for k, a in assets.items() if k != "hair"] + pieces
    if STAGE != "grip":
        bake_outfit(outfit_parts, shoes)
        log(f"{CHAR}: atlas baked ({time.time() - T0:.1f}s)")
    hair = [assets["hair"]] if "hair" in assets else []
    for o in outfit_parts:
        if o.get("mpfb_key") == "shoes" or o in pieces:
            continue
        stiffen_ends(o)
    char = finish_mesh(body, outfit_parts + hair, rig)
    bpy.data.objects.remove(src.obj)
    solver = Solver(R)
    global ANIM
    ANIM = animate(R, solver, L, attach)
    solver.clear()
    log(f"{CHAR}: animated ({time.time() - T0:.1f}s)")
    if STAGE == "anim":
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(CACHE, "anim.blend"))
        return
    if STAGE == "grip":
        grip_review(rig, char, PREVIEW or os.path.join(CACHE, "grip"))
        return
    export(rig, char)
    if PREVIEW:
        floor_check(rig, char)
        grip_check(rig, char)
        previews(rig, char, PREVIEW)


def export(rig, char):
    from lib import export as lexp
    for t in rig.animation_data.nla_tracks:
        t.mute = False
    rig.animation_data.action = None
    raw = os.path.join(CACHE, f"{CHAR}_raw.glb")
    lexp.export_glb(raw, [rig], animations=True, skins=True, export_optimize_animation_size=False)
    os.makedirs(os.path.dirname(os.path.abspath(OUT)), exist_ok=True)
    lexp.compress(raw, OUT, max_texture=1024, quantize_position=True)
    size = os.path.getsize(OUT)
    # Over budget: the normal atlas (UASTC) is the heaviest texture; step it down.
    normal = bpy.data.images.get(f"{CHAR}_outfit_normal")
    for dim in (768, 512):
        if size <= 1.7 * 1024 * 1024 or normal is None:  # safely under 1.8 MB
            break
        normal.scale(dim, dim)
        normal.save()
        lexp.export_glb(raw, [rig], animations=True, skins=True, export_optimize_animation_size=False)
        lexp.compress(raw, OUT, max_texture=1024, quantize_position=True)
        size = os.path.getsize(OUT)
        log(f"{CHAR}: normal atlas down to {dim} for the size budget ({size / 1024:.0f} KB)")
    mats = [m.name for m in char.data.materials]
    clips = [(n, f) for n, f, _, _ in CLIPS]
    log(f"{CHAR}: {tris(char)} tris, {len(mats)} materials {mats}, {size / 1024:.0f} KB, clips {clips}")


def closeups(out, shots, size=768):
    """Explicit-camera renders (no floor): [(name, camera, target, lens)]."""
    from lib import preview
    saved_world = scene.world
    scene.world = preview._studio_world()
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = scene.render.resolution_y = size
    scene.view_settings.view_transform = "AgX"
    cd = bpy.data.cameras.new("_cu")
    cd.clip_start = 0.01
    cam = link(bpy.data.objects.new("_cu", cd))
    scene.camera = cam
    lights = []
    for nm, col in (("k", (1, 0.96, 0.9)), ("f", (0.8, 0.88, 1.0)), ("r", (1, 1, 1))):
        ld = bpy.data.lights.new("_cu_" + nm, "AREA")
        ld.size, ld.color = 0.6, col
        lights.append(link(bpy.data.objects.new("_cu_" + nm, ld)))
    paths = []
    for name, c, t, lens in shots:
        c, t = Vector(c), Vector(t)
        cd.lens = lens
        cam.location = c
        cam.rotation_euler = (t - c).to_track_quat("-Z", "Y").to_euler()
        back = (c - t).normalized()
        right = back.cross(Vector((0, 0, 1))).normalized() * -1
        dist = (c - t).length
        for lo, off, e in zip(lights, (right * 0.8 + Vector((0, 0, 0.7)), -right * 0.9 + Vector((0, 0, 0.1)),
                                       -back * 1.2 + Vector((0, 0, 0.8))), (70, 25, 80)):
            lo.location = t + back * dist * 0.3 + off * dist
            lo.rotation_euler = (t - lo.location).to_track_quat("-Z", "Y").to_euler()
            lo.data.energy = e * dist * dist
        path = os.path.join(out, f"close_{name}.png")
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        paths.append(path)
    for o in [cam] + lights:
        bpy.data.objects.remove(o)
    scene.world = saved_world
    return paths


def grip_check(rig, char, clip="idle", frame=0):
    """Hand skin against the held phone/tablet in a clip frame: vertices inside
    the prop and across its screen (logged; the grip solver aims for none)."""
    props = C["props"]
    kind = "tablet" if any(p.startswith("tablet") for p in props) else "phone"
    pl = bpy.data.objects.get("PhoneLight")
    if pl is None or any(p.startswith("selfie") for p in props):
        return None
    for t in rig.animation_data.nla_tracks:
        t.mute = True
    rig.animation_data.action = bpy.data.actions[clip]
    scene.frame_set(frame)
    dg = bpy.context.evaluated_depsgraph_get()
    w, h, t, r = PROP_DIMS[kind]
    off = 0.03 if kind == "tablet" else 0.025
    ev = char.evaluated_get(dg)
    me = ev.to_mesh()
    co = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3).astype(np.float64)
    skin_i = [i for i, m in enumerate(char.data.materials) if m and m.name == "Skin"]
    skin = np.zeros(len(me.vertices), bool)
    for p in me.polygons:
        if p.material_index in skin_i:
            skin[list(p.vertices)] = True
    ev.to_mesh_clear()
    M = np.array((pl.matrix_world @ Matrix.Translation((0, 0, -off))).inverted() @ char.matrix_world)
    loc = co @ M[:3, :3].T + M[:3, 3]
    d, dxy = slab_sdf(loc, w, h, t, r)
    inside = skin & (d < -0.001)
    over = skin & (loc[:, 2] > t / 2) & (loc[:, 2] < t / 2 + 0.03) & (dxy < -0.003)
    rig.animation_data.action = None
    scene.frame_set(0)
    names = {g.index: g.name for g in char.vertex_groups}
    tg = char.vertex_groups.get("thumb_03_r")
    if tg is not None:
        th = np.array([any(g.group == tg.index and g.weight > 0.5 for g in v.groups) for v in char.data.vertices])
        if (th & skin).any():
            log(f"{CHAR}: grip check: thumb pad {float(d[th & skin].min()) * 1000:+.1f} mm off the {kind}")

    def by_bone(mask):
        out = {}
        for i in np.nonzero(mask)[0]:
            gs = char.data.vertices[int(i)].groups
            b = names[max(gs, key=lambda g: g.weight).group] if len(gs) else "-"
            out[b] = out.get(b, 0) + 1
        return " ".join(f"{b}:{k}" for b, k in sorted(out.items()))
    if lib.flag("gripdebug"):
        for i in np.nonzero(inside)[0][np.argsort(d[inside])][:8]:
            gs = char.data.vertices[int(i)].groups
            log(f"  inside: {names[max(gs, key=lambda g: g.weight).group]} local {np.round(loc[i] * 1000, 1)} mm, d {d[i] * 1000:.1f}")
    log(f"{CHAR}: grip check ({clip} {frame}): {int(inside.sum())} skin verts inside the {kind} "
        f"(deepest {max(0.0, -float(d[skin].min())) * 1000:.1f} mm) [{by_bone(inside)}], "
        f"{int(over.sum())} across its screen [{by_bone(over)}]")
    return int(inside.sum()), int(over.sum())


def grip_review(rig, char, out):
    """Fast grip iteration (--stage grip): the check plus the two grip close-ups."""
    os.makedirs(out, exist_ok=True)
    grip_check(rig, char)
    for t in rig.animation_data.nla_tracks:
        t.mute = True
    rig.animation_data.action = bpy.data.actions["idle"]
    scene.frame_set(0)
    bpy.context.view_layer.update()
    pl = bpy.data.objects.get("PhoneLight")
    c = pl.matrix_world.translation
    z = pl.matrix_world.to_3x3().col[2]
    from lib import preview
    paths = closeups(out, [("grip", c + z * 0.24 + Vector((0, 0, 0.02)), c, 50),
                           ("grip_out", c + Vector((0.3, 0.45, 0.05)), c, 50),
                           ("grip_side", c + Vector((-0.35, 0.05, 0.12)), c, 50)])
    preview.contact_sheet(paths, os.path.join(out, "grip_sheet.png"))


def floor_check(rig, char):
    """Lowest point of the skinned mesh per clip (the track is at z = 0)."""
    for t in rig.animation_data.nla_tracks:
        t.mute = True
    res = []
    for name, n, loop, _ in CLIPS:
        rig.animation_data.action = bpy.data.actions[name]
        lo = 9.0
        for f in range(0, n + 1, 2):
            scene.frame_set(f)
            dg = bpy.context.evaluated_depsgraph_get()
            ev = char.evaluated_get(dg)
            me = ev.to_mesh()
            co = np.empty(len(me.vertices) * 3, np.float32)
            me.vertices.foreach_get("co", co)
            lo = min(lo, float(co[2::3].min()))
            ev.to_mesh_clear()
        res.append(f"{name} {lo:+.3f}")
    rig.animation_data.action = None
    scene.frame_set(0)
    log(f"{CHAR}: lowest point per clip (m): " + ", ".join(res))


def previews(rig, char, out):
    """Review renders: the standing pose (idle frame 0) from four sides, the
    bind pose, close-ups of the void and the grip, and frames of the clips."""
    from lib import preview
    os.makedirs(out, exist_ok=True)
    for t in rig.animation_data.nla_tracks:
        t.mute = True

    def at(clip, frame):
        rig.animation_data.action = bpy.data.actions[clip] if clip else None
        if clip is None:
            for pb in rig.pose.bones:
                pb.location = (0, 0, 0)
                pb.rotation_quaternion = (1, 0, 0, 0)
        scene.frame_set(frame)

    at("idle", 0)
    preview.render_previews(out, [char], views=("front", "side", "back", "three_quarter"), prefix="rest_")
    at(None, 0)
    preview.render_previews(out, [char], views=("front",), prefix="bind_", sheet=False)
    shots = [("run", f) for f in (0, 4, 8, 12)] + [("roll", 9), ("grind", 0), ("fly", 6), ("kicks", 11), ("jump", 10),
                                                   ("present", 36)]
    paths = []
    for clip, f in shots:
        at(clip, f)
        paths += preview.render_previews(out, [char], views=("side",) if clip != "grind" else ("three_quarter",),
                                         prefix=f"{clip}{f:02d}_", sheet=False)
    at("run", 4)
    preview.render_previews(out, [char], views=("game",), prefix="run04_", sheet=False)
    preview.contact_sheet(paths[:4], os.path.join(out, "run_sheet.png"))
    preview.contact_sheet(paths[4:], os.path.join(out, "clips_sheet.png"))
    # Close-ups: the void, the grip from the screen side and from outside.
    at("idle", 0)
    bpy.context.view_layer.update()
    pl = bpy.data.objects.get("PhoneLight")
    head = rig.pose.bones["head"]
    hm = rig.matrix_world @ head.matrix
    eye = hm @ (head.bone.matrix_local.inverted() @ ANIM.eye_rest)
    close = []
    shots = [("face", eye + Vector((0.25, 0.55, 0.1)), eye, 60)]
    if pl is not None:
        c = pl.matrix_world.translation
        z = pl.matrix_world.to_3x3().col[2]
        shots += [("grip", c + z * 0.24 + Vector((0, 0, 0.02)), c, 50), ("grip_out", c + Vector((0.3, 0.45, 0.05)), c, 50)]
    close = closeups(out, shots)
    preview.contact_sheet(close, os.path.join(out, "close_sheet.png"))
    log(f"previews in {out}")


main()
