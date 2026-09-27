# Shared helpers for every asset script (assets/blender/*.py and
# assets/blender/kits/*.py). Contract: docs/assets-v2.md.
#
#   mat      Principled materials: CC0 texture sets (ambientCG / Poly Haven),
#            flat colours, glass, emissive screens, box mapping
#   mesh     primitives, bevel + weighted normals, edge loops for the bend,
#            apply/join/origin, triangle counts, UV unwraps, atlas packing
#   bake     Cycles bakes (Metal GPU, CPU fallback): albedo, normal, AO,
#            roughness, metal, emission, high->low; bake_kit_atlas()
#   export   glb export with the contract's options, then gltf-transform
#            compression (meshopt + KTX2 or WebP)
#   preview  Eevee review renders (front/side/back/three_quarter, turntable)
#
# Scripts run headless: blender -b -P assets/blender/kits/foo.py -- [args]
# Blender does not put the script's folder on sys.path, so every script
# starts with these lines (they work from assets/blender/ and kits/):
#
#   import os, sys
#   sys.dont_write_bytecode = True  # no __pycache__ in the repo
#   _d = os.path.dirname(os.path.abspath(__file__))
#   sys.path.insert(0, _d if os.path.isdir(os.path.join(_d, "lib")) else os.path.dirname(_d))
#   from lib import mat, mesh, bake, export, preview, log, arg
#
# Log lines are prefixed with the running script's name ("common: ..."), so a
# shell wrapper can `grep '^common:'` like scripts/assets.sh does for runner.

import os
import sys

import bpy

BLENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(BLENDER_DIR))
TEXTURES = os.path.join(ROOT, "assets", "textures")
PUBLIC = os.path.join(ROOT, "public", "assets")
TOOLS = os.path.join(ROOT, "tools")


def _script_name():
    argv = sys.argv
    for flag in ("-P", "--python"):
        if flag in argv and argv.index(flag) + 1 < len(argv):
            return os.path.splitext(os.path.basename(argv[argv.index(flag) + 1]))[0].lstrip("_")
    return "lib"


PREFIX = _script_name()


def log(*parts):
    """print() with the script-name prefix (flushes, so logs interleave right)."""
    print(f"{PREFIX}:", *parts, flush=True)


# ------------------------------------------------------------------ arguments

def argv():
    """Arguments after `--` on the blender command line (a fresh list)."""
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def arg(name, default=None, cast=str):
    """Value of `--name value` after `--` (or default). `arg("preview")`."""
    a = argv()
    key = "--" + name
    if key in a and a.index(key) + 1 < len(a):
        return cast(a[a.index(key) + 1])
    return default


def flag(name):
    """True when `--name` appears after `--`."""
    return ("--" + name) in argv()


def positional():
    """Arguments after `--` that are neither `--flags` nor their values."""
    a, out, i = argv(), [], 0
    while i < len(a):
        if a[i].startswith("--"):
            i += 2 if i + 1 < len(a) and not a[i + 1].startswith("--") else 1
            continue
        out.append(a[i])
        i += 1
    return out


# ------------------------------------------------------------------ scene

def reset_scene(fps=30):
    """Empty factory scene (no cube, camera or light). Returns the scene."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = fps
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    return scene


def link(obj, collection=None):
    """Link an object into `collection` (default: the scene collection)."""
    (collection or bpy.context.scene.collection).objects.link(obj)
    return obj


def collection(name, parent=None):
    """Get or create a collection linked under `parent` (default: scene)."""
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
    parent = parent or bpy.context.scene.collection
    if col.name not in parent.children:
        parent.children.link(col)
    return col


def texture_dir(id_or_path):
    """Folder of a fetched texture set: an id under assets/textures/ or a path."""
    if os.path.isdir(id_or_path):
        return os.path.abspath(id_or_path)
    path = os.path.join(TEXTURES, id_or_path)
    if not os.path.isdir(path):
        raise FileNotFoundError(
            f"texture set '{id_or_path}' not found in {TEXTURES}; add it to "
            "assets/texture-manifest.json and run `bun scripts/fetch-textures.ts`"
        )
    return path
