# Diagram updater

Checks a SAID / ASDE-X file, or a tower-cab base layer, against OpenStreetMap and current satellite imagery
and shows where it is out of date. The original file is never changed.

    python diagram_updater.py                   # asks for the folder and which diagrams
    python diagram_updater.py PATH SRQ SJC      # PATH = the folder with asdex/ and diagrams/

Options: `--said-only`, `--towercab-only`, `--blast-pads taxiway|exclude`, `--apply-low`, `--refresh-osm`,
`--yes` (no questions). Needs shapely 2, pyproj, numpy, scipy, Pillow, requests, contourpy.

## Output (`out/<APT>/`)

| file                        | what                                                                               |
| --------------------------- | ---------------------------------------------------------------------------------- |
| `<name> UPDATED.geojson`    | the proposed diagram, same format and properties as the original                   |
| `<name> CHANGES.geojson`    | one polygon per difference, with `change`, `kind`, `area_m2`, `basis`, `confidence`, `applied`, `note`, `lon`, `lat` |
| `<name> overview.jpg`       | the airport with numbered differences                                              |
| `<name> changes N-M.jpg`    | one imagery tile per difference (white = drawn pavement, green = added, red = removed, yellow = check) |

Load `CHANGES` over the diagram in QGIS and style it by `change`.

## What it supports

- **SAID** (`said` property) and **ASDE-X** (`asdex` property) files in `asdex/`: `<APT> SAID.geojson`,
  `<APT> ASDEX.geojson`, `<APT> ASSC.geojson`. The property name is kept in the output.
- **Tower-cab base** layers (`diagrams/<APT>/*_base.geojson`): movement `#717171` and ramp `#a1a1a1`.
  Only the base layer is checked; markings and lines are not.
- **Blast pads**: drawn as taxiway in a SAID at some facilities (ZMA) and left out at others (ZOA), so it asks
  (once, remembered in `config.json`). Never applied to an ASDE-X file or a tower-cab base.

## How it decides

1. A paved / not-paved colour model is learned from the diagram itself (well inside the drawn pavement against
   well outside it), so it adapts to each airport's imagery.
2. **removed**: drawn pavement that is clearly grass- or soil-coloured (grey of any brightness counts as
   pavement), at least 7 m wide and 300 m2.
3. **added**: paved ground outside the drawn pavement that OpenStreetMap also maps as taxiway, taxilane or
   apron (high confidence), or a large paved area attached to drawn pavement that OpenStreetMap does not have
   (low confidence). Buildings, roads and car parks from OpenStreetMap are never proposed.
4. **check**: an OpenStreetMap taxiway or taxilane with no drawn pavement under it.
5. A narrow paved strip along drawn pavement is called a shoulder and left out of a SAID / ASDE-X.

Only additions backed by both OpenStreetMap and imagery are applied to the updated copy. Removals are listed
but applied only with `--apply-removed` (the imagery may simply be older than the diagram); `--apply-low`
applies everything. All differences are in `CHANGES` either way.

## Limits

- **The imagery can be older than the diagram.** The run prints the capture date. Where the diagram already
  shows new construction, the imagery shows bare ground and the finding is a "removed": those are flagged but
  not applied. SRQ's north side is the example (imagery January 2025).
- Outlines of added pavement are simplified imagery outlines at about 0.6 m per pixel. They show where and
  roughly what; redraw them by hand, or rebuild the SAID with the SAID builder after updating the tower-cab map.
- Shadows give no verdict, and pavement the same colour as its surroundings (old asphalt next to bare soil)
  can be missed or over-called.
- Painted edge lines are not considered: a SAID that is too wide for the paint is not detected here.
