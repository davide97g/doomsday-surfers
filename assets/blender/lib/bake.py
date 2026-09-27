# Cycles bakes. Uses the Metal GPU when there is one (Apple silicon), else the
# CPU; a failed GPU bake is retried on the CPU.
#
#   bake_map([obj], "albedo", img)             one map; kinds below
#   bake_maps([obj], 1024, out_dir, "Hoodie", high=[sculpt])   normal/AO/... from a high-poly (selected to active)
#   bake_kit_atlas(objects, 2048, out_dir, "FeedKit", keep_materials=("ReelScreen", "Glass"))
#       packs every object into one shared UV atlas, bakes their current
#       materials (procedural, tiling CC0, box-mapped...) into
#       <name>_albedo.png / _normal.png / _orm.png (+ _emissive.png), then gives
#       them ONE atlas Principled material. Faces on keep_materials keep their
#       material and their own 0..1 UVs.
#
# Kinds: albedo (Base Color, unlit), roughness, metallic, alpha, occlusion (the
# material's AO map), emission (colour x strength), normal (tangent, OpenGL),
# ao (Cycles ambient occlusion from the geometry).
#
# Unlit channels are baked with the emission trick (the Principled input is
# routed into an Emission shader and baked as EMIT), so metals keep their
# albedo and nothing depends on lights. With several Principled nodes (Mix
# Shader) the first one is used.

import os

import bpy
import numpy as np

from . import log, mat, mesh

_DEVICE = None
SOCKET_KINDS = {"albedo": "Base Color", "roughness": "Roughness", "metallic": "Metallic", "alpha": "Alpha",
                "occlusion": "Occlusion", "emission": "Emission"}
DEFAULTS = {"albedo": (0.5, 0.5, 0.5, 1.0), "roughness": 0.5, "metallic": 0.0, "alpha": 1.0, "occlusion": 1.0,
            "emission": (0.0, 0.0, 0.0, 1.0)}
# Samples per kind: unlit channels only need a few for sub-texel filtering.
SAMPLES = {"normal": 8, "ao": 128}
DATA_KINDS = {"roughness", "metallic", "alpha", "occlusion", "normal", "ao"}


# ------------------------------------------------------------------ setup

def setup_cycles(samples=8, device="AUTO"):
    """Switch the scene to Cycles on the Metal GPU (or CPU). Returns "GPU"/"CPU"."""
    global _DEVICE
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = False
    if _DEVICE is None or device != "AUTO":
        _DEVICE = "CPU"
        if device in ("AUTO", "GPU"):
            try:
                prefs = bpy.context.preferences.addons["cycles"].preferences
                prefs.compute_device_type = "METAL"
                prefs.get_devices()
                gpus = [d for d in prefs.devices if d.type == "METAL"]
                for d in prefs.devices:
                    d.use = d.type == "METAL"
                if gpus:
                    _DEVICE = "GPU"
            except Exception as err:  # no Metal: CPU
                log(f"bake: no Metal GPU ({err}), baking on CPU")
    scene.cycles.device = _DEVICE
    if scene.world is None:
        scene.world = bpy.data.worlds.new("BakeWorld")
    return _DEVICE


def new_image(name, size, kind="albedo", alpha=False, float_buffer=False, fill=None):
    """Bake target: sRGB for albedo/emission, Non-Color for data maps.
    size: int or (w, h). Normal maps start flat (0.5, 0.5, 1)."""
    w, h = (size, size) if isinstance(size, int) else size
    old = bpy.data.images.get(name)
    if old is not None:
        bpy.data.images.remove(old)
    img = bpy.data.images.new(name, w, h, alpha=alpha, float_buffer=float_buffer)
    img.colorspace_settings.name = "Non-Color" if kind in DATA_KINDS else ("sRGB" if not float_buffer else "Linear Rec.709")
    if fill is None:
        fill = {"normal": (0.5, 0.5, 1.0, 1.0), "ao": (1, 1, 1, 1), "occlusion": (1, 1, 1, 1),
                "alpha": (1, 1, 1, 1)}.get(kind, (0.0, 0.0, 0.0, 1.0))
    img.generated_color = fill
    return img


def save_png(img, path):
    """Write an image as PNG (8-bit) and point the datablock at the file."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    return path


# ------------------------------------------------------------------ internals

def _materials(objects):
    seen = []
    for o in objects:
        for m in o.data.materials:
            if m is not None and m not in seen:
                seen.append(m)
    return seen


def _ensure_material(o):
    if not o.data.materials or all(m is None for m in o.data.materials):
        o.data.materials.clear()
        o.data.materials.append(mat.flat("_bake_default", (0.5, 0.5, 0.5)))
    for i, m in enumerate(o.data.materials):
        if m is None:
            o.data.materials[i] = mat.flat("_bake_default", (0.5, 0.5, 0.5))


class _Targets:
    """Put `image` as the active Image node in each material (dummy image for
    materials in `skip`), remove them afterwards."""

    def __init__(self, materials, image, skip=()):
        self.materials, self.image, self.skip = materials, image, set(skip)
        self.nodes = []

    def __enter__(self):
        dummy = None
        for m in self.materials:
            img = self.image
            if m.name in self.skip:
                dummy = dummy or new_image("_bake_dummy", 8, "roughness")
                img = dummy
            n = m.node_tree.nodes.new("ShaderNodeTexImage")
            n.image = img
            n.name = n.label = "_bake_target"
            n.location = (-1600, 600)
            n.select = True
            m.node_tree.nodes.active = n
            self.nodes.append((m, n))
        return self

    def __exit__(self, *exc):
        for m, n in self.nodes:
            m.node_tree.nodes.remove(n)
        d = bpy.data.images.get("_bake_dummy")
        if d is not None:
            bpy.data.images.remove(d)
        return False


def _source(m, kind):
    """(from_socket or None, default value) feeding the channel `kind`."""
    nodes = m.node_tree.nodes
    if kind == "occlusion":
        g = next((n for n in nodes if n.type == "GROUP" and n.node_tree and
                  n.node_tree.name in ("glTF Material Output", "glTF Settings")), None)
        if g is None or not g.inputs["Occlusion"].is_linked:
            return None, 1.0
        return g.inputs["Occlusion"].links[0].from_socket, 1.0
    p = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
    if p is None:
        return None, DEFAULTS[kind]
    if kind == "emission":
        return p.inputs["Emission Color"], p.inputs["Emission Strength"]
    sock = p.inputs[SOCKET_KINDS[kind]]
    if sock.is_linked:
        return sock.links[0].from_socket, sock.default_value
    v = sock.default_value
    return None, tuple(v) if hasattr(v, "__len__") else v


class _EmitTrick:
    """Route a material channel into an Emission shader on the output."""

    def __init__(self, materials, kind):
        self.materials, self.kind = materials, kind
        self.saved = []

    def __enter__(self):
        for m in self.materials:
            nt = m.node_tree
            out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output), None) or \
                next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None)
            if out is None:
                out = nt.nodes.new("ShaderNodeOutputMaterial")
            prev = out.inputs["Surface"].links[0].from_socket if out.inputs["Surface"].is_linked else None
            em = nt.nodes.new("ShaderNodeEmission")
            em.name = "_bake_emit"
            added = [em]
            if self.kind == "emission":
                col, strength = _source(m, "emission")
                if col is None:  # no Principled: no glow
                    em.inputs["Strength"].default_value = 0.0
                elif col.is_linked:
                    nt.links.new(col.links[0].from_socket, em.inputs["Color"])
                else:
                    em.inputs["Color"].default_value = col.default_value
                if col is None:
                    pass
                elif strength.is_linked:
                    nt.links.new(strength.links[0].from_socket, em.inputs["Strength"])
                else:
                    em.inputs["Strength"].default_value = strength.default_value
            else:
                src, value = _source(m, self.kind)
                em.inputs["Strength"].default_value = 1.0
                if src is not None:
                    nt.links.new(src, em.inputs["Color"])
                elif isinstance(value, tuple):
                    em.inputs["Color"].default_value = (*value[:3], 1.0)
                else:
                    em.inputs["Color"].default_value = (value, value, value, 1.0)
            nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
            self.saved.append((m, out, prev, added))
        return self

    def __exit__(self, *exc):
        for m, out, prev, added in self.saved:
            nt = m.node_tree
            for n in added:
                nt.nodes.remove(n)
            if prev is not None:
                nt.links.new(prev, out.inputs["Surface"])
        return False


def _select(objects, active):
    vl = bpy.context.view_layer
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for o in vl.objects:
        o.select_set(False)
    for o in objects:
        o.hide_set(False)
        o.hide_render = False
        o.select_set(True)
    vl.objects.active = active


def _run_bake(**kw):
    global _DEVICE
    try:
        return bpy.ops.object.bake(**kw)
    except RuntimeError as err:
        if _DEVICE != "GPU":
            raise
        log(f"bake: GPU bake failed ({str(err).strip()}), retrying on CPU")
        _DEVICE = "CPU"
        bpy.context.scene.cycles.device = "CPU"
        return bpy.ops.object.bake(**kw)


# ------------------------------------------------------------------ bakes

def bake_map(objects, kind, image, uv_layer=None, samples=None, margin=16, high=None, cage_extrusion=0.02,
             max_ray_distance=0.0, skip_materials=(), ao_distance=0.5, clear=False):
    """Bake one channel of `objects` into `image` (all objects share it, so
    their UVs in `uv_layer` must not overlap).

    high: objects to bake FROM (selected to active onto a single object in
    `objects`): normals of a sculpt, AO of a detailed shell, albedo..."""
    objects = objects if isinstance(objects, (list, tuple)) else [objects]
    setup_cycles(samples or SAMPLES.get(kind, 8))
    for o in objects + list(high or ()):
        _ensure_material(o)
    targets = _materials(objects)
    sources = _materials(high) if high else targets
    if kind == "ao":
        bpy.context.scene.world.light_settings.distance = ao_distance
    btype = {"normal": "NORMAL", "ao": "AO"}.get(kind, "EMIT")
    args = dict(type=btype, margin=margin, margin_type="EXTEND", use_clear=clear, target="IMAGE_TEXTURES",
                save_mode="INTERNAL", uv_layer=uv_layer or "")
    if btype == "NORMAL":
        args.update(normal_space="TANGENT", normal_r="POS_X", normal_g="POS_Y", normal_b="POS_Z")
    if high:
        if len(objects) != 1:
            raise ValueError("bake from high-poly needs exactly one low-poly object")
        args.update(use_selected_to_active=True, cage_extrusion=cage_extrusion, max_ray_distance=max_ray_distance)
        _select(list(high) + objects, objects[0])
    else:
        _select(objects, objects[0])
    trick = _EmitTrick(sources, kind) if btype == "EMIT" else None
    with _Targets(targets, image, skip_materials):
        if trick:
            with trick:
                _run_bake(**args)
        else:
            _run_bake(**args)
    return image


def pixels(img):
    """Image pixels as an (h, w, 4) float32 array (raw stored values)."""
    a = np.empty(len(img.pixels), dtype=np.float32)
    img.pixels.foreach_get(a)
    return a.reshape(img.size[1], img.size[0], 4)


def set_pixels(img, arr):
    img.pixels.foreach_set(np.ascontiguousarray(arr, dtype=np.float32).ravel())
    img.update()


def _linear_to_srgb(x):
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def bake_maps(objects, size, out_dir, name, kinds=("albedo", "normal", "orm"), uv_layer=None, high=None,
              skip_materials=(), alpha=False, emissive="auto", texture_ao=True, ao_samples=128, ao_distance=0.5,
              ao_isolate=True, margin=4, samples=8, cage_extrusion=0.02, max_ray_distance=0.0):
    """Bake a set of maps into PNGs <out_dir>/<name>_<map>.png.

    kinds: any of albedo, normal, orm (R occlusion, G roughness, B metal),
    roughness, metallic, ao. alpha=True writes the Alpha channel into the
    albedo's A. emissive "auto" bakes <name>_emissive.png if any material
    glows (True forces it). ao_isolate hides the other objects while each
    one's AO bakes (kit pieces often overlap at the origin).
    Returns {"albedo": Image, ..., "emissive_strength": float, "paths": {...}}."""
    objects = objects if isinstance(objects, (list, tuple)) else [objects]
    out = {"paths": {}, "emissive_strength": 1.0}
    kw = dict(uv_layer=uv_layer, margin=margin, high=high, skip_materials=skip_materials,
              cage_extrusion=cage_extrusion, max_ray_distance=max_ray_distance)

    def one(kind, fill_kind=None):
        img = new_image(f"{name}_{kind}", size, fill_kind or kind, alpha=(kind == "albedo" and alpha))
        bake_map(objects, kind, img, samples=samples if kind != "ao" else ao_samples, ao_distance=ao_distance, **kw)
        return img

    if "albedo" in kinds:
        a = one("albedo")
        if alpha:
            al = one("alpha")
            px = pixels(a)
            px[..., 3] = pixels(al)[..., 0]
            set_pixels(a, px)
            bpy.data.images.remove(al)
        out["albedo"] = a
    if "normal" in kinds:
        out["normal"] = one("normal")
    need_rough = "orm" in kinds or "roughness" in kinds
    need_metal = "orm" in kinds or "metallic" in kinds
    rough = one("roughness") if need_rough else None
    metal = one("metallic") if need_metal else None
    ao = None
    if "orm" in kinds or "ao" in kinds:
        ao = new_image(f"{name}_ao", size, "ao")
        if ao_isolate and len(objects) > 1 and not high:
            hidden = {o: o.hide_render for o in bpy.context.view_layer.objects}
            for o in objects:
                for other in hidden:
                    other.hide_render = other is not o
                bake_map([o], "ao", ao, samples=ao_samples, ao_distance=ao_distance, **kw)
            for o, h in hidden.items():
                o.hide_render = h
        else:
            bake_map(objects, "ao", ao, samples=ao_samples, ao_distance=ao_distance, **kw)
        if texture_ao:
            tex_ao = one("occlusion")
            px = pixels(ao)
            px[..., :3] *= pixels(tex_ao)[..., :3]
            set_pixels(ao, px)
            bpy.data.images.remove(tex_ao)
    if "orm" in kinds:
        orm = new_image(f"{name}_orm", size, "roughness")
        px = np.ones_like(pixels(orm))
        px[..., 0] = pixels(ao)[..., 0]
        px[..., 1] = pixels(rough)[..., 0]
        px[..., 2] = pixels(metal)[..., 0]
        set_pixels(orm, px)
        out["orm"] = orm
    for k, img in (("roughness", rough), ("metallic", metal), ("ao", ao)):
        if img is None:
            continue
        if k in kinds:
            out[k] = img
        else:
            bpy.data.images.remove(img)

    glowing = any(_glows(m) for m in _materials(high or objects) if m.name not in skip_materials)
    if emissive is True or (emissive == "auto" and glowing):
        f = new_image(f"{name}_emission_f", size, "emission", float_buffer=True)
        bake_map(objects, "emission", f, samples=samples, **kw)
        px = pixels(f)
        peak = float(max(px[..., :3].max(), 1e-6))
        strength = max(1.0, peak)
        e = new_image(f"{name}_emissive", size, "emission")
        srgb = np.ones_like(px)
        srgb[..., :3] = _linear_to_srgb(px[..., :3] / strength)
        set_pixels(e, srgb)
        bpy.data.images.remove(f)
        out["emissive"] = e
        out["emissive_strength"] = strength

    for k in ("albedo", "normal", "orm", "roughness", "metallic", "ao", "emissive"):
        if k in out:
            out["paths"][k] = save_png(out[k], os.path.join(out_dir, f"{name}_{k}.png"))
    log(f"bake: {name} {size}px -> {', '.join(sorted(out['paths']))} ({_DEVICE})")
    return out


def _glows(m):
    p = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if p is None:
        return False
    s = p.inputs["Emission Strength"]
    c = p.inputs["Emission Color"]
    return (s.is_linked or s.default_value > 0) and (c.is_linked or max(c.default_value[:3]) > 0)


def bake_kit_atlas(objects, size, out_dir, name="Kit", keep_materials=(), alpha=None, emissive="auto",
                   margin_px=8, unwrap="smart", weights=None, texture_ao=True, ao_samples=128, ao_distance=0.5,
                   ao_isolate=True, samples=8, material_name=None, apply=True):
    """Pack `objects` into one UV atlas, bake their materials into
    albedo/normal/ORM(/emissive) PNGs and give them one atlas material.

    keep_materials  names of materials left alone (screens the renderer fills,
                    glass, emissive signage): their faces keep their UVs
    alpha           None or "CLIP": albedo alpha + alphaMode MASK (foliage, hair)
    unwrap          "smart" | "box" | "keep" (see mesh.pack_uvs_to_atlas)
    weights         {obj_name: texel density multiplier}
    material_name   the atlas material's name (default: name)
    apply           apply each object's modifiers first (the atlas UVs must
                    live on the final mesh); armatures are kept
    Afterwards each object's only UV layer is the atlas (TEXCOORD_0)."""
    objects = [o for o in objects if o.type == "MESH"]
    for o in objects:
        if apply:
            mesh.apply_modifiers(o, only=[m.name for m in o.modifiers if m.type != "ARMATURE"])
        _ensure_material(o)
    mesh.pack_uvs_to_atlas(objects, size=size, margin_px=margin_px, layer="Atlas", unwrap=unwrap,
                           skip_materials=keep_materials, weights=weights)
    res = bake_maps(objects, size, out_dir, name, kinds=("albedo", "normal", "orm"), uv_layer="Atlas",
                    skip_materials=keep_materials, alpha=bool(alpha), emissive=emissive, texture_ao=texture_ao,
                    ao_samples=ao_samples, ao_distance=ao_distance, ao_isolate=ao_isolate,
                    margin=max(2, margin_px // 2), samples=samples)
    atlas = mat.atlas(material_name or name, res["albedo"], res["normal"], res["orm"], res.get("emissive"),
                      res["emissive_strength"], alpha=alpha)
    keep = set(keep_materials)
    for o in objects:
        me = o.data
        old = list(me.materials)
        new = [atlas] + [m for m in dict.fromkeys(old) if m is not None and m.name in keep]
        index = {id(m): (new.index(m) if m in new else 0) for m in old if m is not None}
        remap = [index.get(id(m), 0) if m is not None else 0 for m in old]
        mi = [0] * len(me.polygons)
        me.polygons.foreach_get("material_index", mi)
        me.materials.clear()
        for m in new:
            me.materials.append(m)
        me.polygons.foreach_set("material_index", [remap[i] if i < len(remap) else 0 for i in mi])
        me.update()
        mesh.finalize_uvs(o, "Atlas")
    res["material"] = atlas
    return res
