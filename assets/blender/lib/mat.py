# Materials: Principled BSDF only (the glTF exporter turns it into
# MeshStandardMaterial). Colours are linear RGB tuples or "#rrggbb" sRGB hex.
#
#   pbr("Rock", "Rock051", tiling=2)                   CC0 set by id (assets/textures/<id>/)
#   pbr("Brick", "Bricks097", mapping="BOX", box_scale=1.5)   object-space box mapping, 1.5 m per tile
#   pbr("Floor", "concrete_floor", wet=0.6)            darker, glossier
#   flat("Void", "#050507", rough=0.06, metal=1)
#   glass("Glass", smudges="Fingerprints002")
#   emissive_screen("Screen", (0.6, 0.85, 1.0), 6.0)
#   assign(obj, material, faces=lambda f: f.normal.z > 0.9)
#
# Texture sets: ambientCG (<id>_2K-JPG_Color.jpg, _NormalGL, _Roughness,
# _Metalness, _AmbientOcclusion, _Displacement, _Opacity, _Emission) and
# Poly Haven (<id>_diff_2k.jpg, _nor_gl, _rough, _metal, _ao, _disp, _arm,
# _alpha). find_maps() reads either; a dict {"color": path, ...} works too.
#
# Occlusion goes into a "glTF Material Output" group node (the exporter writes
# it as occlusionTexture; bake.py reads it for the ORM atlas). Alpha "CLIP" is
# wired as Alpha -> Math(Round) so the exporter writes alphaMode MASK; "BLEND"
# gives alphaMode BLEND (glass only, per the contract).

import os
import re

import bpy

from . import texture_dir

# ------------------------------------------------------------------ colours

def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def rgb(color):
    """(r, g, b) linear from a linear tuple/list, or from "#rrggbb" sRGB hex."""
    if isinstance(color, str):
        h = color.lstrip("#")
        return tuple(srgb_to_linear(int(h[i:i + 2], 16) / 255) for i in (0, 2, 4))
    return tuple(float(x) for x in color[:3])


def rgba(color, alpha=1.0):
    return (*rgb(color), alpha)


# ------------------------------------------------------------------ texture sets

# Suffix (after the set id and resolution tokens are stripped) -> map kind.
_SUFFIX = {
    "color": "color", "basecolor": "color", "albedo": "color", "diff": "color", "diffuse": "color", "col": "color",
    "normalgl": "normal", "nor_gl": "normal", "normal": "normal",
    "normaldx": "normal_dx", "nor_dx": "normal_dx",
    "roughness": "roughness", "rough": "roughness",
    "metalness": "metalness", "metallic": "metalness", "metal": "metalness",
    "ambientocclusion": "ao", "ao": "ao",
    "displacement": "displacement", "disp": "displacement", "height": "displacement",
    "opacity": "opacity", "alpha": "opacity", "mask": "opacity",
    "emission": "emission", "emissive": "emission",
    "arm": "arm",
}
_IMAGE_EXT = (".jpg", ".jpeg", ".png", ".exr", ".tif", ".tiff", ".webp")
_RES = re.compile(r"^\d+k(-(jpg|png|exr))?$")
# Colour data lives in sRGB images, everything else is raw data.
_SRGB = {"color", "emission"}


def find_maps(textures):
    """{kind: path} for a texture set id, folder, or a ready dict.

    kinds: color normal normal_dx roughness metalness ao displacement opacity
    emission arm. Normal prefers the OpenGL map (glTF convention)."""
    if isinstance(textures, dict):
        return {k: os.path.abspath(v) for k, v in textures.items() if v}
    folder = texture_dir(textures)
    set_id = os.path.basename(folder.rstrip("/")).lower()
    maps = {}
    for fname in sorted(os.listdir(folder)):
        stem, ext = os.path.splitext(fname)
        if ext.lower() not in _IMAGE_EXT or fname.startswith("."):
            continue
        s = stem.lower()
        if s.startswith(set_id):
            s = s[len(set_id):]
        tokens = [t for t in s.strip("_-").split("_") if t and not _RES.match(t)]
        kind = None
        # Try the whole remainder, then shorter tails ("..._nor_gl" -> "nor_gl").
        for i in range(len(tokens)):
            kind = _SUFFIX.get("_".join(tokens[i:]))
            if kind:
                break
        if kind and (kind not in maps or ext.lower() in (".jpg", ".png")):
            maps[kind] = os.path.join(folder, fname)
    if "color" not in maps and "arm" not in maps:
        raise FileNotFoundError(f"no colour map in {folder} (files: {os.listdir(folder)})")
    return maps


def image(path, data=False):
    """Load (or reuse) an image; data=True marks it Non-Color."""
    img = bpy.data.images.load(path, check_existing=True)
    img.colorspace_settings.name = "Non-Color" if data else "sRGB"
    return img


# ------------------------------------------------------------------ node helpers

def new_material(name, replace=True):
    """A fresh node material named exactly `name` (renames any old one away)."""
    old = bpy.data.materials.get(name)
    if old is not None and replace:
        old.name = name + ".old"
    m = bpy.data.materials.new(name)
    if hasattr(m, "use_nodes") and not m.use_nodes:  # always on in 5.x
        m.use_nodes = True
    # Single-sided by default (glTF doubleSided=false: half the fragments on
    # mobile). set_alpha("BLEND") and double_sided(m) turn it off.
    m.use_backface_culling = True
    if old is not None and replace:
        old.user_remap(m)
        if old.users == 0:
            bpy.data.materials.remove(old)
    return m


def double_sided(m, on=True):
    """glTF doubleSided (for thin cards, hair, foliage, glass)."""
    m.use_backface_culling = not on
    return m


def principled(m):
    for n in m.node_tree.nodes:
        if n.type == "BSDF_PRINCIPLED":
            return n
    raise ValueError(f"material {m.name} has no Principled BSDF")


def gltf_output(m):
    """The "glTF Material Output" group node of `m` (created on demand)."""
    for n in m.node_tree.nodes:
        if n.type == "GROUP" and n.node_tree and n.node_tree.name in ("glTF Material Output", "glTF Settings"):
            return n
    group = bpy.data.node_groups.get("glTF Material Output")
    if group is None:
        group = bpy.data.node_groups.new("glTF Material Output", "ShaderNodeTree")
        group.interface.new_socket("Occlusion", socket_type="NodeSocketFloat")
        group.interface.new_socket("Thickness", socket_type="NodeSocketFloat").default_value = 0.0
        group.nodes.new("NodeGroupOutput")
        group.nodes.new("NodeGroupInput").location = (-200, 0)
    node = m.node_tree.nodes.new("ShaderNodeGroup")
    node.node_tree = group
    node.label = node.name = "glTF Material Output"
    node.location = (300, -400)
    return node


def box_vector(nt, scale=1.0, rotation=0.0, offset=(0.0, 0.0, 0.0)):
    """Object-space coordinates scaled to `scale` metres per tile, for Image
    nodes with projection BOX (triplanar-style). Returns the vector socket."""
    tc = nt.nodes.new("ShaderNodeTexCoord")
    tc.location = (-1300, 0)
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.location = (-1100, 0)
    s = 1.0 / scale if isinstance(scale, (int, float)) else tuple(1.0 / v for v in scale)
    mp.inputs["Scale"].default_value = (s, s, s) if isinstance(s, float) else s
    mp.inputs["Rotation"].default_value = (0.0, 0.0, rotation)
    mp.inputs["Location"].default_value = offset
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    return mp.outputs["Vector"]


def uv_vector(nt, tiling=1.0, rotation=0.0, offset=(0.0, 0.0), uv_map=None):
    """UV coordinates (named layer or the render-active one) tiled/rotated."""
    if uv_map:
        src = nt.nodes.new("ShaderNodeUVMap")
        src.uv_map = uv_map
        out = src.outputs["UV"]
    else:
        src = nt.nodes.new("ShaderNodeTexCoord")
        out = src.outputs["UV"]
    src.location = (-1300, 0)
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.location = (-1100, 0)
    tu, tv = (tiling, tiling) if isinstance(tiling, (int, float)) else tiling
    mp.inputs["Scale"].default_value = (tu, tv, 1.0)
    mp.inputs["Rotation"].default_value = (0.0, 0.0, rotation)
    mp.inputs["Location"].default_value = (offset[0], offset[1], 0.0)
    nt.links.new(out, mp.inputs["Vector"])
    return mp.outputs["Vector"]


def set_box_mapping(material, scale=1.0, blend=0.25):
    """Switch every Image node of an existing material to object-space box
    projection (`scale` metres per tile). Handy before a procedural bake."""
    nt = material.node_tree
    vec = box_vector(nt, scale)
    for n in nt.nodes:
        if n.type == "TEX_IMAGE":
            n.projection = "BOX"
            n.projection_blend = blend
            nt.links.new(vec, n.inputs["Vector"])
    return material


def _tex(nt, path, data, vec, box, blend, loc):
    n = nt.nodes.new("ShaderNodeTexImage")
    n.image = image(path, data)
    n.location = loc
    n.interpolation = "Linear"
    if box:
        n.projection = "BOX"
        n.projection_blend = blend
    nt.links.new(vec, n.inputs["Vector"])
    return n


def _math(nt, op, a, b=None, loc=(0, 0), clamp=False):
    n = nt.nodes.new("ShaderNodeMath")
    n.operation = op
    n.location = loc
    n.use_clamp = clamp
    for i, v in enumerate((a, b)):
        if v is None:
            continue
        if isinstance(v, bpy.types.NodeSocket):
            nt.links.new(v, n.inputs[i])
        else:
            n.inputs[i].default_value = v
    return n.outputs[0]


def _mix(nt, blend, a, b, fac=1.0, loc=(0, 0)):
    n = nt.nodes.new("ShaderNodeMix")
    n.data_type = "RGBA"
    n.blend_type = blend
    n.location = loc
    n.inputs["Factor"].default_value = fac
    for sock, v in ((n.inputs[6], a), (n.inputs[7], b)):
        if isinstance(v, bpy.types.NodeSocket):
            nt.links.new(v, sock)
        else:
            sock.default_value = rgba(v) if len(v) == 3 or isinstance(v, str) else v
    return n.outputs[2]


def set_alpha(m, mode, alpha_socket=None, value=1.0, threshold=0.5):
    """mode "CLIP" (glTF MASK, via Math Round/Greater Than) or "BLEND"."""
    nt, p = m.node_tree, principled(m)
    if mode == "CLIP":
        src = alpha_socket if alpha_socket is not None else value
        if abs(threshold - 0.5) < 1e-6:
            out = _math(nt, "ROUND", src, loc=(-250, -350))
        else:
            out = _math(nt, "GREATER_THAN", src, threshold, loc=(-250, -350))
        nt.links.new(out, p.inputs["Alpha"])
        if hasattr(m, "blend_method"):
            m.blend_method = "CLIP"
        m.surface_render_method = "DITHERED"
    elif mode == "BLEND":
        if alpha_socket is not None:
            nt.links.new(alpha_socket, p.inputs["Alpha"])
        else:
            p.inputs["Alpha"].default_value = value
        if hasattr(m, "blend_method"):
            m.blend_method = "BLEND"
        m.surface_render_method = "BLENDED"
        m.use_backface_culling = False
    return m


# ------------------------------------------------------------------ materials

def pbr(name, textures, tiling=1.0, mapping="UV", box_scale=1.0, box_blend=0.25, uv_map=None,
        rotation=0.0, offset=(0.0, 0.0), tint=None, tint_mode="MULTIPLY", saturation=1.0, value=1.0,
        roughness=None, roughness_scale=1.0, roughness_offset=0.0, metallic=None,
        normal_strength=1.0, bump=0.0, bump_distance=0.01, ao_strength=1.0, wet=0.0,
        alpha=None, alpha_threshold=0.5, emission=None, emission_strength=0.0, **inputs):
    """Principled material from a CC0 texture set.

    textures      set id under assets/textures/, a folder, or {kind: path}
    tiling        UV repeats (float or (u, v)); mapping "UV" | "BOX"
    box_scale     BOX: metres per tile, object space (apply scale first)
    tint          colour multiplied (tint_mode "MULTIPLY") or overlaid on the albedo
    saturation, value   HSV tweak of the albedo (1 = unchanged)
    roughness     constant override; else map * roughness_scale + roughness_offset
    metallic      constant override; else the metalness map, else 0
    normal_strength   tangent normal map strength (BOX mapping approximates)
    bump          >0 adds the displacement map as a Bump on top of the normal
    ao_strength   occlusion map strength into the glTF output (0 = none)
    wet           0..1 darker, more saturated, glossier (sewer, rain)
    alpha         None | "CLIP" | "BLEND" using the opacity map
    **inputs      any Principled input by name ({"Sheen Weight": 0.3} as
                  sheen_weight=0.3 or with the exact name via inputs dict)"""
    maps = find_maps(textures)
    m = new_material(name)
    nt = m.node_tree
    p = principled(m)
    p.location = (300, 0)
    box = mapping.upper() == "BOX"
    vec = box_vector(nt, box_scale, rotation) if box else uv_vector(nt, tiling, rotation, offset, uv_map)
    tex = lambda kind, data, y: _tex(nt, maps[kind], data, vec, box, box_blend, (-800, y))  # noqa: E731

    arm = tex("arm", True, -300) if "arm" in maps else None
    arm_sep = None
    if arm is not None:
        arm_sep = nt.nodes.new("ShaderNodeSeparateColor")
        arm_sep.location = (-500, -300)
        nt.links.new(arm.outputs["Color"], arm_sep.inputs["Color"])

    # Albedo -> tint -> HSV -> wet darkening
    col = tex("color", False, 300).outputs["Color"] if "color" in maps else rgba((0.5, 0.5, 0.5))
    if tint is not None:
        if tint_mode == "MULTIPLY":
            col = _mix(nt, "MULTIPLY", col, rgba(tint), 1.0, (-500, 300))
        else:
            col = _mix(nt, tint_mode, col, rgba(tint), 1.0, (-500, 300))
    if saturation != 1.0 or value != 1.0 or wet > 0:
        hsv = nt.nodes.new("ShaderNodeHueSaturation")
        hsv.location = (-300, 300)
        hsv.inputs["Saturation"].default_value = saturation * (1.0 + 0.25 * wet)
        hsv.inputs["Value"].default_value = value * (1.0 - 0.4 * wet)
        if isinstance(col, bpy.types.NodeSocket):
            nt.links.new(col, hsv.inputs["Color"])
        else:
            hsv.inputs["Color"].default_value = col
        col = hsv.outputs["Color"]
    if isinstance(col, bpy.types.NodeSocket):
        nt.links.new(col, p.inputs["Base Color"])
    else:
        p.inputs["Base Color"].default_value = col

    # Roughness
    if roughness is not None:
        p.inputs["Roughness"].default_value = roughness * (1.0 - 0.75 * wet)
    else:
        if "roughness" in maps:
            r = tex("roughness", True, 0).outputs["Color"]
        elif arm_sep is not None:
            r = arm_sep.outputs["Green"]
        else:
            r = 0.6
        if roughness_scale != 1.0 or roughness_offset != 0.0 or wet > 0 or not isinstance(r, bpy.types.NodeSocket):
            r = _math(nt, "MULTIPLY_ADD", r, roughness_scale * (1.0 - 0.75 * wet), loc=(-300, 0), clamp=True)
            r.node.inputs[2].default_value = roughness_offset * (1.0 - 0.75 * wet)
        nt.links.new(r, p.inputs["Roughness"])

    # Metalness
    if metallic is not None:
        p.inputs["Metallic"].default_value = metallic
    elif "metalness" in maps:
        nt.links.new(tex("metalness", True, -150).outputs["Color"], p.inputs["Metallic"])
    elif arm_sep is not None:  # ARM: R occlusion, G roughness, B metal
        nt.links.new(arm_sep.outputs["Blue"], p.inputs["Metallic"])
    else:
        p.inputs["Metallic"].default_value = 0.0

    # Normal (+ optional bump from the height map)
    normal = None
    if normal_strength > 0 and ("normal" in maps or "normal_dx" in maps):
        kind = "normal" if "normal" in maps else "normal_dx"
        n_img = tex(kind, True, -600).outputs["Color"]
        if kind == "normal_dx":  # DirectX -> OpenGL: flip green
            sep = nt.nodes.new("ShaderNodeSeparateColor")
            comb = nt.nodes.new("ShaderNodeCombineColor")
            sep.location, comb.location = (-550, -600), (-400, -600)
            nt.links.new(n_img, sep.inputs["Color"])
            nt.links.new(sep.outputs["Red"], comb.inputs["Red"])
            nt.links.new(_math(nt, "SUBTRACT", 1.0, sep.outputs["Green"], loc=(-470, -650)), comb.inputs["Green"])
            nt.links.new(sep.outputs["Blue"], comb.inputs["Blue"])
            n_img = comb.outputs["Color"]
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.location = (-250, -600)
        nm.inputs["Strength"].default_value = normal_strength
        if uv_map:
            nm.uv_map = uv_map
        nt.links.new(n_img, nm.inputs["Color"])
        normal = nm.outputs["Normal"]
    if bump > 0 and "displacement" in maps:
        b = nt.nodes.new("ShaderNodeBump")
        b.location = (-100, -700)
        b.inputs["Strength"].default_value = bump
        b.inputs["Distance"].default_value = bump_distance
        nt.links.new(tex("displacement", True, -900).outputs["Color"], b.inputs["Height"])
        if normal is not None:
            nt.links.new(normal, b.inputs["Normal"])
        normal = b.outputs["Normal"]
    if normal is not None:
        nt.links.new(normal, p.inputs["Normal"])

    # Occlusion (for the glTF exporter and the atlas bake)
    if ao_strength > 0 and ("ao" in maps or arm_sep is not None):
        ao = tex("ao", True, -450).outputs["Color"] if "ao" in maps else arm_sep.outputs["Red"]
        if ao_strength != 1.0:  # lerp(1, ao, strength)
            ao = _math(nt, "MULTIPLY_ADD", ao, ao_strength, loc=(-300, -450))
            ao.node.inputs[2].default_value = 1.0 - ao_strength
        nt.links.new(ao, gltf_output(m).inputs["Occlusion"])

    # Emission
    if "emission" in maps:
        nt.links.new(tex("emission", False, 600).outputs["Color"], p.inputs["Emission Color"])
        p.inputs["Emission Strength"].default_value = emission_strength or 1.0
    elif emission is not None:
        p.inputs["Emission Color"].default_value = rgba(emission)
        p.inputs["Emission Strength"].default_value = emission_strength

    if alpha and "opacity" in maps:
        set_alpha(m, alpha, tex("opacity", True, 800).outputs["Color"], threshold=alpha_threshold)
    elif alpha:
        set_alpha(m, alpha, value=1.0, threshold=alpha_threshold)

    _apply_inputs(p, inputs)
    m.diffuse_color = (*(rgb(tint) if tint is not None else (0.5, 0.5, 0.5)), 1.0)
    m["lib_textures"] = textures if isinstance(textures, str) else "custom"
    return m


def _apply_inputs(p, inputs):
    for key, value in inputs.items():
        name = key if key in p.inputs else key.replace("_", " ").title()
        if name not in p.inputs:
            raise KeyError(f"Principled BSDF has no input '{key}' (have: {[i.name for i in p.inputs]})")
        sock = p.inputs[name]
        if sock.type == "RGBA":
            sock.default_value = rgba(value)
        else:
            sock.default_value = value


def flat(name, color, rough=0.5, metal=0.0, emission=None, strength=0.0, alpha=None, alpha_value=1.0, **inputs):
    """Untextured Principled. `emission` colour + `strength` for glow
    (strength > 1 exports as KHR_materials_emissive_strength)."""
    m = new_material(name)
    p = principled(m)
    p.inputs["Base Color"].default_value = rgba(color)
    p.inputs["Roughness"].default_value = rough
    p.inputs["Metallic"].default_value = metal
    if emission is not None:
        p.inputs["Emission Color"].default_value = rgba(emission)
        p.inputs["Emission Strength"].default_value = strength
    if alpha:
        set_alpha(m, alpha, value=alpha_value)
    _apply_inputs(p, inputs)
    m.diffuse_color = rgba(color)
    return m


def glass(name="Glass", color=(0.9, 0.95, 1.0), rough=0.04, alpha=0.18, ior=1.45, smudges=None,
          smudge_strength=0.25, tiling=1.0, transmission=0.0):
    """Alpha-blended glass (cheap on mobile; transmission=0 by default so
    three.js stays on MeshStandardMaterial). `smudges`: a texture set id
    (e.g. "Fingerprints002") whose roughness/colour raises the roughness."""
    m = new_material(name)
    nt, p = m.node_tree, principled(m)
    p.inputs["Base Color"].default_value = rgba(color)
    p.inputs["IOR"].default_value = ior
    p.inputs["Metallic"].default_value = 0.0
    if transmission:
        p.inputs["Transmission Weight"].default_value = transmission
    rough_out = rough
    if smudges:
        maps = find_maps(smudges)
        kind = next((k for k in ("roughness", "opacity", "color") if k in maps), None)
        mask = _tex(nt, maps[kind], True, uv_vector(nt, tiling), False, 0, (-800, 0)).outputs["Color"]
        rough_out = _math(nt, "MULTIPLY_ADD", mask, smudge_strength, loc=(-300, 0), clamp=True)
        rough_out.node.inputs[2].default_value = rough
    if isinstance(rough_out, bpy.types.NodeSocket):
        nt.links.new(rough_out, p.inputs["Roughness"])
    else:
        p.inputs["Roughness"].default_value = rough_out
    set_alpha(m, "BLEND", value=alpha)
    m.diffuse_color = (*rgb(color), alpha)
    return m


def emissive_screen(name="Screen", color=(0.6, 0.85, 1.0), strength=6.0, image_path=None, base=(0.01, 0.01, 0.012),
                    rough=0.15, uv_map=None):
    """A phone/billboard screen: dark glass base plus emission (a colour or an
    image). The renderer finds screens by material name (Screen*, ReelScreen,
    ScreenFeed, ...) and may swap the emissive map for a canvas, so give the
    faces clean 0..1 UVs (mesh.uv_fit_faces)."""
    m = new_material(name)
    nt, p = m.node_tree, principled(m)
    p.inputs["Base Color"].default_value = rgba(base)
    p.inputs["Roughness"].default_value = rough
    p.inputs["Metallic"].default_value = 0.0
    p.inputs["Emission Strength"].default_value = strength
    if image_path:
        n = _tex(nt, image_path, False, uv_vector(nt, 1.0, uv_map=uv_map), False, 0, (-500, 200))
        nt.links.new(n.outputs["Color"], p.inputs["Emission Color"])
    else:
        p.inputs["Emission Color"].default_value = rgba(color)
    m.diffuse_color = rgba(color)
    return m


def atlas(name, albedo, normal=None, orm=None, emissive=None, emissive_strength=1.0, alpha=None, uv_map=None):
    """The one-material-per-kit Principled: baked albedo (+alpha), normal,
    ORM (R occlusion, G roughness, B metal) and optional emissive images."""
    m = new_material(name)
    nt, p = m.node_tree, principled(m)
    vec = uv_vector(nt, 1.0, uv_map=uv_map)

    def img_node(img, y):
        n = nt.nodes.new("ShaderNodeTexImage")
        n.image = img
        n.location = (-600, y)
        nt.links.new(vec, n.inputs["Vector"])
        return n

    a = img_node(albedo, 300)
    nt.links.new(a.outputs["Color"], p.inputs["Base Color"])
    if alpha:
        set_alpha(m, alpha, a.outputs["Alpha"])
    if orm is not None:
        o = img_node(orm, 0)
        sep = nt.nodes.new("ShaderNodeSeparateColor")
        sep.location = (-300, 0)
        nt.links.new(o.outputs["Color"], sep.inputs["Color"])
        nt.links.new(sep.outputs["Green"], p.inputs["Roughness"])
        nt.links.new(sep.outputs["Blue"], p.inputs["Metallic"])
        nt.links.new(sep.outputs["Red"], gltf_output(m).inputs["Occlusion"])
    if normal is not None:
        n = img_node(normal, -300)
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.location = (-300, -300)
        if uv_map:
            nm.uv_map = uv_map
        nt.links.new(n.outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], p.inputs["Normal"])
    if emissive is not None:
        e = img_node(emissive, 600)
        nt.links.new(e.outputs["Color"], p.inputs["Emission Color"])
        p.inputs["Emission Strength"].default_value = emissive_strength
    return m


def assign(obj, material, faces=None):
    """Add `material` to obj's slots (once) and put faces on it: all faces when
    faces is None, else those where faces(polygon) is true."""
    mats = obj.data.materials
    idx = next((i for i, s in enumerate(mats) if s == material), None)
    if idx is None:
        mats.append(material)
        idx = len(mats) - 1
    for poly in obj.data.polygons:
        if faces is None or faces(poly):
            poly.material_index = idx
    return idx
