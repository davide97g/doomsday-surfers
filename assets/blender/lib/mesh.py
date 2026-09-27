# Mesh helpers. Everything works headless (blender -b): bmesh where possible,
# operators under bpy.context.temp_override where Blender needs them.
#
#   o = box("crate", (1, 1, 0.6), location=(0, 0, 0.3), bevel=0.02)
#   bevel(o, 0.01); weighted_normals(o)          modifiers (apply=True to bake them in)
#   subdivide_along(o, "Y", 0.5)                 edge loops for the vertex-shader bend
#   set_origin(o, y="min", z="min")              contract origins ("front face", "on the ground")
#   uv_box(o, 1.0) / uv_smart(o) / uv_fit_faces(o, material="ReelScreen")
#   pack_uvs_to_atlas([a, b, c], size=2048)      one shared "Atlas" UV layer (bake.bake_kit_atlas uses it)
#   tri_count([a, b])                            evaluated (modifiers included)
#
# Order that keeps shading right: model -> apply_transform -> subdivide_along ->
# bevel/weighted_normals -> apply_modifiers. Bisecting after custom normals
# exist throws them away, so cut first.

import math

import bmesh
import bpy
from mathutils import Matrix, Vector

from . import link

AXES = {"X": 0, "Y": 1, "Z": 2}


# ------------------------------------------------------------------ objects

def new_object(name, data, collection=None):
    """Object from a bmesh (freed) or a Mesh."""
    if isinstance(data, bmesh.types.BMesh):
        me = bpy.data.meshes.new(name)
        data.to_mesh(me)
        data.free()
        data = me
    return link(bpy.data.objects.new(name, data), collection)


def box(name, size=(1.0, 1.0, 1.0), location=(0.0, 0.0, 0.0), bevel=0.0, segments=3, rotation=(0.0, 0.0, 0.0),
        collection=None):
    """Axis-aligned box (size = full extents) with a default "UVMap" (per-face
    0..1), optionally with real bevelled geometry (not a modifier).
    Location is the box centre."""
    bm = bmesh.new()
    bm.loops.layers.uv.new("UVMap")
    bmesh.ops.create_cube(bm, size=1.0, calc_uvs=True)
    bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts)
    if bevel > 0:
        bmesh.ops.bevel(bm, geom=bm.edges[:] + bm.verts[:], offset=bevel, segments=segments, profile=0.5,
                        affect="EDGES", clamp_overlap=True)
    o = new_object(name, bm, collection)
    o.location = location
    o.rotation_euler = rotation
    return o


def cylinder(name, radius=0.5, depth=1.0, verts=32, location=(0.0, 0.0, 0.0), axis="Z", caps=True, radius2=None,
             collection=None):
    """Cylinder (or cone with radius2) centred on `location` along `axis`."""
    bm = bmesh.new()
    bm.loops.layers.uv.new("UVMap")
    bmesh.ops.create_cone(bm, cap_ends=caps, cap_tris=False, segments=verts, radius1=radius,
                          radius2=radius if radius2 is None else radius2, depth=depth, calc_uvs=True)
    if axis == "X":
        bmesh.ops.rotate(bm, verts=bm.verts, matrix=Matrix.Rotation(math.pi / 2, 3, "Y"))
    elif axis == "Y":
        bmesh.ops.rotate(bm, verts=bm.verts, matrix=Matrix.Rotation(math.pi / 2, 3, "X"))
    o = new_object(name, bm, collection)
    o.location = location
    return o


def duplicate(obj, name=None, linked=False):
    """Copy of an object (own mesh unless linked), in the same collections."""
    new = obj.copy()
    if not linked and obj.data is not None:
        new.data = obj.data.copy()
    new.name = name or obj.name + ".copy"
    for col in obj.users_collection:
        col.objects.link(new)
    return new


# ------------------------------------------------------------------ modifiers

def modifier(obj, kind, name=None, **props):
    """obj.modifiers.new + setattr for each prop. Returns the modifier."""
    mod = obj.modifiers.new(name or kind.lower(), kind)
    for k, v in props.items():
        setattr(mod, k, v)
    return mod


def bevel(obj, width=0.01, segments=3, angle=30.0, profile=0.5, harden=True, limit="ANGLE", apply=False):
    """Bevel modifier (angle-limited by default) with harden normals, so hard
    surfaces catch highlights on their edges. Follow with weighted_normals."""
    mod = modifier(obj, "BEVEL", width=width, segments=segments, limit_method=limit,
                   angle_limit=math.radians(angle), profile=profile, harden_normals=harden,
                   use_clamp_overlap=True, miter_outer="MITER_ARC")
    if apply:
        apply_modifiers(obj, only=[mod.name])
    return mod


def weighted_normals(obj, weight=50, keep_sharp=True, mode="FACE_AREA", apply=False):
    """Smooth shading + Weighted Normal modifier (flat faces stay flat, bevels
    take the curvature). Blender 4.1+ needs no auto smooth for this."""
    smooth(obj, angle=None)
    mod = modifier(obj, "WEIGHTED_NORMAL", weight=weight, keep_sharp=keep_sharp, mode=mode)
    if apply:
        apply_modifiers(obj, only=[mod.name])
    return mod


def smooth(obj, angle=30.0):
    """Shade smooth; with an angle, edges sharper than it stay sharp."""
    me = obj.data
    me.shade_smooth()
    if angle is not None:
        me.set_sharp_from_angle(angle=math.radians(angle))
    return obj


def apply_modifiers(obj, only=None):
    """Apply the object's modifiers (all, or the names in `only`) in stack order."""
    names = [m.name for m in obj.modifiers if only is None or m.name in only]
    for name in names:
        with bpy.context.temp_override(object=obj, active_object=obj, selected_objects=[obj],
                                       selected_editable_objects=[obj]):
            result = bpy.ops.object.modifier_apply(modifier=name)
        if "FINISHED" not in result:
            raise RuntimeError(f"could not apply modifier {name} on {obj.name}")
    return obj


def apply_transform(obj, location=True, rotation=True, scale=True):
    """Bake the object transform into its mesh (mesh made single-user first)."""
    if obj.data.users > 1:
        obj.data = obj.data.copy()
    loc, rot, sca = obj.matrix_basis.decompose()
    m = Matrix.Identity(4)
    keep = Matrix.Identity(4)
    parts = [(location, Matrix.Translation(loc)), (rotation, rot.to_matrix().to_4x4()),
             (scale, Matrix.Diagonal((*sca, 1.0)))]
    for use, part in parts:
        if use:
            m = m @ part
        else:
            keep = keep @ part
    obj.data.transform(m)
    obj.matrix_basis = keep
    obj.data.update()
    return obj


def decimate(obj, ratio=0.5, apply=True):
    """Collapse decimation (for background pieces over budget)."""
    mod = modifier(obj, "DECIMATE", ratio=ratio, use_collapse_triangulate=True)
    if apply:
        apply_modifiers(obj, only=[mod.name])
    return obj


def clean(obj, merge=1e-5, recalc_normals=True):
    """Merge by distance and make face normals point outward."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=merge)
    if recalc_normals:
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    return obj


# ------------------------------------------------------------------ bend loops

def subdivide_along(obj, axis="Y", max_len=1.0, positions=None):
    """Cut edge loops across the whole mesh along `axis` (object space, scale
    taken into account) so no segment is longer than `max_len` metres. The
    contract: <= 1 m for anything longer than 2 m, <= 0.5 m for deck/tunnels.
    `positions`: explicit world-axis cut coordinates instead. UVs are
    interpolated. Returns the number of cuts."""
    i = AXES[axis.upper()]
    bpy.context.view_layer.update()
    s = obj.matrix_world.to_scale()[i] or 1.0
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    coords = [v.co[i] for v in bm.verts]
    if not coords:
        bm.free()
        return 0
    lo, hi = min(coords), max(coords)
    if positions is None:
        n = max(1, math.ceil((hi - lo) * abs(s) / max_len - 1e-6))
        cuts = [lo + (hi - lo) * k / n for k in range(1, n)]
    else:
        cuts = [c / s for c in positions]
    normal = Vector((0.0, 0.0, 0.0))
    normal[i] = 1.0
    for c in cuts:
        co = Vector((0.0, 0.0, 0.0))
        co[i] = c
        bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], dist=1e-5, plane_co=co,
                               plane_no=normal)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    return len(cuts)


def max_segment(obj, axis="Y"):
    """Largest gap between consecutive vertex coordinates along an axis (world
    units): a quick check that the bend has enough loops."""
    i = AXES[axis.upper()]
    bpy.context.view_layer.update()
    s = abs(obj.matrix_world.to_scale()[i])
    cs = sorted({round(v.co[i] * s, 5) for v in obj.data.vertices})
    return max((b - a for a, b in zip(cs, cs[1:])), default=0.0)


# ------------------------------------------------------------------ join, origin, bounds

def join(objects, name=None):
    """Join meshes into the first one (materials and UV layers merge by name)."""
    objects = [o for o in objects if o is not None]
    target = objects[0]
    if len(objects) > 1:
        with bpy.context.temp_override(object=target, active_object=target, selected_objects=objects,
                                       selected_editable_objects=objects):
            bpy.ops.object.join()
    if name:
        target.name = name
        target.data.name = name
    return target


def bounds(objs, world=True):
    """(min, max) Vectors over the mesh vertices of one or more objects."""
    objs = objs if isinstance(objs, (list, tuple)) else [objs]
    bpy.context.view_layer.update()  # matrix_world lags behind location/rotation edits
    lo = Vector((math.inf,) * 3)
    hi = Vector((-math.inf,) * 3)
    for o in objs:
        if o.type != "MESH":
            continue
        mw = o.matrix_world if world else Matrix.Identity(4)
        for v in o.data.vertices:
            p = mw @ v.co
            lo = Vector(map(min, lo, p))
            hi = Vector(map(max, hi, p))
    return lo, hi


def set_origin(obj, x="center", y="center", z="center", point=None):
    """Move the origin without moving the mesh. Each axis: "min", "max",
    "center" of the world bounding box, or a number (world coordinate); or pass
    `point` (world). E.g. habits: z="min"; train_front: y="min", z="min"."""
    if point is None:
        lo, hi = bounds(obj)
        pick = lambda spec, k: {"min": lo[k], "max": hi[k], "center": (lo[k] + hi[k]) / 2}.get(spec, spec)  # noqa: E731
        point = Vector((pick(x, 0), pick(y, 1), pick(z, 2)))
    bpy.context.view_layer.update()
    local = obj.matrix_world.inverted() @ Vector(point)
    obj.data.transform(Matrix.Translation(-local))
    obj.matrix_world = obj.matrix_world @ Matrix.Translation(local)
    obj.data.update()
    return obj


def tri_count(objs, evaluated=True):
    """Triangles after modifiers (evaluated=True) for one object or a list."""
    objs = objs if isinstance(objs, (list, tuple)) else [objs]
    dg = bpy.context.evaluated_depsgraph_get()
    total = 0
    for o in objs:
        if o.type != "MESH":
            continue
        if evaluated:
            ev = o.evaluated_get(dg)
            me = ev.to_mesh()
            me.calc_loop_triangles()
            total += len(me.loop_triangles)
            ev.to_mesh_clear()
        else:
            total += sum(len(p.vertices) - 2 for p in o.data.polygons)
    return total


# ------------------------------------------------------------------ UVs

def uv_layer(obj, name=None, active=True):
    """Get or create a UV layer (default: the active one, else "UVMap")."""
    layers = obj.data.uv_layers
    if name is None:
        layer = layers.active or layers.new(name="UVMap")
    else:
        layer = layers.get(name) or layers.new(name=name)
    if active:
        layers.active = layer
    return layer


def _face_filter(obj, faces, material):
    names = [m.name if m else None for m in obj.data.materials]
    if isinstance(material, str):
        material = (material,)

    def ok(poly):
        if material is not None and (poly.material_index >= len(names) or names[poly.material_index] not in material):
            return False
        return faces is None or faces(poly)
    return ok


def uv_box(obj, size=1.0, layer=None, faces=None, material=None):
    """Metric box projection: each face takes the plane of its dominant normal
    axis, `size` metres per UV unit (object space, scale included). Good for
    tiling CC0 textures at real-world scale."""
    lay = uv_layer(obj, layer)
    ok = _face_filter(obj, faces, material)
    bpy.context.view_layer.update()
    sc = obj.matrix_world.to_scale()
    me = obj.data
    for poly in me.polygons:
        if not ok(poly):
            continue
        n = poly.normal
        k = max(range(3), key=lambda a: abs(n[a]))
        sign = 1.0 if n[k] >= 0 else -1.0
        # u runs to the right as seen from outside the face, v up (+Z, or +Y on floors)
        for li in poly.loop_indices:
            co = me.vertices[me.loops[li].vertex_index].co
            x, y, z = co.x * sc.x / size, co.y * sc.y / size, co.z * sc.z / size
            lay.data[li].uv = ((sign * y, z), (-sign * x, z), (sign * x, y))[k]
    me.update()
    return lay


def uv_fit_faces(obj, material=None, faces=None, layer=None, rotate=0, flip_u=False, flip_v=False, margin=0.0):
    """Project the chosen faces onto their average plane and stretch them to
    exactly 0..1 (u to the viewer's right, v up). For canvas-driven faces the
    renderer fills at runtime (ReelScreen, AdFace, NotifFace, ScreenFeed...).
    rotate: quarter turns."""
    lay = uv_layer(obj, layer)
    ok = _face_filter(obj, faces, material)
    me = obj.data
    polys = [p for p in me.polygons if ok(p)]
    if not polys:
        return lay
    n = sum((p.normal * p.area for p in polys), Vector()).normalized()
    up = Vector((0, 0, 1)) if abs(n.z) < 0.9 else Vector((0, 1, 0))
    right = up.cross(n).normalized()
    up = n.cross(right).normalized()
    pts = {li: me.vertices[me.loops[li].vertex_index].co for p in polys for li in p.loop_indices}
    us = [pts[li].dot(right) for li in pts]
    vs = [pts[li].dot(up) for li in pts]
    u0, u1, v0, v1 = min(us), max(us), min(vs), max(vs)
    for li, co in pts.items():
        u = (co.dot(right) - u0) / ((u1 - u0) or 1)
        v = (co.dot(up) - v0) / ((v1 - v0) or 1)
        for _ in range(rotate % 4):
            u, v = v, 1 - u
        if flip_u:
            u = 1 - u
        if flip_v:
            v = 1 - v
        lay.data[li].uv = (margin + u * (1 - 2 * margin), margin + v * (1 - 2 * margin))
    me.update()
    return lay


class _EditMode:
    """Multi-object edit mode on `objects` with face selection set by `pick`
    (pick(obj, poly) -> bool), UV sync on, the given UV layer active."""

    def __init__(self, objects, layer=None, pick=None):
        self.objects, self.layer, self.pick = objects, layer, pick

    def __enter__(self):
        vl = bpy.context.view_layer
        if bpy.context.object and bpy.context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for o in vl.objects:
            o.select_set(False)
        for o in self.objects:
            o.hide_set(False)
            o.select_set(True)
            if self.layer:
                o.data.uv_layers.active = o.data.uv_layers[self.layer]
            for p in o.data.polygons:
                p.select = True if self.pick is None else bool(self.pick(o, p))
        vl.objects.active = self.objects[0]
        ts = bpy.context.scene.tool_settings
        self._sync = ts.use_uv_select_sync
        ts.use_uv_select_sync = True
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="FACE")
        return self

    def __exit__(self, *exc):
        bpy.ops.object.mode_set(mode="OBJECT")
        bpy.context.scene.tool_settings.use_uv_select_sync = self._sync
        return False


def uv_smart(obj, angle=66.0, margin=0.02, layer=None, faces=None, material=None):
    """Smart UV Project (operator, edit mode) of all or the chosen faces."""
    lay = uv_layer(obj, layer)
    ok = _face_filter(obj, faces, material)
    with _EditMode([obj], lay.name, lambda o, p: ok(p)):
        bpy.ops.uv.smart_project(angle_limit=math.radians(angle), island_margin=margin, area_weight=0.0,
                                 correct_aspect=True, scale_to_bounds=False)
    return lay


def pack_uvs_to_atlas(objects, size=2048, margin_px=8, layer="Atlas", unwrap="smart", source=None, angle=66.0,
                      skip_materials=(), weights=None):
    """Give every object a shared, non-overlapping UV layout in UV layer
    `layer` (created), for baking a whole kit into one atlas.

    unwrap    "smart" (fresh Smart UV Project), "box" (uv_box at 1 m), or
              "keep" (copy the object's current/`source` UV layer)
    weights   {obj_name: w} texel density multipliers (also read from the
              object custom property "atlas_weight"), e.g. 2 for hero pieces
    skip_materials   faces with these materials keep their own UVs (copied from
              the source layer) and take no atlas space: canvas screens, glass
    The render-active UV layer stays the object's original one, so existing
    materials keep sampling what they did; bake.bake_kit_atlas bakes into
    `layer`, then makes it the only UV layer."""
    weights = dict(weights or {})
    skip = set(skip_materials)
    for o in objects:
        me = o.data
        if not me.uv_layers:
            me.uv_layers.new(name="UVMap")
        src = me.uv_layers.get(source) if source else (
            next((l for l in me.uv_layers if l.active_render), None) or me.uv_layers[0])
        src_name = src.name
        if layer in me.uv_layers:
            me.uv_layers.remove(me.uv_layers[layer])
        me.uv_layers[src_name].active_render = True
        dst = me.uv_layers.new(name=layer)
        src = me.uv_layers[src_name]
        for i, d in enumerate(src.data):
            dst.data[i].uv = d.uv
        me.uv_layers[src_name].active_render = True
        o["_atlas_src"] = src_name

    def atlas_face(o, p):
        mats = o.data.materials
        m = mats[p.material_index] if p.material_index < len(mats) else None
        return (m.name if m else None) not in skip

    if unwrap == "box":
        for o in objects:
            uv_box(o, 1.0, layer=layer, faces=lambda p, o=o: atlas_face(o, p))
    with _EditMode(objects, layer, atlas_face):
        if unwrap == "smart":
            bpy.ops.uv.smart_project(angle_limit=math.radians(angle), island_margin=0.0, area_weight=0.0,
                                     correct_aspect=True, scale_to_bounds=False)
        bpy.ops.uv.average_islands_scale()
    # Per-object texel density: scale each object's islands before packing.
    for o in objects:
        w = weights.get(o.name, o.get("atlas_weight", 1.0))
        if w != 1.0:
            k = math.sqrt(w)
            lay = o.data.uv_layers[layer]
            for p in o.data.polygons:
                if atlas_face(o, p):
                    for li in p.loop_indices:
                        lay.data[li].uv = lay.data[li].uv * k
    with _EditMode(objects, layer, atlas_face):
        bpy.ops.uv.pack_islands(udim_source="CLOSEST_UDIM", rotate=True, rotate_method="ANY", scale=True,
                                merge_overlap=False, margin_method="FRACTION", margin=margin_px / size,
                                shape_method="CONCAVE")
    for o in objects:  # skipped faces: back to their own 0..1 UVs
        me = o.data
        src, dst = me.uv_layers[o["_atlas_src"]], me.uv_layers[layer]
        for p in me.polygons:
            if not atlas_face(o, p):
                for li in p.loop_indices:
                    dst.data[li].uv = src.data[li].uv
        me.uv_layers.active = dst
        me.uv_layers[o["_atlas_src"]].active_render = True
    return layer


def finalize_uvs(obj, layer="Atlas", name="UVMap"):
    """Make `layer` the only UV layer (TEXCOORD_0), renamed to `name`."""
    me = obj.data
    for l in [l for l in me.uv_layers if l.name != layer]:
        me.uv_layers.remove(l)
    lay = me.uv_layers[layer]
    lay.name = name
    lay.active = True
    lay.active_render = True
    if "_atlas_src" in obj:
        del obj["_atlas_src"]
    return lay
