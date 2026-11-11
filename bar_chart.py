"""
Animated 3D bar chart for Blender.

Reads a CSV (label, value[, colour]) and builds a scene with bars that grow
one after another, text labels, and a slow camera orbit, then renders PNG
frames to a folder.

Run headless:
    blender --background --python bar_chart.py

Or open it in Blender's Text Editor and press Run Script (set RENDER_ON_RUN
to False first if you only want to look at the scene).

The chart is built in its own scene called "BarChart", so running this inside
an existing .blend does not touch your other scenes.
"""

import csv
import math
import os
import re

import bpy

# =============================================================================
# SETTINGS
# =============================================================================

# --- Files -------------------------------------------------------------------
CSV_PATH = "data.csv"          # relative paths are resolved next to this script
OUTPUT_DIR = "frames"          # PNG frames land here as frame_0001.png, ...
SAVE_BLEND = "bar_chart.blend"  # saved next to the script in --background runs; None to skip
RENDER_ON_RUN = True           # False = build the scene only, no render

# --- CSV layout --------------------------------------------------------------
LABEL_COLUMN = 0               # zero-based column index of the bar labels
VALUE_COLUMN = 1               # zero-based column index of the numbers
# A header row is detected automatically. If the header has a column called
# "colour", "color" or "hex", its values (#RRGGBB) override BAR_COLOURS per bar.

# --- Timing ------------------------------------------------------------------
DURATION_SECONDS = 10.0        # total length of the animation
FPS = 30
START_DELAY_SECONDS = 0.4      # pause before the first bar starts growing
BAR_GROW_SECONDS = 1.2         # how long each bar takes to grow
BAR_STAGGER_SECONDS = 0.25     # delay between one bar starting and the next

# --- Resolution and render ---------------------------------------------------
RESOLUTION_X = 1920
RESOLUTION_Y = 1080
RENDER_ENGINE = "EEVEE"        # "EEVEE" (fast) or "CYCLES" (slower, nicer shadows)
SAMPLES = 32                   # render samples; lower = faster
TRANSPARENT_BACKGROUND = False  # True = PNGs with alpha, for compositing

# --- Colours (hex) -----------------------------------------------------------
BAR_COLOURS = ["#2F80ED", "#F2994A", "#27AE60", "#EB5757", "#9B51E0", "#F2C94C"]
BACKGROUND_COLOUR = "#0F1419"
FLOOR_COLOUR = "#161C24"
LABEL_COLOUR = "#FFFFFF"
VALUE_COLOUR = "#FFFFFF"
TITLE_COLOUR = "#FFFFFF"

# --- Text --------------------------------------------------------------------
TITLE = ""                     # leave empty for no title
FONT_PATH = ""                 # path to a .ttf/.otf, or empty for Blender's default
LABEL_SIZE = 0.38
VALUE_SIZE = 0.42
TITLE_SIZE = 0.75
VALUE_DECIMALS = 0
VALUE_PREFIX = ""              # e.g. "$"
VALUE_SUFFIX = ""              # e.g. "%" or "M"
LABELS_FACE_CAMERA = True      # keep text turned towards the camera as it orbits

# --- Chart geometry ----------------------------------------------------------
BAR_WIDTH = 1.0
BAR_DEPTH = 1.0
BAR_GAP = 0.6
BAR_MAX_HEIGHT = 4.0           # height of the tallest bar, in Blender units
SHOW_FLOOR = True

# --- Camera ------------------------------------------------------------------
ORBIT_DEGREES = 50.0           # total sweep over the whole duration; 360 = full circle
ORBIT_START_DEGREES = None     # None = centre the sweep on the front of the chart
CAMERA_ELEVATION_DEGREES = 16.0
CAMERA_LENS_MM = 50.0
CAMERA_ZOOM = 1.0              # >1 moves the camera closer, <1 further away

# =============================================================================
# END OF SETTINGS
# =============================================================================

SCENE_NAME = "BarChart"


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def base_dir():
    """Folder that relative paths are resolved against."""
    candidates = []
    try:
        candidates.append(os.path.dirname(os.path.abspath(__file__)))
    except NameError:
        pass
    if bpy.data.filepath:
        candidates.append(os.path.dirname(bpy.data.filepath))
    candidates.append(os.getcwd())
    for folder in candidates:
        if os.path.isfile(os.path.join(folder, CSV_PATH)):
            return folder
    return candidates[0]


def resolve(path, root):
    return path if os.path.isabs(path) else os.path.join(root, path)


def hex_to_rgba(hex_colour, alpha=1.0):
    """'#RRGGBB' or '#RGB' -> linear RGBA tuple, which is what Blender expects."""
    h = hex_colour.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    if len(h) != 6:
        raise ValueError("Not a hex colour: %r" % hex_colour)

    def to_linear(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return tuple(to_linear(int(h[i:i + 2], 16)) for i in (0, 2, 4)) + (alpha,)


def parse_number(text):
    """'1,250', '$3.5', '42%' -> float. Returns None if it is not a number."""
    cleaned = re.sub(r"[^0-9eE.+\-]", "", text.strip().replace(",", ""))
    try:
        return float(cleaned)
    except ValueError:
        return None


def read_csv(path):
    """Return a list of (label, value, colour_or_None)."""
    if not os.path.isfile(path):
        raise FileNotFoundError("CSV not found: %s" % path)

    with open(path, newline="", encoding="utf-8-sig") as handle:
        sample = handle.read(4096)
        handle.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        rows = [row for row in csv.reader(handle, dialect) if any(c.strip() for c in row)]

    if not rows:
        raise ValueError("CSV is empty: %s" % path)

    needed = max(LABEL_COLUMN, VALUE_COLUMN) + 1
    colour_column = None
    first = rows[0]
    has_header = len(first) >= needed and parse_number(first[VALUE_COLUMN]) is None
    if has_header:
        for index, name in enumerate(first):
            if name.strip().lower() in ("colour", "color", "hex"):
                colour_column = index
        rows = rows[1:]

    data = []
    for line, row in enumerate(rows, start=2 if has_header else 1):
        if len(row) < needed:
            print("Skipping row %d: not enough columns" % line)
            continue
        value = parse_number(row[VALUE_COLUMN])
        if value is None:
            print("Skipping row %d: %r is not a number" % (line, row[VALUE_COLUMN]))
            continue
        if value < 0:
            print("Row %d: negative value %s drawn as 0" % (line, value))
        colour = None
        if colour_column is not None and len(row) > colour_column and row[colour_column].strip():
            colour = row[colour_column].strip()
        data.append((row[LABEL_COLUMN].strip(), value, colour))

    if not data:
        raise ValueError("No usable rows in %s" % path)
    return data


def format_value(value):
    return "%s%s%s" % (VALUE_PREFIX, format(value, ",.%df" % VALUE_DECIMALS), VALUE_SUFFIX)


def ease_out_cubic(t):
    return 1.0 - (1.0 - t) ** 3


def make_material(name, rgba, roughness=0.5, emission=0.0):
    mat = bpy.data.materials.new(name)
    if bpy.app.version < (5, 0, 0):  # node trees are always on from 5.0
        mat.use_nodes = True
    bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = rgba
        bsdf.inputs["Roughness"].default_value = roughness
        if emission > 0.0:
            # Socket was renamed from "Emission" to "Emission Color" in Blender 4.0
            socket = bsdf.inputs.get("Emission Color") or bsdf.inputs.get("Emission")
            if socket is not None:
                socket.default_value = rgba
            strength = bsdf.inputs.get("Emission Strength")
            if strength is not None:
                strength.default_value = emission
    mat.diffuse_color = rgba  # viewport colour in Solid mode
    if emission > 0.0 and hasattr(mat, "shadow_method"):  # Blender 4.1 and older
        mat.shadow_method = "NONE"
    return mat


def link(scene, obj):
    scene.collection.objects.link(obj)
    return obj


def make_bar_mesh():
    """Unit box with its origin on the bottom face, so scaling Z grows it upward."""
    verts = [
        (-0.5, -0.5, 0.0), (0.5, -0.5, 0.0), (0.5, 0.5, 0.0), (-0.5, 0.5, 0.0),
        (-0.5, -0.5, 1.0), (0.5, -0.5, 1.0), (0.5, 0.5, 1.0), (-0.5, 0.5, 1.0),
    ]
    faces = [
        (0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
        (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
    ]
    mesh = bpy.data.meshes.new("BarMesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    return mesh


def make_text(scene, name, body, size, material, font, align_y="BOTTOM"):
    curve = bpy.data.curves.new(name, type="FONT")
    curve.body = body
    curve.size = size
    curve.align_x = "CENTER"
    curve.align_y = align_y
    curve.extrude = size * 0.02
    if font is not None:
        curve.font = font
    curve.materials.append(material)
    obj = bpy.data.objects.new(name, curve)
    obj.rotation_euler = (math.radians(90.0), 0.0, 0.0)  # upright, facing the front
    if hasattr(obj, "visible_shadow"):  # text should not cast shadows
        obj.visible_shadow = False
    return link(scene, obj)


def shrink_to_width(scene, obj, max_width):
    """Scale a text object down if it is wider than max_width. Returns the scale used."""
    scene.view_layers[0].update()
    width = obj.dimensions.x
    if width <= 0.0:  # bounds not available; fall back to a rough estimate
        width = len(obj.data.body) * obj.data.size * 0.55
    factor = min(1.0, max_width / width) if width > 0.0 else 1.0
    obj.scale = (factor, factor, factor)
    return factor


def face_camera(obj, camera):
    constraint = obj.constraints.new("COPY_ROTATION")
    constraint.target = camera


def fresh_scene():
    """Create an empty 'BarChart' scene, replacing one left over from an earlier run."""
    old = bpy.data.scenes.get(SCENE_NAME)
    scene = bpy.data.scenes.new(SCENE_NAME + "_new")
    if bpy.context.window is not None:
        bpy.context.window.scene = scene
    if old is not None:
        for obj in list(old.collection.all_objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        if old.world is not None and old.world.users <= 1:
            bpy.data.worlds.remove(old.world)
        bpy.data.scenes.remove(old)
    scene.name = SCENE_NAME
    return scene


def set_engine(scene):
    if RENDER_ENGINE.upper() == "CYCLES":
        scene.render.engine = "CYCLES"
        scene.cycles.samples = SAMPLES
        return
    # EEVEE's identifier differs between Blender versions.
    for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            scene.render.engine = engine
            break
        except TypeError:
            continue
    try:
        scene.eevee.taa_render_samples = SAMPLES
    except AttributeError:
        pass


def configure_render(scene, total_frames, output_dir):
    render = scene.render
    render.resolution_x = RESOLUTION_X
    render.resolution_y = RESOLUTION_Y
    render.resolution_percentage = 100
    render.fps = FPS
    render.fps_base = 1.0
    scene.frame_start = 1
    scene.frame_end = total_frames
    scene.frame_set(1)

    set_engine(scene)
    render.film_transparent = TRANSPARENT_BACKGROUND

    settings = render.image_settings
    if hasattr(settings, "media_type"):  # Blender 5.x
        settings.media_type = "IMAGE"
    settings.file_format = "PNG"
    settings.color_mode = "RGBA" if TRANSPARENT_BACKGROUND else "RGB"
    settings.compression = 15

    os.makedirs(output_dir, exist_ok=True)
    render.filepath = os.path.join(output_dir, "frame_")
    render.use_file_extension = True
    render.use_overwrite = True

    # "Standard" keeps the hex colours looking the way they were specified.
    try:
        scene.view_settings.view_transform = "Standard"
        scene.view_settings.look = "None"
    except TypeError:
        pass


def camera_distance(width, height):
    """Distance at which a width x height area fits the frame."""
    aspect = RESOLUTION_X / RESOLUTION_Y
    half_sensor = 18.0  # Blender's default 36 mm sensor, fitted to the longer side
    if aspect >= 1.0:
        half_h = math.atan(half_sensor / CAMERA_LENS_MM)
        half_v = math.atan(half_sensor / (CAMERA_LENS_MM * aspect))
    else:
        half_v = math.atan(half_sensor / CAMERA_LENS_MM)
        half_h = math.atan(half_sensor * aspect / CAMERA_LENS_MM)
    return max(width / 2.0 / math.tan(half_h), height / 2.0 / math.tan(half_v))


# ----------------------------------------------------------------------------
# Build
# ----------------------------------------------------------------------------

def build():
    root = base_dir()
    data = read_csv(resolve(CSV_PATH, root))
    output_dir = resolve(OUTPUT_DIR, root)

    count = len(data)
    total_frames = max(2, int(round(DURATION_SECONDS * FPS)))
    peak = max(max(value for _, value, _ in data), 1e-9)

    scene = fresh_scene()
    configure_render(scene, total_frames, output_dir)

    # --- World ---------------------------------------------------------------
    world = bpy.data.worlds.new("BarChartWorld")
    if bpy.app.version < (5, 0, 0):  # node trees are always on from 5.0
        world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background is not None:
        background.inputs[0].default_value = hex_to_rgba(BACKGROUND_COLOUR)
        background.inputs[1].default_value = 1.0
    scene.world = world

    # --- Shared resources ----------------------------------------------------
    font = bpy.data.fonts.load(FONT_PATH) if FONT_PATH else None
    bar_mesh = make_bar_mesh()
    label_mat = make_material("LabelText", hex_to_rgba(LABEL_COLOUR), emission=1.0)
    value_mat = make_material("ValueText", hex_to_rgba(VALUE_COLOUR), emission=1.0)

    pitch = BAR_WIDTH + BAR_GAP
    chart_width = count * BAR_WIDTH + (count - 1) * BAR_GAP
    first_x = -chart_width / 2.0 + BAR_WIDTH / 2.0
    value_gap = VALUE_SIZE * 0.35
    chart_top = BAR_MAX_HEIGHT + value_gap + VALUE_SIZE

    # --- Camera rig (made first so labels can be pointed at the camera) ------
    title_space = (TITLE_SIZE * 1.8) if TITLE else 0.0
    content_height = chart_top + title_space
    target_z = content_height * 0.45
    fit_width = (chart_width + BAR_DEPTH + 1.5) * 1.15
    fit_height = (content_height + LABEL_SIZE) * 1.3
    # Push the category labels far enough forward that, seen from the camera's
    # height, they sit in front of the bars instead of overlapping them.
    label_offset = 0.15 + LABEL_SIZE * 0.8 / max(math.tan(math.radians(CAMERA_ELEVATION_DEGREES)), 0.2)
    fit_width += label_offset
    distance = camera_distance(fit_width, fit_height) / max(CAMERA_ZOOM, 0.01)

    pivot = link(scene, bpy.data.objects.new("OrbitPivot", None))
    pivot.empty_display_size = 0.5
    pivot.location = (0.0, 0.0, target_z)

    cam_data = bpy.data.cameras.new("ChartCamera")
    cam_data.lens = CAMERA_LENS_MM
    cam_data.clip_end = max(1000.0, distance * 10.0)
    camera = link(scene, bpy.data.objects.new("ChartCamera", cam_data))
    camera.parent = pivot
    elevation = math.radians(CAMERA_ELEVATION_DEGREES)
    camera.location = (0.0, -distance * math.cos(elevation), distance * math.sin(elevation))
    track = camera.constraints.new("TRACK_TO")
    track.target = pivot
    track.track_axis = "TRACK_NEGATIVE_Z"
    track.up_axis = "UP_Y"
    scene.camera = camera

    orbit_start = -ORBIT_DEGREES / 2.0 if ORBIT_START_DEGREES is None else ORBIT_START_DEGREES
    for frame in range(1, total_frames + 1):
        progress = (frame - 1) / (total_frames - 1)
        pivot.rotation_euler = (0.0, 0.0, math.radians(orbit_start + ORBIT_DEGREES * progress))
        pivot.keyframe_insert("rotation_euler", index=2, frame=frame)

    # --- Timing --------------------------------------------------------------
    grow = min(BAR_GROW_SECONDS, DURATION_SECONDS * 0.8)
    delay = min(START_DELAY_SECONDS, max(0.0, DURATION_SECONDS * 0.85 - grow))
    stagger = BAR_STAGGER_SECONDS
    if count > 1:
        # Squeeze the stagger if the bars would not all finish in time.
        latest = DURATION_SECONDS * 0.85 - delay - grow
        stagger = max(0.0, min(stagger, latest / (count - 1)))
    grow_frames = max(1, int(round(grow * FPS)))

    # --- Bars and labels -----------------------------------------------------
    for index, (label, value, colour) in enumerate(data):
        x = first_x + index * pitch
        height = BAR_MAX_HEIGHT * max(value, 0.0) / peak
        bar_hex = colour or BAR_COLOURS[index % len(BAR_COLOURS)]
        try:
            bar_rgba = hex_to_rgba(bar_hex)
        except ValueError:
            print("Bad colour %r for %r, using the palette instead" % (bar_hex, label))
            bar_rgba = hex_to_rgba(BAR_COLOURS[index % len(BAR_COLOURS)])

        mesh = bar_mesh.copy()
        mesh.materials.append(make_material("BarMat_%02d" % (index + 1), bar_rgba, 0.45))
        bar = link(scene, bpy.data.objects.new("Bar_%02d" % (index + 1), mesh))
        bar.location = (x, 0.0, 0.0)
        bar.scale = (BAR_WIDTH, BAR_DEPTH, 0.0001)

        name_obj = make_text(scene, "Label_%02d" % (index + 1), label, LABEL_SIZE, label_mat, font)
        name_obj.location = (x, -BAR_DEPTH / 2.0 - label_offset, 0.03)
        shrink_to_width(scene, name_obj, pitch * 0.95)

        value_obj = make_text(scene, "Value_%02d" % (index + 1), format_value(value),
                              VALUE_SIZE, value_mat, font)
        value_obj.location = (x, 0.0, value_gap)
        value_scale = shrink_to_width(scene, value_obj, pitch * 0.95)

        if LABELS_FACE_CAMERA:
            face_camera(name_obj, camera)
            face_camera(value_obj, camera)

        # Keyed on every frame of the growth so the motion does not depend on
        # Blender's keyframe interpolation settings.
        start = 1 + int(round((delay + index * stagger) * FPS))
        start = min(start, total_frames - 1)
        end = min(start + grow_frames, total_frames)
        for frame in range(start, end + 1):
            t = ease_out_cubic((frame - start) / (end - start))
            bar.scale = (BAR_WIDTH, BAR_DEPTH, max(height * t, 0.0001))
            bar.keyframe_insert("scale", frame=frame)

            value_obj.location.z = height * t + value_gap
            value_obj.keyframe_insert("location", index=2, frame=frame)
            pop = max(value_scale * min(1.0, t * 1.5), 0.0001)
            value_obj.scale = (pop, pop, pop)
            value_obj.keyframe_insert("scale", frame=frame)

    # --- Title ---------------------------------------------------------------
    if TITLE:
        title_mat = make_material("TitleText", hex_to_rgba(TITLE_COLOUR), emission=1.0)
        title = make_text(scene, "Title", TITLE, TITLE_SIZE, title_mat, font)
        title.location = (0.0, 0.0, chart_top + TITLE_SIZE * 0.6)
        shrink_to_width(scene, title, max(chart_width * 1.2, 6.0))
        if LABELS_FACE_CAMERA:
            face_camera(title, camera)

    # --- Floor ---------------------------------------------------------------
    if SHOW_FLOOR:
        half = max(400.0, distance * 20.0)
        floor_mesh = bpy.data.meshes.new("FloorMesh")
        floor_mesh.from_pydata(
            [(-half, -half, 0.0), (half, -half, 0.0), (half, half, 0.0), (-half, half, 0.0)],
            [], [(0, 1, 2, 3)])
        floor_mesh.update()
        floor_mesh.materials.append(make_material("Floor", hex_to_rgba(FLOOR_COLOUR), 0.8))
        link(scene, bpy.data.objects.new("Floor", floor_mesh))

    # --- Lights --------------------------------------------------------------
    key_data = bpy.data.lights.new("KeyLight", type="SUN")
    key_data.energy = 3.5
    key_data.angle = math.radians(8.0)  # soft shadow edges
    key = link(scene, bpy.data.objects.new("KeyLight", key_data))
    key.rotation_euler = (math.radians(50.0), 0.0, math.radians(35.0))

    fill_data = bpy.data.lights.new("FillLight", type="SUN")
    fill_data.energy = 1.2
    fill_data.use_shadow = False
    fill = link(scene, bpy.data.objects.new("FillLight", fill_data))
    fill.rotation_euler = (math.radians(60.0), 0.0, math.radians(-60.0))

    scene.frame_set(1)
    print("Built %d bars, %d frames at %d fps (%dx%d)"
          % (count, total_frames, FPS, RESOLUTION_X, RESOLUTION_Y))
    return scene, root, output_dir


def main():
    scene, root, output_dir = build()

    if SAVE_BLEND and bpy.app.background:
        blend_path = resolve(SAVE_BLEND, root)
        bpy.ops.wm.save_as_mainfile(filepath=blend_path)
        print("Saved %s" % blend_path)

    if RENDER_ON_RUN:
        print("Rendering to %s" % output_dir)
        bpy.ops.render.render(animation=True, scene=scene.name)
        print("Done. Frames are in %s" % output_dir)


if __name__ == "__main__":
    main()
