# NAS-Tools
Tools for vNAS Data

A collection of scripts for building and maintaining vNAS facility data and CRC setups. Most are single-file
Python scripts: open the file, edit the values at the top (input file, ARTCC, folders), then run it. Tools
with their own folder have their own README.

| Folder | What it is for |
|--------|----------------|
| [`atct/`](#atct--tower-cab-and-asde-x--said) | Tower cab, ASDE-X and SAID maps, plus QGIS helpers for drawing them |
| [`eram/`](#eram) | ERAM geomaps and video map files |
| [`stars/`](#stars) | Converting STARS adaptation into vNAS data, and cleaning STARS video maps |
| [`misc/`](#misc--crc-and-everything-else) | CRC profile utilities and other small helpers |

## `atct/` – Tower cab and ASDE-X / SAID

| Tool | What it does |
|------|--------------|
| [`said_builder/`](atct/said_builder/) | Builds SAID GeoJSON files (`<APT> SAID.geojson`: runways, taxiways, aprons, structures) from an airport's hand-drawn tower-cab layers, using OpenStreetMap for runway axes and buildings and ArcGIS imagery to line the result up. Start with `said_builder_init.py` (or the `.bat`), which walks through setup, building, checking and installing. See its [README](atct/said_builder/README.md). |
| `said_converter.py` | Switches your CRC profiles from ASDE-X displays to SAID displays. It reads the vNAS configuration of every ARTCC installed in CRC, finds the facilities that have a SAID, backs up your Profiles and PrefSets to a zip in `%temp%`, lists the profiles it would change, and converts them (and their PrefSets) once you confirm. |
| `batch_tower_cab_images.py` | Runs `TowerCabImageGenerator.exe` for a list of airports against one imagery tile source (ArcGIS by default; Bing, Google, OpenStreetMap and NAIP URLs are included, commented out). |
| `remove_single_point_linestring.py` | Deletes LineStrings that have only one point from every GeoJSON in a folder and writes minified copies to an `OUTPUT` subfolder. |
| `dxf_convert/` | Windows executables for converting between formats: `dxf_2_sct.exe`, `sct_2_dxf.exe` and `afcad_xml_2_sct.exe`. |
| `ASDEX-SAID Style.qml` | QGIS layer style that colours features by their `said` or `asdex` property (runway, taxiway, apron, structure). Load it from Layer Properties → Symbology → Style → Load Style. |
| `qgis-shortcuts.xml` | QGIS keyboard shortcuts for map drawing: Ctrl+E toggle editing, Ctrl+M move feature, Ctrl+W select features, Ctrl+R vertex tool. Import it from Settings → Keyboard Shortcuts. |

## `eram/`

| Tool | What it does |
|------|--------------|
| `eram_csv_to_geojson.py` | Converts ERAM geomap CSV exports (Lines, Symbols and Texts) into GeoJSON, one file per geomap object, grouped into a folder per geomap. Coordinates are converted from DMS to decimal degrees. |
| `eram_objects_to_filters.py` | Takes the per-object files from `eram_csv_to_geojson.py` and merges each geomap into one GeoJSON per filter (`<map> - FILTER 01.geojson` … `20`), filling in the line, symbol and text defaults on the way. |
| `rename_maps.py` | Copies the video maps CRC has downloaded for an ARTCC (`%localappdata%\CRC\VideoMaps\<ARTCC>`, named by ID) to `Downloads\<ARTCC> Maps`, renamed to their original source file names. |
| `find_map_filters.py` | Scans a folder of GeoJSON maps for features on a given filter (filter 1 as written), prints the matches and copies those files to a `SELECT` subfolder. |

## `stars/`

Most of these read a STARS adaptation report saved as a text file in your Downloads folder and write JSON,
also to Downloads, in the shape vNAS expects.

| Tool | What it does |
|------|--------------|
| `adaptation_to_excel.py` | Converts a plaintext DMS Site Adaptation Report into an Excel workbook, one tab per SUM section with bold headers. Tables that the report splits across several column blocks are merged back into one wide table. Usage: `python adaptation_to_excel.py <report.txt> [output.xlsx]` (needs `openpyxl`). |
| `process_lists.py` | Builds the TCW/TDW flight-plan lists (P and T lists), including their coordination channels with sending and receiving TCPs, sort fields and titles. Writes `<name>_lists.json`, `<name>_list_configs.json` (list window positions for the TCP set in `MAIN_TCP`) and `<name>_info.txt`. |
| `process_rpcs.py` | Builds the runway pair configurations (CRDA): runway IDs, region sizes, target reference points and lines, stagger and tie symbols, and the scratchpads tied to each runway. |
| `process_scratchpads.ipynb` | Builds scratchpad rules from a route-based scratchpad CSV: each route or fix pattern (with optional altitude range, aircraft class and departure airport) becomes a search pattern and template. Writes `<name>_scratchpads.json`. |
| `process_map_names.ipynb` | Pulls map numbers, mnemonics, titles and brightness categories from the adaptation's MAP section into `<facility>_map_data.csv`, matches them to GeoJSON files, reports files not in the CSV, and applies the names, short names and brightness categories to a `videomaps.json`. |
| `txt_to_json_atpa.py` | Converts the ATPA volumes section of an adaptation text file to JSON. Usage: `python txt_to_json_atpa.py <input.txt> <output.json>`. |
| `process_atpa_xml.py` | The same conversion for ATPA volumes and TCPs exported as XML spreadsheets. Run with `-h` for the arguments. |
| `remove_borders.py` | Removes the circular range border from STARS video maps: every point at or beyond the map radius from the point of tangency is deleted. It can estimate the radius and the point of tangency when they are not known. Output goes to an `OUTPUT` subfolder. |
| `track_ownership.ipynb` | Logs which TCPs own tracks at the listed facilities every five minutes, from the live dSTARS feed, into `<facility>_track_ownership.txt`. |

## `misc/` – CRC and everything else

| Tool | What it does |
|------|--------------|
| [`crc-shift-bookmarks/`](misc/crc-shift-bookmarks/) | Background helper that makes Shift+Numpad recall CRC bookmarks beyond the built-in Ctrl+Numpad 0–9, with a setup script that starts it whenever CRC opens. See its [README](misc/crc-shift-bookmarks/README.md). |
| `update_profiles.py` | Backs up your CRC Profiles, PrefSets and aliases to a dated zip, then (optionally) copies updated ones into CRC from a folder that mirrors CRC's layout, such as a synced Dropbox folder. |
| `transceiver_report.py` | Checks the transceiver setup of every position in an ARTCC using the vNAS data API. For each position it lists its transceivers, the positions that share them, and positions of the same type that do not. Saves the report to Downloads. |
| `toggle_invert_numpad.py` | Flips the "invert numeric keypad" setting in every CRC profile at once. |
| `crc_second_display_only.py` | Rewrites two-monitor CRC profiles (file names with `2` as the fourth character) for a single monitor: drops the first display window and moves the second to the primary screen. |
| `scale_secondary_list_positions.ipynb` | Halves the list positions in CRC STARS PrefSets whose names start with `/`, saving the results as `mod-` copies. For moving PrefSets to a display with half the resolution. |
| `generate_ulid.py` | Prints a handful of new ULIDs for use as IDs in vNAS data. |
| `qgis_layer_advance_macro.py` | QGIS project macro: Ctrl+Space hides the current layer and shows the next one without changing zoom, for stepping through maps. Paste it into Project → Properties → Macros. |

## Requirements

Python 3. Scripts that need extra packages either install them on first run or name them at the top; the
common ones are `pandas`, `python-ulid`, `pyperclip`, `requests` and `openpyxl`. The SAID builder checks and
installs its own. Several scripts read or write `%localappdata%\CRC`, so they are Windows-only, and some have
a folder path hard-coded at the top that you will need to change.
