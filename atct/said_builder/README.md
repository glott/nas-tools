# SAID builder

Builds ASDE-X SAID files (`asdex/<APT> SAID.geojson`) from the hand-drawn tower-cab layers of the maps
repository (`diagrams/<APT>/`).

## Getting started

    python said_builder_init.py          # or double-click said_builder_init.bat

The setup walks through everything and asks before it changes anything outside this folder:

1. checks the Python packages (shapely 2, pyproj, numpy, scipy, Pillow, requests, matplotlib) and offers to
   install what is missing
2. finds the tower-cab maps repository (the folder with `diagrams/` and `asdex/`) and remembers it in
   `config.json`
3. lists every airport with tower-cab layers, and whether it already has a SAID
4. for the airports you pick: fetches runway axes and building footprints from OpenStreetMap, measures how far
   the linework sits from the ArcGIS imagery, builds, checks, and renders review pictures into `out/`
5. installs into `asdex/` only on a yes. A SAID that was not made by this builder is never overwritten without
   an explicit yes; say no and it offers to save the build next to it as `<APT> SAID AUTO.geojson` instead.

`python said_builder_init.py LVK` does the same for one airport; `--yes` runs without questions (and without
installing).

Afterwards:

    python build.py LVK                  # rebuild -> new/LVK SAID.geojson, prints a report
    python check.py LVK                  # validity, overlaps, gaps, connectivity, centreline coverage
    python review.py LVK walk 0 20       # zoomed tiles over the imagery -> out/LVK_walk_0.jpg
    python build.py --install LVK        # rebuild and copy to asdex/LVK SAID.geojson, or to
                                         # 'LVK SAID AUTO.geojson' if a SAID it did not make is there
                                         # (--overwrite replaces it, --auto always uses the AUTO name)

An airport needs the `base`, `markings` and `taxi_lines` layers with the usual colours (`lines` is optional).

## The idea

A SAID is traced to the painted **edge lines**; the tower-cab map is traced to the full width of the concrete.
The tower-cab map already holds the edge lines, runway stripes, centrelines and ramp outlines, all drawn by
hand, so the SAID is derived from those lines. Edges are as straight and smooth as the lines that were drawn.

| SAID      | comes from                                                                                          |
| --------- | --------------------------------------------------------------------------------------------------- |
| runway    | rectangle spanned by the runway side stripes (`_markings`), one per runway; crossing runways overlap |
| taxiway   | movement-area pavement (`_base` `#717171`) on the centreline side of the **solid** edge lines (`_taxi_lines` `#a29857`) |
| apron     | ramp pavement (`_base` `#a1a1a1`), minus strips outside a solid edge line drawn on the ramp           |
| structure | `airports/<APT>/structures.geojson`, copied unchanged                                                |

Rules, taken from how the hand-drawn SAIDs (HWD, LVK, STS, RNO, ...) relate to their tower-cab maps:

- A solid edge line is a boundary. Pavement outside it (shoulders, painted islands) is left out.
- A **dashed** edge line is not a boundary. Taxiway and apron meet where the movement and ramp base polygons meet.
- Pavement is a taxiway only if a movement centreline (`#858585`) runs on it. Blast pads / chevron areas,
  runway shoulders and closed pavement with no centreline are left out.
- Where a stretch has no edge line, the drawn pavement edge is the boundary.
- A runway whose stripes were drawn from the threshold bars is extended the 20 ft to the pavement end.
- Blast pads (chevron areas) are left out by default, as at ZOA. Facilities that draw them as taxiway (ZMA) set
  `"blast_pads": "taxiway"` in `config.json`; the setup asks once.
- Aprons are cut around the building footprints, not drawn under them.

How good the result is depends on the tower-cab map. With solid edge lines drawn (SCK, CCR) it needs almost
nothing by hand. Without them (APC) taxiways follow the drawn pavement edge, and every place where the base
layer is wider than the paint, or no longer matches the ground, needs a correction.

## Corrections: `airports/<APT>/fix.geojson`

A normal GeoJSON layer you can draw in QGIS over the imagery (true positions: the registration shift is not
applied to it). Each feature has a property `op`, and a free-text `note`:

| op        | geometry   | effect                                                                                   |
| --------- | ---------- | ---------------------------------------------------------------------------------------- |
| `cut`     | Polygon    | not usable pavement (old pavement beyond a painted edge, grass drawn as ramp): removed   |
| `add`     | Polygon    | pavement the base lacks; property `to` = `movement` (default) or `ramp`                   |
| `edge`    | LineString | a painted solid edge line the taxi_lines layer lacks                                      |
| `taxiway` | Polygon    | ramp pavement that is really a taxiway (a concrete taxiway laid through an apron)         |

Only the edge of a `cut` that should become the new boundary has to be exact; the rest just has to lie off the
pavement. `paint.py` fits a straight line to a painted line in the imagery (a few cm over 50-100 m), which is
how the APC corrections were made (`mkfix_APC.py`).

`airports/<APT>/cfg.py` (`CFG = {...}`) holds numeric overrides and `extra_edges`; only SCK has one.

## Steps (`build.py`)

1. **Register.** Every tower-cab layer is moved by the airport's shift (`airports/<APT>/airport.json`, about
   0.5-1 m) so the linework sits on the current ArcGIS World Imagery. `register.py` measures it two ways
   (paint under the edge lines / centrelines, and runway markings against image brightness). Set the shift to
   `[0, 0]` to make the SAID coincide with the tower-cab map instead.
2. **Corrections** from `fix.geojson` are applied to the base.
3. **Runways** (`rwy.py`): for each OpenStreetMap runway axis, the rectangle spanned by the side stripes; a
   runway with no side stripes uses the drawn pavement edges. Compare the printed sizes with the published ones.
4. **Dividers**: the solid edge lines, with each free end closed onto what it ends at.
5. **Faces**: all pavement minus the runways is cut by the dividers and each face classified by the rules above.
6. **Assemble**: faces are merged, slivers thinner than ~2.5 m cut off, and everything rebuilt from one
   arrangement on a 1 cm grid so polygons that meet share identical vertices.

## Before installing

`check.py` does not replace looking. Walk the review tiles, and look in particular for:

- a taxiway that is wider than the paint (run-up pads and bays often have a painted outline inside the
  pavement edge)
- grass or old pavement inside a polygon (the base layer is older than the imagery)
- building footprints that do not sit on their roofs: fix them in `structures.geojson`

## Files

| file                 | purpose                                                                   |
| -------------------- | ------------------------------------------------------------------------- |
| `said_builder_init.py` / `.bat` | guided setup                                                     |
| `paths.py`           | where things live (`config.json`, `airports/<APT>/`)                      |
| `fetch.py`           | OpenStreetMap runway axes and building footprints for an airport          |
| `register.py`        | measures and stores the registration shift (uses `reg.py`, `reg2.py`)     |
| `build.py`, `rwy.py`, `tc.py` | the builder, runway fitting, tower-cab layer loader               |
| `check.py`           | geometry checks; `--installed` checks the files in `asdex/`               |
| `review.py`, `render.py`, `twr.py`, `dbg.py`, `schem.py`, `grid.py` | review pictures and plots   |
| `paint.py`           | straight-line fit of a painted line in the imagery                        |
| `mkfix_APC.py`, `fillet.py` | how the APC corrections and the SCK extra edge lines were generated  |

`config.json`, `tiles/` (imagery cache), `new/` (build output) and `out/` (pictures) are not committed.

## Notes per airport

- **SCK** - 22 solid edge lines. One connector between the runways has paint but no drawn edge lines; they were
  generated (`airports/SCK/extra_edges.json`). The helicopter pad north of taxiway B has no lines in the
  tower-cab map and is left out.
- **CCR** - 54 solid edge lines, nothing overridden. Closed strips marked with X have no centrelines and are
  left out.
- **APC** - no solid edge lines in the tower-cab map, so taxiways follow the drawn pavement edge. Five
  corrections: the 19R run-up pad (paint, and old pavement east of it), the grass strip between the parallel
  taxiway and the apron's north-west corner, the run-up bay near 06 (paint 6-7 m inside the pavement edge), and
  the concrete taxiway through the main ramp.
