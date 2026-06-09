#!/usr/bin/env python
# coding: utf-8

import json
import os
import re
import sys
import shutil
import textwrap
import time
from datetime import datetime
import requests

# ==============================================================================
# INITIALIZATION & WARNING
# ==============================================================================
print("=" * 70)
print(" NOTICE: This script will only replace ASDE-X displays with SAIDs if a")
print(" facility has active SAID config and NO active ASDE-X config.")
print("=" * 70)
print()

# ==============================================================================
# [STEP 1/3]: FETCH CONFIGURATIONS FROM vNAS
# ==============================================================================
print("[STEP 1/3] Fetching latest ARTCC configuration data from vNAS...")

folder_path = os.path.expandvars(r"%localappdata%\CRC\ARTCCs")
artcc_list = []

if os.path.exists(folder_path):
    for filename in os.listdir(folder_path):
        if filename.endswith(".json"):
            artcc_list.append(os.path.splitext(filename)[0])
else:
    print(f"  [-] Directory not found: {folder_path}")
    artcc_list = []

said_facilities = []
asdex_facilities = []

for artcc in artcc_list:
    url = f"https://data-api.vnas.vatsim.net/api/artccs/{artcc}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        config = response.json()
    except Exception as e:
        print(f"  [!] Could not fetch data for {artcc}: {e}")
        continue

    facility_data = config.get("facility", {})
    child_facilities = facility_data.get("childFacilities", [])

    for child_facility in child_facilities:
        if "saidConfiguration" in child_facility:
            said_facilities.append(child_facility.get("id"))
        if "asdexConfiguration" in child_facility:
            asdex_facilities.append(child_facility.get("id"))

        if "childFacilities" in child_facility:
            child_child_facilities = child_facility.get("childFacilities", [])
            for child_child_facility in child_child_facilities:
                if "saidConfiguration" in child_child_facility:
                    said_facilities.append(child_child_facility.get("id"))
                if "asdexConfiguration" in child_child_facility:
                    asdex_facilities.append(child_child_facility.get("id"))

said_facilities = sorted(list(set(said_facilities)))
asdex_facilities = sorted(list(set(asdex_facilities)))

print(f"  [+] Successfully processed {len(artcc_list)} ARTCC files.\n")

wrapper = textwrap.TextWrapper(width=65, initial_indent="      ", subsequent_indent="      ")

print(f"  >>> SAID-ENABLED FACILITIES ({len(said_facilities)}):")
if said_facilities:
    print(wrapper.fill(", ".join(said_facilities)))
else:
    print("      None detected.")

print(f"\n  >>> ASDE-X-ENABLED FACILITIES ({len(asdex_facilities)}):")
if asdex_facilities:
    print(wrapper.fill(", ".join(asdex_facilities)))
else:
    print("      None detected.")
print()


# ==============================================================================
# [STEP 2/3]: PROFILE & PREFSETS BACKUP
# ==============================================================================
print("[STEP 2/3] Creating safety backup of your current CRC profiles and prefsets...")

profiles_dir = os.path.expandvars(r"%localappdata%\CRC\Profiles")
prefsets_dir = os.path.expandvars(r"%localappdata%\CRC\PrefSets")

timestamp = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
zip_filename = f"CRC Backup {timestamp}"
temp_backup_dir = os.path.join(os.path.expandvars("%temp%"), f"CRC_Backup_Staging_{timestamp}")
destination_zip_path = os.path.join(os.path.expandvars("%temp%"), zip_filename)

try:
    # Create a fresh temporary folder to aggregate directories for the zip archive
    os.makedirs(temp_backup_dir, exist_ok=True)
    
    profiles_copied = False
    prefsets_copied = False

    if os.path.exists(profiles_dir):
        shutil.copytree(profiles_dir, os.path.join(temp_backup_dir, "Profiles"))
        profiles_copied = True
    else:
        print(f"  [!] WARNING: Profiles directory not found at {profiles_dir}")

    if os.path.exists(prefsets_dir):
        shutil.copytree(prefsets_dir, os.path.join(temp_backup_dir, "PrefSets"))
        prefsets_copied = True
    else:
        print(f"  [!] WARNING: PrefSets directory not found at {prefsets_dir}")

    if profiles_copied or prefsets_copied:
        shutil.make_archive(destination_zip_path, "zip", temp_backup_dir)
        print(f"  [+] Success: Backup saved to %temp%\\{zip_filename}.zip\n")
    else:
        print("  [-] ERROR: Neither Profiles nor PrefSets directories were found. Backup aborted.\n")

finally:
    # Always clean up the temporary staging folder
    if os.path.exists(temp_backup_dir):
        shutil.rmtree(temp_backup_dir)


# ==============================================================================
# [STEP 3/3]: PROFILE PROCESSING & REPLACEMENT
# ==============================================================================
print("[STEP 3/3] Scanning CRC profiles for eligible SAID replacements...")

asdex_to_saids = []
eligible_profile_replacements = {}
loaded_profiles = {}
run_replacement = False

if os.path.exists(profiles_dir):
    for filename in os.listdir(profiles_dir):
        if filename.endswith(".json"):
            file_path = os.path.join(profiles_dir, filename)

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    profile = json.load(f)
            except Exception as e:
                continue

            profile_name = profile.get("Name", "Unknown Profile")
            display_window_settings = profile.get("DisplayWindowSettings", [])
            profile_changes = []

            for window in display_window_settings:
                display_settings = window.get("DisplaySettings", [])
                for display in display_settings:
                    if "$type" in display and "FacilityId" in display:
                        display_type = display["$type"].split(",")[0]
                        facility_id = display["FacilityId"]

                        if ".Asdex." in display_type:
                            is_in_saids = facility_id in said_facilities
                            is_in_asdex = facility_id in asdex_facilities

                            if is_in_saids and not is_in_asdex:
                                if facility_id not in profile_changes:
                                    profile_changes.append(facility_id)

            if profile_changes:
                eligible_profile_replacements[profile_name] = profile_changes
                loaded_profiles[filename] = (file_path, profile)

    if not eligible_profile_replacements:
        print("  [+] Scan complete: No profiles require modification.")
    else:
        max_name_len = max(len(name) for name in eligible_profile_replacements.keys())

        print("\n  >>> Eligible SAID replacements found:")
        for prof_name, changes in eligible_profile_replacements.items():
            print(f"      {prof_name:<{max_name_len + 2}}{changes}")
        print()

        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            user_input = input("  Confirm execution: Type 'SAID' and press Enter: ").strip()

            if user_input.upper() == "SAID":
                print("\n  Applying replacements...")
                run_replacement = True
                break
            else:
                remaining = max_attempts - attempt
                if remaining > 0:
                    print(f"  [!] Invalid input. You have {remaining} {'try' if remaining == 1 else 'tries'} left.\n")
                else:
                    print("\n  [!] Too many invalid attempts. Exiting script without making changes.")

    if run_replacement:
        all_modified_profiles = {}

        for filename, (file_path, profile) in loaded_profiles.items():
            profile_name = profile.get("Name", "Unknown Profile")
            display_window_settings = profile.get("DisplayWindowSettings", [])
            profile_changes = []
            profile_modified = False

            for window in display_window_settings:
                display_settings = window.get("DisplaySettings", [])
                for display in display_settings:
                    if "$type" in display and "FacilityId" in display:
                        display_type = display["$type"].split(",")[0]
                        facility_id = display["FacilityId"]

                        if ".Asdex." in display_type:
                            is_in_saids = facility_id in said_facilities
                            is_in_asdex = facility_id in asdex_facilities

                            if is_in_saids and not is_in_asdex:
                                # 1. Update the display type metadata
                                display["$type"] = "Vatsim.Nas.Crc.Ui.Displays.SaabSaid.Settings.SaabSaidDisplaySettings, CRC"
                                
                                # 2. Strip non-SAID compatible properties from the main object
                                display.pop("ActivePositionIds", None)
                                display.pop("Volume", None)

                                # 3. Remap individual display window components
                                pref_set = display.get("CurrentPrefSet", {})
                                inner_windows = pref_set.get("Windows", [])
                                
                                for win in inner_windows:
                                    if win.get("DisplayType") == "Asdex":
                                        win["DisplayType"] = "SaabSaid"
                                    
                                    # Structure rebuilding to inject elements in schema order
                                    new_win_layout = {}
                                    for key, value in win.items():
                                        new_win_layout[key] = value
                                        
                                        # Inject after EnableAntiAliasing
                                        if key == "EnableAntiAliasing":
                                            new_win_layout["ShowRangeRings"] = False
                                            new_win_layout["RangeRingsScale"] = 2
                                            
                                        # Inject after LeaderLength
                                        if key == "LeaderLength":
                                            new_win_layout["LabelDeconflictEnabled"] = True
                                            
                                    win.clear()
                                    win.update(new_win_layout)

                                if facility_id not in profile_changes:
                                    profile_changes.append(facility_id)
                                asdex_to_saids.append({
                                    "profile": profile_name,
                                    "facility": facility_id
                                })
                                profile_modified = True

            if profile_modified:
                all_modified_profiles[profile_name] = profile_changes
                json_string = json.dumps(profile, indent=2, ensure_ascii=False)
                json_string = re.sub(r'\[\s*\n\s*\]', '[]', json_string)

                try:
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(json_string)
                except Exception as e:
                    pass

        if all_modified_profiles:
            max_mod_len = max(len(name) for name in all_modified_profiles.keys())
            print("\n  >>> SAID replacements complete:")
            for prof_name, changes in all_modified_profiles.items():
                print(f"      {prof_name:<{max_mod_len + 2}}{changes}")
            print("  [+] Status: Successfully updated all matching profiles.")
        else:
            print("  [+] Status: Process finished, but no configurations required actual updates.")

else:
    print(f"\n  [-] Error: Could not open profiles directory: {profiles_dir}")

# ==============================================================================
# EXIT COUNTDOWN TIMEOUT
# ==============================================================================
print()
for remaining in range(15, 0, -1):
    sys.stdout.write(f"\r  Closing in {remaining} seconds...")
    sys.stdout.flush()
    time.sleep(1)
print("\r  Done.                                                         ")