import json, os
crc_profiles = os.getenv('LOCALAPPDATA') + R'\CRC\Profiles'

for file in os.listdir(crc_profiles):
    if '.json' not in file or file[3] != '2':
        continue
        
    f = os.path.join(crc_profiles, file)
    data = {}
    with open(f) as json_file:
        data = json.load(json_file)
        
        dws = data['DisplayWindowSettings']
        
        if len(dws) == 2:
            dws.pop(0)
        
        bounds = dws[0]['WindowSettings']['Bounds']
        dws[0]['WindowSettings']['Bounds'] = bounds.replace('3840,550', '0,0')

        data['Name'] = data['Name'].replace('2)', '1)')
        
    with open(f, 'w', encoding='utf-8') as json_file:
        json.dump(data, json_file, ensure_ascii=False, indent=4)