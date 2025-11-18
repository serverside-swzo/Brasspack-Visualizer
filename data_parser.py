import sys
from datetime import datetime

import nbtlib

# Assume infiltrator.py is available
try:
    import infiltrator
except ImportError:
    print("Error: 'infiltrator.py' not found in the current directory.")
    sys.exit(1)

def format_short_date(timestamp_ms):
    """Formats a raw millisecond timestamp into a human-readable string."""
    if not timestamp_ms: return "Never"
    try:
        dt = datetime.fromtimestamp(timestamp_ms / 1000)
        return dt.strftime("%y-%m-%d %H:%M")
    except:
        return "Invalid"

def format_count(count):
    """Formats large item counts (e.g., 120000 -> 120k)."""
    if count < 10000: return str(count)
    n = float(count)
    for suffix in ['k', 'M', 'B', 'T']:
        n /= 1000.0
        if n < 1000:
            return f"{int(n)}{suffix}" if n >= 10 else f"{n:.1f}".replace('.0', '') + suffix
    return "INF"

def parse_all_backpacks(file_path):
    """
    Reads the Sophisticated Backpacks NBT file and yields normalized backpack data.
    This logic has been moved from the original main file.
    """
    print(f"[Parser] Reading NBT file: {file_path}...")
    try:
        doc = nbtlib.load(file_path)
    except Exception as e:
        print(f"Fatal Error reading NBT: {e}")
        return

    # Deep search for the main data payload (containing backpackContents)
    data_payload = None
    search_queue = [(doc, "root")]
    for _ in range(3):
        next_layer = []
        for node, desc in search_queue:
            if hasattr(node, 'get'):
                if 'backpackContents' in node:
                    data_payload = node;
                    break
                if 'data' in node:
                    d = node['data']
                    if hasattr(d, 'get') and 'backpackContents' in d:
                        data_payload = d;
                        break
                    next_layer.append((d, desc + ".data"))
                if hasattr(node, 'keys'):
                    for k in node.keys():
                        if k != 'data': next_layer.append((node[k], f"{desc}.{k}"))
        if data_payload: break
        search_queue = next_layer

    if not data_payload:
        print("[Parser] Error: Could not locate 'backpackContents' in the NBT structure.")
        return

    access_log = infiltrator.safe_get(data_payload, 'accessLogRecords', [])
    contents_list = infiltrator.safe_get(data_payload, 'backpackContents', [])
    owner_index = infiltrator.build_owner_index_from_access_log(access_log)

    print(f"[Parser] Found {len(contents_list)} raw backpack entries.")

    for bc in infiltrator.iter_nbt_list(contents_list):
        try:
            uuid_ints = infiltrator.safe_get(bc, 'uuid') or infiltrator.safe_get(bc, 'backpackUuid')
            uuid = infiltrator.uuid_from_int_list(uuid_ints)
            if not uuid: continue

            contents = infiltrator.safe_get(bc, 'contents') or {}
            inv_tag = infiltrator.safe_get(contents, 'inventory', {})
            items = infiltrator.safe_get(inv_tag, 'Items', [])
            inv_map = {}
            for i, it in enumerate(infiltrator.iter_nbt_list(items)):
                iid = str(infiltrator.safe_get(it, 'id') or "").lower().replace('"', '').strip()
                cnt = int(infiltrator.safe_get(it, 'count') or 1)
                slot = int(infiltrator.safe_get(it, 'Slot') if infiltrator.safe_get(it, 'Slot') is not None else i)
                if iid and "air" not in iid:
                    inv_map[slot] = {'id': iid, 'count': cnt}

            upg_tag = infiltrator.safe_get(contents, 'upgradeInventory', {})
            upgs = infiltrator.safe_get(upg_tag, 'Items', [])
            upg_list = []
            for it in infiltrator.iter_nbt_list(upgs):
                iid = str(infiltrator.safe_get(it, 'id') or "").lower().replace('"', '').strip()
                cnt = int(infiltrator.safe_get(it, 'count') or 1)
                if iid: upg_list.append((iid, cnt))

            rec = owner_index.get(uuid, {})
            yield {
                'type': 'backpack',
                'backpackUuid': uuid,
                'playerName': rec.get('playerName', "Unknown"),
                'accessTimeRaw': rec.get('accessTime'),
                'inventory': inv_map,
                'upgrades': upg_list,
                'id': 'sophisticatedbackpacks:backpack'
            }
        except Exception as e:
            # print(f"Skipping malformed backpack entry: {e}")
            continue