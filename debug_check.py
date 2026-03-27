# debug_check.py
source = open('data/cache/raw_data/data_raw.lua', encoding='utf-8').read()
import re

# Trouver des -- dans des strings
matches = re.findall(r'"[^"]*--[^"]*"', source)
print(f'Strings contenant -- : {len(matches)}')
for m in matches[:10]:
    print(repr(m))