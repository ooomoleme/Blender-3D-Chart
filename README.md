# Animated 3D bar chart (Blender)

`bar_chart.py` reads `data.csv`, builds a 3D bar chart in Blender with bars that grow one after another, labels, and a slow camera orbit, then renders PNG frames to a `frames/` folder. FFmpeg turns the frames into an MP4.

## Files

| File | Purpose |
| --- | --- |
| `bar_chart.py` | The Blender script. All settings are at the top. |
| `data.csv` | Sample data. Replace with your own. |
| `README.md` | This file. |

## Requirements

- Blender 3.6 or newer. Tested on Blender 5.0.1; the version-specific parts (EEVEE engine name, emission socket name, output settings) have fallbacks for older releases, but those were not run.
- FFmpeg, for the MP4 step.

## Data format

Two columns: label, then value. A header row is optional and detected automatically.

```csv
label,value
North,120
South,340
East,275
```

- Bars appear in the order of the rows.
- Values may include thousands separators, currency symbols or `%` (`"1,250"`, `$3.5`, `42%`); these are stripped.
- Negative values are drawn as zero-height bars.
- Optional third column named `colour`, `color` or `hex` sets a bar's colour, e.g. `#EB5757`. Bars without one use the palette in the settings.
- If your label and value are in other columns, change `LABEL_COLUMN` and `VALUE_COLUMN` (zero-based).

## Render the frames

Put `bar_chart.py` and `data.csv` in the same folder, then from that folder:

```bash
blender --background --python bar_chart.py
```

If `blender` is not on your PATH, use the full path to it:

```bash
# Windows
"C:\Program Files\Blender Foundation\Blender 5.0\blender.exe" --background --python bar_chart.py

# macOS
/Applications/Blender.app/Contents/MacOS/Blender --background --python bar_chart.py
```

Frames are written to `frames/frame_0001.png`, `frame_0002.png`, and so on. A `bar_chart.blend` is also saved next to the script so you can open the scene and adjust it by hand.

### Running inside Blender instead

Open the Scripting workspace, load `bar_chart.py` in the Text Editor and press Run Script. The chart is built in a new scene called `BarChart`, so the rest of your file is left alone. Set `RENDER_ON_RUN = False` first if you only want to preview; otherwise Blender's window freezes until the render finishes. If the CSV is not found, set `CSV_PATH` to an absolute path.

## Make the MP4

Run this from the folder that contains `frames/`. Keep `-framerate` equal to `FPS` in the script.

```bash
ffmpeg -framerate 30 -start_number 1 -i frames/frame_%04d.png -c:v libx264 -crf 18 -preset slow -pix_fmt yuv420p -movflags +faststart bar_chart.mp4
```

- `-crf 18` is high quality. Raise it (e.g. 23) for a smaller file.
- `-pix_fmt yuv420p` makes the file play in browsers, phones and editing software.
- H.264 needs even width and height. If you set an odd resolution, add `-vf "pad=ceil(iw/2)*2:ceil(ih/2)*2"`.

### With a transparent background

MP4 cannot hold transparency. Set `TRANSPARENT_BACKGROUND = True` (and usually `SHOW_FLOOR = False`), render, then either import the PNG sequence straight into your editor or make a ProRes 4444 file:

```bash
ffmpeg -framerate 30 -start_number 1 -i frames/frame_%04d.png -c:v prores_ks -profile:v 4444 -pix_fmt yuva444p10le bar_chart_alpha.mov
```

## Settings

All of these are at the top of `bar_chart.py`.

| Setting | Default | What it does |
| --- | --- | --- |
| `CSV_PATH` | `data.csv` | Input file. Relative paths are resolved next to the script. |
| `OUTPUT_DIR` | `frames` | Folder for the PNG frames. |
| `SAVE_BLEND` | `bar_chart.blend` | Scene file saved in `--background` runs. `None` to skip. |
| `RENDER_ON_RUN` | `True` | `False` builds the scene without rendering. |
| `DURATION_SECONDS` | `10.0` | Total length. |
| `FPS` | `30` | Frame rate. |
| `START_DELAY_SECONDS` | `0.4` | Pause before the first bar grows. |
| `BAR_GROW_SECONDS` | `1.2` | Growth time per bar. |
| `BAR_STAGGER_SECONDS` | `0.25` | Delay between bars. Shortened automatically if the bars would not all finish within the duration. |
| `RESOLUTION_X`, `RESOLUTION_Y` | `1920`, `1080` | Output size. Use `1080`, `1920` for vertical; the camera distance adjusts to fit. |
| `RENDER_ENGINE` | `EEVEE` | `EEVEE` is fast; `CYCLES` is slower with softer shadows. |
| `SAMPLES` | `32` | Render samples. Lower is faster and noisier. |
| `TRANSPARENT_BACKGROUND` | `False` | PNGs with an alpha channel. |
| `BAR_COLOURS` | six hex colours | Palette, cycled across the bars. |
| `BACKGROUND_COLOUR`, `FLOOR_COLOUR` | dark greys | Scene colours. |
| `LABEL_COLOUR`, `VALUE_COLOUR`, `TITLE_COLOUR` | white | Text colours. |
| `TITLE` | empty | Text shown above the chart. |
| `FONT_PATH` | empty | Path to a `.ttf` or `.otf`. Empty uses Blender's built-in font. |
| `LABEL_SIZE`, `VALUE_SIZE`, `TITLE_SIZE` | `0.38`, `0.42`, `0.75` | Text sizes in Blender units. Long text is shrunk to fit its bar. |
| `VALUE_DECIMALS`, `VALUE_PREFIX`, `VALUE_SUFFIX` | `0`, empty, empty | Number formatting, e.g. prefix `$` or suffix `%`. |
| `LABELS_FACE_CAMERA` | `True` | Text turns to face the camera as it orbits. |
| `BAR_WIDTH`, `BAR_DEPTH`, `BAR_GAP`, `BAR_MAX_HEIGHT` | `1.0`, `1.0`, `0.6`, `4.0` | Bar geometry. The largest value gets `BAR_MAX_HEIGHT`. |
| `SHOW_FLOOR` | `True` | Ground plane that catches shadows. |
| `ORBIT_DEGREES` | `50.0` | Total camera sweep over the whole duration. `360` is a full circle. |
| `ORBIT_START_DEGREES` | `None` | Starting angle. `None` centres the sweep on the front. |
| `CAMERA_ELEVATION_DEGREES` | `16.0` | Camera height angle above the floor. |
| `CAMERA_LENS_MM` | `50.0` | Focal length. |
| `CAMERA_ZOOM` | `1.0` | Above 1 moves closer, below 1 further away. |

## Tips

- **Quick test first.** Set `DURATION_SECONDS = 2` and halve the resolution, check a few frames, then render the full version.
- **Speed.** Render time depends heavily on the GPU. Lower `SAMPLES` or the resolution if it is slow.
- **Full 360 orbit.** Category labels stay in front of the chart, so on the far side of a full circle they are hidden behind the bars. A sweep of up to about 90 degrees keeps everything readable.
- **Many bars.** The camera pulls back to fit the chart, so with more than about 12 bars the text gets small. Raise the text sizes or split the data.
- **Re-running.** Each run replaces the `BarChart` scene and overwrites frames with the same numbers. If you shorten the duration, delete the `frames/` folder first so leftover frames from the longer render do not end up in the MP4.
