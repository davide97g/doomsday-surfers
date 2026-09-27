# glb export with the contract's options (docs/assets-v2.md "Export"), then
# compression through gltf-transform (scripts/compress-glb.ts: meshopt, and
# KTX2 textures when tools/ktx/ktx exists, else WebP).
#
#   path = export_glb("public/assets/kits/common.glb", objects)      # or collection=...
#   compress(path, max_texture=2048)                                  # in place
#   export_glb(out, [rig, body], animations=True, skins=True)         # characters
#   compress(out, max_texture=1024, quantize_position=True)
#
# Export options: GLB, Y-up, TEXCOORD_0 + normals, no tangents (three.js
# derives them in the fragment shader, which keeps normal maps right under
# the bend), custom properties as glTF extras, modifiers NOT applied (apply
# them yourself: mesh.apply_modifiers), no cameras or lights.

import os
import shutil
import subprocess

import bpy

from . import ROOT, log


def _with_children(objs):
    out = []
    for o in objs:
        if o not in out:
            out.append(o)
        for c in o.children_recursive:
            if c not in out:
                out.append(c)
    return out


def export_glb(path, objects=None, collection=None, animations=False, extras=True, skins=None, deform_bones=True,
               children=True, **options):
    """Export objects (plus their children), a collection, or (neither) the
    whole scene to a .glb. Extra exporter options pass through (`export_*`).
    Returns the absolute path."""
    path = os.path.abspath(path if os.path.isabs(path) else os.path.join(ROOT, path))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    if collection is not None:
        objects = list(collection.all_objects)
    selection = objects is not None
    if selection:
        objs = _with_children(objects) if children else list(objects)
        vl = bpy.context.view_layer
        for o in vl.objects:
            o.select_set(False)
        for o in objs:
            o.hide_set(False)
            o.hide_select = False
            o.select_set(True)
        if objs:
            vl.objects.active = objs[0]
    if skins is None:
        skins = any(o.type == "ARMATURE" for o in (objects or bpy.context.scene.objects))
    kw = dict(
        filepath=path,
        export_format="GLB",
        use_selection=selection,
        export_yup=True,
        export_apply=False,
        export_texcoords=True,
        export_normals=True,
        export_tangents=False,
        export_extras=extras,
        export_cameras=False,
        export_lights=False,
        export_materials="EXPORT",
        export_image_format="AUTO",
        export_unused_images=False,
        export_unused_textures=False,
        export_animations=animations,
        export_skins=skins,
        export_def_bones=bool(skins and deform_bones),
        export_morph=False,
        export_gpu_instances=False,
    )
    if animations:
        kw.update(export_animation_mode="ACTIONS", export_force_sampling=True, export_optimize_animation_size=True,
                  export_frame_step=1)
    kw.update(options)
    result = bpy.ops.export_scene.gltf(**kw)
    if "FINISHED" not in result:
        raise RuntimeError(f"glTF export failed: {result}")
    shown = os.path.relpath(path, ROOT) if path.startswith(ROOT) else path
    log(f"export: {shown} ({os.path.getsize(path) // 1024} KB raw)")
    return path


def _bun():
    for cand in (shutil.which("bun"), os.path.expanduser("~/.bun/bin/bun"), "/opt/homebrew/bin/bun"):
        if cand and os.path.exists(cand):
            return cand
    raise FileNotFoundError("bun not found (install Bun, https://bun.sh)")


def ktx_available():
    return os.path.exists(os.path.join(ROOT, "tools", "ktx", "ktx")) or shutil.which("ktx") is not None


def compress(path, out=None, max_texture=1024, textures="auto", meshopt=True, quantize_position=False, inspect=False):
    """Compress a .glb with gltf-transform (in place unless `out`).

    textures: "auto" (KTX2 if tools/ktx/ktx exists, else WebP) | "ktx2" |
    "webp" | "keep". max_texture: 1024 characters/props, 2048 kit atlases.
    quantize_position: off by default so every node keeps a plain float
    geometry and an untouched matrix (kits are read node by node).
    inspect=True prints `gltf-transform inspect`. Returns the output path."""
    out = out or path
    cmd = [_bun(), os.path.join(ROOT, "scripts", "compress-glb.ts"), path, out, "--max-texture", str(max_texture),
           "--textures", textures]
    if quantize_position:
        cmd.append("--quantize-position")
    if not meshopt:
        cmd.append("--no-meshopt")
    env = dict(os.environ)
    ktx_dir = os.path.join(ROOT, "tools", "ktx")
    env["PATH"] = os.pathsep.join([ktx_dir, env.get("PATH", ""), os.path.dirname(cmd[0])])
    run = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env=env)
    if run.returncode != 0:
        raise RuntimeError(f"compress failed:\n{run.stdout}\n{run.stderr}")
    for line in run.stdout.strip().splitlines():
        if line.startswith("compress:"):
            log(line)
    if inspect:
        log(inspect_glb(out))
    return out


def inspect_glb(path):
    """`gltf-transform inspect` output (scenes, meshes, materials, textures)."""
    gt = os.path.join(ROOT, "node_modules", "@gltf-transform", "cli", "bin", "cli.js")
    cmd = [_bun(), gt, "inspect", path] if os.path.exists(gt) else [_bun(), "x", "gltf-transform", "inspect", path]
    run = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env={**os.environ, "NO_COLOR": "1"})
    return run.stdout if run.returncode == 0 else run.stderr
