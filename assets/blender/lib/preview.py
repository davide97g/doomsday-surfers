# Review renders: neutral studio (AgX, 3-point area lights relative to each
# camera, a soft gradient dome for reflections, a dark floor), camera framing
# the targets' bounds. Everything added is removed afterwards, so scripts can
# preview and still export the same scene.
#
#   render_previews(dir, [obj])                 front/side/back/three_quarter PNGs + sheet.png
#   render_each(dir, kit_objects)               one set per object (others hidden): kits
#   turntable(dir, [obj], frames=8)             turn_00..07.png + sheet
#
# Views (Blender Z-up, the runner faces +Y): front = camera at +Y looking
# back at the model (its face), back = from -Y (the game camera's side),
# side = from +X, three_quarter = front-right and above, top, game (behind
# and above, like the in-game chase camera).

import math
import os

import bpy
import numpy as np
from mathutils import Vector

from . import link, log
from . import mesh as _mesh

VIEWS = {  # direction from the target centre to the camera, before normalising
    "front": (0.0, 1.0, 0.18),
    "back": (0.0, -1.0, 0.18),
    "side": (1.0, 0.0, 0.12),
    "left": (-1.0, 0.0, 0.12),
    "three_quarter": (0.8, 0.9, 0.45),
    "back_three_quarter": (0.8, -0.9, 0.45),
    "top": (0.0, -0.05, 1.0),
    "game": (0.0, -1.0, 0.45),
}


def _studio_world():
    w = bpy.data.worlds.new("_preview_world")
    nt = w.node_tree
    nt.nodes.clear()
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    rng = nt.nodes.new("ShaderNodeMapRange")
    bg = nt.nodes.new("ShaderNodeBackground")
    out = nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(tc.outputs["Generated"], sep.inputs["Vector"])
    nt.links.new(sep.outputs["Z"], rng.inputs["Value"])
    rng.inputs["From Min"].default_value = -0.3
    rng.inputs["From Max"].default_value = 1.0
    rng.inputs["To Min"].default_value = 0.015
    rng.inputs["To Max"].default_value = 0.35
    nt.links.new(rng.outputs["Result"], bg.inputs["Strength"])
    bg.inputs["Color"].default_value = (0.8, 0.82, 0.86, 1.0)
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    return w


def _area(name, energy, size, color):
    data = bpy.data.lights.new(name, "AREA")
    data.energy = energy
    data.size = size
    data.color = color
    return link(bpy.data.objects.new(name, data))


def _aim(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


class _Studio:
    def __init__(self, targets, size, engine, samples, floor, background, lens):
        self.targets, self.size, self.engine, self.samples = targets, size, engine, samples
        self.floor, self.background, self.lens = floor, background, lens
        self.added = []

    def __enter__(self):
        sc = bpy.context.scene
        self.saved = dict(engine=sc.render.engine, world=sc.world, camera=sc.camera, x=sc.render.resolution_x,
                          y=sc.render.resolution_y, pct=sc.render.resolution_percentage,
                          view=sc.view_settings.view_transform, look=sc.view_settings.look,
                          film=sc.render.film_transparent, path=sc.render.filepath)
        sc.render.engine = "CYCLES" if self.engine.upper() == "CYCLES" else "BLENDER_EEVEE"
        if sc.render.engine == "CYCLES":
            from . import bake
            bake.setup_cycles(self.samples)
            sc.cycles.use_denoising = True
        else:
            sc.eevee.taa_render_samples = self.samples
            if hasattr(sc.eevee, "use_raytracing"):
                sc.eevee.use_raytracing = True
        sc.render.resolution_x, sc.render.resolution_y = self.size
        sc.render.resolution_percentage = 100
        sc.render.film_transparent = False
        sc.render.image_settings.file_format = "PNG"
        sc.view_settings.view_transform = "AgX"
        sc.view_settings.look = "None"
        self.world = _studio_world()
        if self.background is not None:
            self.world.node_tree.nodes["Background"].inputs["Color"].default_value = (*self.background, 1.0)
        sc.world = self.world
        lo, hi = _mesh.bounds(self.targets)
        self.lo, self.hi = lo, hi
        self.center = (lo + hi) / 2
        self.radius = max((hi - lo).length / 2, 0.05)
        cam_data = bpy.data.cameras.new("_preview_cam")
        cam_data.lens = self.lens
        cam_data.clip_start = self.radius * 0.01
        cam_data.clip_end = self.radius * 200
        self.cam = link(bpy.data.objects.new("_preview_cam", cam_data))
        sc.camera = self.cam
        r = self.radius
        self.key = _area("_preview_key", 900 * r * r, 1.6 * r, (1.0, 0.96, 0.9))
        self.fill = _area("_preview_fill", 300 * r * r, 2.4 * r, (0.85, 0.9, 1.0))
        self.rim = _area("_preview_rim", 700 * r * r, 1.2 * r, (1.0, 1.0, 1.0))
        self.added += [self.cam, self.key, self.fill, self.rim]
        if self.floor:
            from . import mat
            fl = _mesh.box("_preview_floor", (r * 60, r * 60, 0.001), (self.center.x, self.center.y, lo.z - 0.0005))
            fl.data.materials.append(mat.flat("_preview_floor", (0.012, 0.012, 0.014), rough=0.7))
            self.added.append(fl)
        return self

    def shoot(self, direction, path):
        d = Vector(direction).normalized()
        cam = self.cam
        cam.location = self.center + d * 10.0
        _aim(cam, self.center)
        sc = bpy.context.scene
        fov = cam.data.angle  # along the larger sensor dimension
        w, h = self.size
        fx = fov if w >= h else 2 * math.atan(math.tan(fov / 2) * w / h)
        fy = fov if h > w else 2 * math.atan(math.tan(fov / 2) * h / w)
        rot = cam.rotation_euler.to_matrix()  # matrix_world is stale until a depsgraph update
        right, up, back = rot.col[0], rot.col[1], rot.col[2]
        dist = 0.0
        for cx in (self.lo.x, self.hi.x):
            for cy in (self.lo.y, self.hi.y):
                for cz in (self.lo.z, self.hi.z):
                    q = Vector((cx, cy, cz)) - self.center
                    z = q.dot(back)
                    dist = max(dist, z + abs(q.dot(right)) * 1.12 / math.tan(fx / 2),
                               z + abs(q.dot(up)) * 1.12 / math.tan(fy / 2))
        cam.location = self.center + back * dist
        r = self.radius
        # Lights relative to the camera: key up-right, fill left, rim behind.
        self.key.location = cam.location + right * 1.2 * dist + up * 0.9 * dist - back * 0.2 * dist
        self.fill.location = cam.location - right * 1.3 * dist + up * 0.1 * dist - back * 0.1 * dist
        self.rim.location = self.center - back * 1.4 * max(dist, 2 * r) + up * 1.2 * max(dist, 2 * r) + right * 0.3 * r
        for L, e in ((self.key, 700), (self.fill, 220), (self.rim, 700)):
            _aim(L, self.center)
            L.data.energy = e * max(dist, r) ** 2 / 9.0
        sc.render.filepath = path
        bpy.ops.render.render(write_still=True)
        return path

    def __exit__(self, *exc):
        sc = bpy.context.scene
        for o in self.added:
            data = o.data
            bpy.data.objects.remove(o, do_unlink=True)
            if data is not None and data.users == 0:
                if isinstance(data, bpy.types.Mesh):
                    bpy.data.meshes.remove(data)
                elif isinstance(data, bpy.types.Light):
                    bpy.data.lights.remove(data)
                elif isinstance(data, bpy.types.Camera):
                    bpy.data.cameras.remove(data)
        for m in [m for m in bpy.data.materials if m.name.startswith("_preview_floor") and m.users == 0]:
            bpy.data.materials.remove(m)
        s = self.saved
        sc.render.engine = s["engine"]
        sc.world = s["world"]
        sc.camera = s["camera"]
        sc.render.resolution_x, sc.render.resolution_y = s["x"], s["y"]
        sc.render.resolution_percentage = s["pct"]
        sc.view_settings.view_transform = s["view"]
        sc.view_settings.look = s["look"]
        sc.render.film_transparent = s["film"]
        sc.render.filepath = s["path"]
        bpy.data.worlds.remove(self.world)
        return False


def _targets(targets):
    if targets is None:
        return [o for o in bpy.context.scene.objects if o.type == "MESH" and o.visible_get()]
    targets = targets if isinstance(targets, (list, tuple)) else [targets]
    out = []
    for o in targets:
        out.append(o)
        out += [c for c in o.children_recursive if c.type == "MESH"]
    return [o for o in out if o.type == "MESH"]


def render_previews(out_dir, targets=None, views=("front", "side", "back", "three_quarter"), size=(768, 1024),
                    engine="EEVEE", samples=32, prefix="", floor=True, lens=50, background=None, frame=None,
                    sheet=True):
    """Render `views` of `targets` (objects, default: every visible mesh) to
    <out_dir>/<prefix><view>.png. A view is a name from VIEWS or a direction
    tuple. sheet=True also writes <prefix>sheet.png (all views side by side).
    Returns the paths."""
    os.makedirs(out_dir, exist_ok=True)
    objs = _targets(targets)
    if frame is not None:
        bpy.context.scene.frame_set(frame)
    paths = []
    with _Studio(objs, size, engine, samples, floor, background, lens) as st:
        for v in views:
            name = v if isinstance(v, str) else "view%d" % len(paths)
            paths.append(st.shoot(VIEWS[v] if isinstance(v, str) else v, os.path.join(out_dir, f"{prefix}{name}.png")))
    if sheet and len(paths) > 1:
        contact_sheet(paths, os.path.join(out_dir, f"{prefix}sheet.png"))
    log(f"preview: {len(paths)} views in {out_dir}")
    return paths


def render_each(out_dir, objects, views=("three_quarter", "front", "side"), size=(640, 640), **kw):
    """Previews of each object on its own (the others hidden from render):
    <out_dir>/<object>_<view>.png plus <object>_sheet.png."""
    objects = [o for o in objects if o.type == "MESH"]
    everything = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    saved = {o: o.hide_render for o in everything}
    paths = []
    try:
        for o in objects:
            group = set(_targets([o]))
            for other in everything:
                other.hide_render = other not in group
            paths += render_previews(out_dir, [o], views=views, size=size, prefix=f"{o.name}_", **kw)
    finally:
        for o, h in saved.items():
            o.hide_render = h
    return paths


def turntable(out_dir, targets=None, frames=8, elevation=15.0, size=(768, 1024), prefix="turn_", **kw):
    """`frames` views around Z at `elevation` degrees: turn_00.png ... + sheet."""
    e = math.radians(elevation)
    views = [(math.sin(2 * math.pi * i / frames) * math.cos(e), math.cos(2 * math.pi * i / frames) * math.cos(e),
              math.sin(e)) for i in range(frames)]
    os.makedirs(out_dir, exist_ok=True)
    objs = _targets(targets)
    paths = []
    sheet = kw.pop("sheet", True)
    with _Studio(objs, size, kw.pop("engine", "EEVEE"), kw.pop("samples", 32), kw.pop("floor", True),
                 kw.pop("background", None), kw.pop("lens", 50)) as st:
        for i, d in enumerate(views):
            paths.append(st.shoot(d, os.path.join(out_dir, f"{prefix}{i:02d}.png")))
    if sheet:
        contact_sheet(paths, os.path.join(out_dir, f"{prefix}sheet.png"), cols=min(frames, 4))
    return paths


def contact_sheet(paths, out_path, cols=None, max_width=3072):
    """Tile same-size PNGs into one image (left to right, top to bottom)."""
    imgs = [bpy.data.images.load(p, check_existing=False) for p in paths]
    w, h = imgs[0].size
    cols = cols or len(imgs)
    rows = math.ceil(len(imgs) / cols)
    sheet = np.zeros((rows * h, cols * w, 4), dtype=np.float32)
    for i, img in enumerate(imgs):
        if tuple(img.size) != (w, h):
            continue
        a = np.empty(w * h * 4, dtype=np.float32)
        img.pixels.foreach_get(a)
        r, c = divmod(i, cols)
        # Blender rows go bottom-up: row 0 of the sheet is the bottom row.
        y0 = (rows - 1 - r) * h
        sheet[y0:y0 + h, c * w:(c + 1) * w] = a.reshape(h, w, 4)
    out = bpy.data.images.new("_sheet", cols * w, rows * h, alpha=True)
    out.pixels.foreach_set(sheet.ravel())
    out.filepath_raw = out_path
    out.file_format = "PNG"
    out.save()
    for img in imgs + [out]:
        bpy.data.images.remove(img)
    if cols * w > max_width:  # keep sheets readable in review tools
        _shrink(out_path, max_width)
    return out_path


def _shrink(path, max_width):
    img = bpy.data.images.load(path, check_existing=False)
    w, h = img.size
    k = max_width / w
    img.scale(int(w * k), int(h * k))
    img.save()
    bpy.data.images.remove(img)
