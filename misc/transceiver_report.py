import sys
import json
import urllib.request
import urllib.error
import time
from pathlib import Path

# Global formatting widths
MAX_CALLSIGN_LENGTH = 10  # Hard-capped to exactly 10 characters
MAX_TX_LENGTH = 23        # Hard-capped to exactly 23 characters

def fetch_facility_data(facility_id):
    """Fetches the ARTCC JSON data using Python's built-in urllib module with a User-Agent."""
    url = f"https://data-api.vnas.vatsim.net/api/artccs/{facility_id}"
    
    # Adding a standard User-Agent header to bypass 403 Forbidden restrictions
    req = urllib.request.Request(
        url, 
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode())
    except urllib.error.URLError as e:
        print(f"Error fetching data from API: {e}")
        sys.exit(1)

def get_prefix_and_suffix(callsign):
    """Extracts the prefix and suffix from a callsign, grouping interchangeable suffixes."""
    if "_" in callsign:
        parts = callsign.split("_")
        prefix = parts[0]
        suffix = "_" + parts[-1]
        
        # Define the interchangeable suffix groups
        ctr_group = {"_CTR", "_FSS", "_TMU"}
        app_group = {"_APP", "_DEP"}
        twr_group = {"_TWR", "_GND", "_DEL", "_RMP"}
        
        # Normalize the suffix based on its group family
        if suffix in ctr_group:
            suffix = "_CTR_FAMILY"
        elif suffix in app_group:
            suffix = "_APP_FAMILY"
        elif suffix in twr_group:
            suffix = "_TWR_FAMILY"
            
        return prefix, suffix
    return callsign, ""

def pre_process_positions(facility_node, footprint_map, affix_map):
    """Recursively parses all positions to group them by transceiver footprint."""
    if not facility_node:
        return
    
    positions = facility_node.get("positions", [])
    for position in positions:
        raw_callsign = position.get("callsign")
        if raw_callsign:
            callsign = raw_callsign[:MAX_CALLSIGN_LENGTH]
                
            tx_ids = sorted(position.get("transceiverIds", []))
            footprint_key = tuple(tx_ids)
            
            if footprint_key not in footprint_map:
                footprint_map[footprint_key] = []
            footprint_map[footprint_key].append(callsign)
            
            affix_key = get_prefix_and_suffix(callsign)
            if affix_key not in affix_map:
                affix_map[affix_key] = []
            affix_map[affix_key].append(callsign)
            
    child_facilities = facility_node.get("childFacilities", [])
    for child in child_facilities:
        pre_process_positions(child, footprint_map, affix_map)

def format_transceiver_columns(char_tag, tx_names):
    """Formats transceivers into a 3-column string layout."""
    lines = []
    prefix = f"  {char_tag}  "
    indent_spaces = " " * len(prefix)
    col_width = MAX_TX_LENGTH + 3
    
    if not tx_names:
        return f"{prefix}None\n"

    for i in range(0, len(tx_names), 3):
        row_items = tx_names[i:i+3]
        row_str = prefix if i == 0 else indent_spaces
        
        for idx, name in enumerate(row_items):
            truncated_name = name[:MAX_TX_LENGTH]
            if idx < len(row_items) - 1:
                row_str += f"{truncated_name:<{col_width}}"
            else:
                row_str += truncated_name
        lines.append(row_str)
    return "\n".join(lines) + "\n"

def format_position_columns(char_tag, callsigns):
    """Formats callsigns into a 6-column grid string layout syncing with the transceivers."""
    lines = []
    prefix = f"  {char_tag}  "
    indent_spaces = " " * len(prefix)
    
    if not callsigns:
        return f"{prefix}None\n"

    num_cols = 6

    for i in range(0, len(callsigns), num_cols):
        row_items = callsigns[i:i+num_cols]
        row_str = prefix if i == 0 else indent_spaces
        
        for idx, name in enumerate(row_items):
            if idx == len(row_items) - 1:
                row_str += name
            else:
                col_width = 13
                row_str += f"{name:<{col_width}}"
        lines.append(row_str)
    return "\n".join(lines) + "\n"

def build_report_string(facility_node, transceivers_map, footprint_map, affix_map):
    """Recursively processes facilities and compiles the report string."""
    output = ""
    if not facility_node:
        return output
    
    positions = facility_node.get("positions", [])
    for position in positions:
        raw_callsign = position.get("callsign")
        position_name = position.get("name")
        
        if raw_callsign:
            callsign = raw_callsign[:MAX_CALLSIGN_LENGTH]
            output += f"{callsign} - {position_name}\n"
            
            tx_ids = position.get("transceiverIds", [])
            tx_names = sorted([transceivers_map.get(tx_id) for tx_id in tx_ids if transceivers_map.get(tx_id)])
            
            output += format_transceiver_columns("T", tx_names)
            
            footprint_key = tuple(sorted(tx_ids))
            matching_callsigns = sorted([c for c in footprint_map.get(footprint_key, []) if c != callsign])
            output += format_position_columns("M", matching_callsigns)
            
            affix_key = get_prefix_and_suffix(callsign)
            non_matching_callsigns = []
            
            same_affix_positions = affix_map.get(affix_key, [])
            for companion in same_affix_positions:
                if companion != callsign and companion not in matching_callsigns:
                    non_matching_callsigns.append(companion)
            
            non_matching_callsigns.sort()
            output += format_position_columns("X", non_matching_callsigns)
            output += "\n"

    child_facilities = facility_node.get("childFacilities", [])
    for child in child_facilities:
        output += build_report_string(child, transceivers_map, footprint_map, affix_map)
        
    return output

def main():
    valid_facilities = {
        "ZAB", "ZMA", "ZOA", "ZHU", "ZDV", "ZID", "ZLA", "ZME", "ZMP", "ZFW", 
        "ZAN", "ZUA", "ZJX", "ZSE", "ZNY", "ZAU", "ZDC", "ZLC", "ZOB", "ZTL", 
        "ZSU", "ZHN", "ZKC", "ZBW"
    }
    
    print("################################################################################")
    print("#                               TRANSCEIVER REPORT                             #")
    print("################################################################################")
    print("This script checks the transceiver setups for all positions in an ARTCC.")
    print("  * TRANSCEIVERS        T       Lists all transceivers assigned to the position.")
    print("  * MATCHING            M       Lists positions with the same transceivers.")
    print("  * NOT MATCHING        X       Lists positions with the same facility type but")
    print("                                different transceivers assigned.")
    print()
    
    attempts = 0
    facility_name = ""
    
    while attempts < 3:
        user_input = input("Input ARTCC:      ").strip().upper()
        if user_input in valid_facilities:
            facility_name = user_input
            break
        else:
            attempts += 1
            if attempts < 3:
                print(f"Invalid facility name. Please try again ({3 - attempts} attempts remaining).\n")
            else:
                print("Invalid facility name. Third try failed. Exiting script.")
                sys.exit(0)
                
    print(f"\nFetching data for {facility_name}...")
    data = fetch_facility_data(facility_name)
    
    transceivers_list = data.get("transceivers", [])
    transceivers_map = {tx.get("id"): tx.get("name") for tx in transceivers_list if tx.get("id")}
    
    root_facility = data.get("facility")
    
    footprint_map = {}
    affix_map = {}
    pre_process_positions(root_facility, footprint_map, affix_map)
    
    report_title = f"{facility_name} TRANSCEIVER REPORT"
    report_banner = f"# {report_title:^76} #"
    
    # Construct total output body
    full_report_text = "################################################################################\n"
    full_report_text += f"{report_banner}\n"
    full_report_text += "################################################################################\n\n"
    full_report_text += build_report_string(root_facility, transceivers_map, footprint_map, affix_map)
    
    # 1. Print the entire generated report straight to the live terminal stream
    print()
    print(full_report_text, end="")
    
    # 2. Save file cleanly to the local system Downloads folder framework
    downloads_path = Path.home() / "Downloads"
    file_name = f"{facility_name.lower()}_transceiver_report.txt"
    destination_file = downloads_path / file_name
    
    with open(destination_file, "w", encoding="utf-8") as file:
        file.write(full_report_text)
        
    # 3. Dynamic destination output with one trailing blank line and footer summary frame
    print("################################################################################")
    print(f"Saved '{file_name}' to '{downloads_path}'")
    print()
    
    # Live updating countdown sequence using carriage return '\r'
    for remaining in range(60, 0, -1):
        print(f"\rExiting script in {remaining:02d} seconds...", end="", flush=True)
        time.sleep(1)
        
    # Clean fallback transition text as it shuts down
    print("\rExiting script now...                       ")

if __name__ == "__main__":
    main()