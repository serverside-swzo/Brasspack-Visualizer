

import argparse
import asyncio
import re
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

try:
    import aiofiles
except Exception:
    aiofiles = None

try:
    from rich.console import Console
    from rich.table import Table

    RICH_AVAILABLE = True
    console = Console()
except Exception:
    RICH_AVAILABLE = False
    console = None

try:
    import nbtlib
except Exception:
    nbtlib = None

RE_PLAYERNAME = re.compile(r'playerName\s*:\s*(?:"([^"]+)"|([A-Za-z0-9_\-]+))', re.IGNORECASE)
RE_BACKPACK_UUID_INTS = re.compile(r'backpackUuid\s*:\s*ints\(\s*([-\d,\s]+)\s*\)', re.IGNORECASE)
RE_ACCESS_TIME = re.compile(r'accessTime\s*:\s*([0-9]+)L?', re.IGNORECASE)
RE_ITEM_ID = re.compile(r'id\s*:\s*(?:"([^"]+)"|([A-Za-z0-9:_\-\.]+))')

def pattern_for_item(item_id):
    esc = re.escape(item_id)
    return re.compile(r'id\s*:\s*(?:"' + esc + r'"|' + esc + r')', re.IGNORECASE)

def pattern_for_upgrade(upgrade_id):
    esc = re.escape(upgrade_id)
    return re.compile(r'id\s*:\s*(?:"' + esc + r'"|' + esc + r')', re.IGNORECASE)

def format_timestamp_ms(ms_value: int, tz_name: str = "Europe/Berlin"):
    try:
        dt = datetime.fromtimestamp(int(ms_value) / 1000, tz=timezone.utc).astimezone(ZoneInfo(tz_name))
        return dt.isoformat()
    except Exception:
        return str(ms_value)

def uuid_from_int_list(ints):
    """
    ints: sequence of 4 ints (signed 32-bit). Returns UUID string like xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
    """
    if not ints:
        return None

    try:
        parts = [int(x) for x in ints]
    except:
        return None

    if len(parts) != 4:
        return None

    parts = [(x & 0xFFFFFFFF) for x in parts]
    high = (parts[0] << 32) | parts[1]
    low = (parts[2] << 32) | parts[3]

    combined = (high << 64) | low
    hex32 = f"{combined:032x}"

    return f"{hex32[0:8]}-{hex32[8:12]}-{hex32[12:16]}-{hex32[16:20]}-{hex32[20:32]}"

def simple_table(rows, columns, title=None):
    if RICH_AVAILABLE:
        table = Table(title=title)
        for col in columns:
            table.add_column(col, overflow="fold")
        for r in rows:
            table.add_row(*[str(r.get(col, "")) for col in columns])
        console.print(table)
    else:
        if title:
            print(f"=== {title} ===")
        if not rows:
            print("(no results)")
            return
        widths = [max(len(col), *(len(str(r.get(col, ""))) for r in rows)) for col in columns]
        fmt = "  ".join("{:" + str(w) + "}" for w in widths)
        print(fmt.format(*columns))
        print("-" * (sum(widths) + 2 * (len(widths) - 1)))
        for r in rows:
            print(fmt.format(*[str(r.get(c, "")) for c in columns]))

RE_BACKPACK_CONTENTS_START = re.compile(r'\bbackpackContents\s*:\s*\[')

async def scan_text_snbt_file(path, on_backpack_block):
    if aiofiles is None:
        raise RuntimeError("aiofiles is required for async text scanning. Install with 'pip install aiofiles'")
    collecting = False
    brace_level = 0
    buffer_lines = []
    async with aiofiles.open(path, 'r', encoding='utf-8', errors='ignore') as f:
        async for raw_line in f:
            line = raw_line.rstrip('\n')
            if not collecting:
                if RE_BACKPACK_CONTENTS_START.search(line) or '"":' in line or 'backpackContents' in line:
                    collecting = True
                    buffer_lines = [line]
                    brace_level = line.count('{') - line.count('}')
                    continue
            else:
                buffer_lines.append(line)
                brace_level += line.count('{') - line.count('}')
                if brace_level <= 0:
                    block_text = "\n".join(buffer_lines)
                    try:
                        await on_backpack_block(block_text)
                    except Exception:
                        pass
                    collecting = False
                    brace_level = 0
                    buffer_lines = []
    if collecting and buffer_lines:
        await on_backpack_block("\n".join(buffer_lines))

def extract_owner_from_block(block: str):
    m = RE_PLAYERNAME.search(block)
    pname = m.group(1) or m.group(2) if m else None
    m3 = RE_BACKPACK_UUID_INTS.search(block)
    uuid_text = None
    if m3:
        uuid_text = uuid_from_int_list([int(p.strip()) for p in m3.group(1).split(',') if p.strip()])
    m4 = RE_ACCESS_TIME.search(block)
    access_ts = int(m4.group(1)) if m4 else None
    return dict(playerName=pname, backpackUuid=uuid_text, accessTime=access_ts)

def summary_inventory_from_block(block: str, max_items=8):
    items = []
    for match in RE_ITEM_ID.finditer(block):
        item = match.group(1) or match.group(2)
        start = max(0, match.start() - 120)
        snippet = block[start: match.end() + 20]
        mcount = re.search(r'count\s*:\s*([0-9]+)', snippet)
        count = int(mcount.group(1)) if mcount else None
        items.append((item, count))
        if len(items) >= max_items:
            break
    return items

def safe_get(obj, key, default=None):
    try:
        return obj.get(key, default)
    except Exception:
        try:
            return obj[key]
        except Exception:
            return default

def iter_nbt_list(lst):

    try:
        for x in lst:
            yield x
    except:
        return []

def normalize_to_py(x):
    """
    Convert nbtlib objects to plain python types (dict/list/str/int) recursively
    only when needed to check keys/values easily.
    """
    try:
        if hasattr(x, 'keys') and hasattr(x, 'items'):

            return {k: normalize_to_py(v) for k, v in x.items()}
        elif isinstance(x, (list, tuple)) or (hasattr(x, '__iter__') and not isinstance(x, (str, bytes, bytearray))):

            return [normalize_to_py(i) for i in x]
        elif hasattr(x, '__int__'):
            return int(x)
        elif hasattr(x, '__float__'):
            return float(x)
        elif hasattr(x, '__str__'):
            return str(x)
        return x
    except Exception:
        return x

def build_owner_index_from_access_log(access_log):
    """
    Returns dict mapping uuid_string -> owner_record
    """
    idx = {}
    if not access_log:
        return idx
    for rec in iter_nbt_list(access_log):
        try:

            ints_val = safe_get(rec, 'backpackUuid') or safe_get(rec, 'uuid')
            uuid_str = uuid_from_int_list(ints_val)

            pname = safe_get(rec, 'playerName') or safe_get(rec, 'player')
            access_time = safe_get(rec, 'accessTime') or safe_get(rec, 'lastAccess')

            if uuid_str:
                idx[uuid_str] = {
                    "playerName": str(pname) if pname else "",
                    "accessTime": int(access_time) if access_time else None
                }
        except Exception:
            continue
    return idx

def find_items_in_inventory(inv):
    """
    inv is the 'inventory' compound
    """
    items_found = []
    try:
        items = safe_get(inv, 'Items', [])
        for it in iter_nbt_list(items):
            try:
                iid = str(safe_get(it, 'id') or safe_get(it, 'Name') or "").lower()
                cnt = int(safe_get(it, 'count') or safe_get(it, 'Count') or 1)
                if iid:
                    items_found.append((iid, cnt))
            except Exception:
                continue
    except Exception:
        pass
    return items_found

def search_binary_nbt(path, mode, query, tz="Europe/Berlin"):
    if nbtlib is None:
        raise RuntimeError("nbtlib is required to read binary NBT files. Install with 'pip install nbtlib'")

    doc = nbtlib.load(path)
    results = []

    data_payload = None

    search_queue = [(doc, "root")]

    for _ in range(3):
        next_layer = []
        for node, desc in search_queue:
            if hasattr(node, 'get'):
                if 'backpackContents' in node:
                    data_payload = node
                    break
                if 'data' in node:

                    d = node['data']
                    if hasattr(d, 'get') and 'backpackContents' in d:
                        data_payload = d
                        break
                    next_layer.append((d, desc + ".data"))

                if hasattr(node, 'keys'):
                    for k in node.keys():
                        if k not in ['data']:
                            next_layer.append((node[k], f"{desc}.{k}"))

        if data_payload:
            break
        search_queue = next_layer

    if not data_payload:
        print("Warning: Could not locate 'backpackContents' in NBT structure.", file=sys.stderr)
        return []

    access_log = safe_get(data_payload, 'accessLogRecords', [])
    contents_list = safe_get(data_payload, 'backpackContents', [])

    owner_index = build_owner_index_from_access_log(access_log)

    for bc in iter_nbt_list(contents_list):
        try:

            uuid_ints = safe_get(bc, 'uuid') or safe_get(bc, 'backpackUuid')
            backpack_uuid = uuid_from_int_list(uuid_ints)

            contents = safe_get(bc, 'contents') or {}

            inv_items = find_items_in_inventory(safe_get(contents, 'inventory', {}))
            up_items = find_items_in_inventory(safe_get(contents, 'upgradeInventory', {}))

            owner_rec = owner_index.get(backpack_uuid) or {}
            player_name = owner_rec.get('playerName', "")
            access_time = owner_rec.get('accessTime')

            registry_name = ""

            if mode == 'owner':
                q_lower = query.lower()
                if backpack_uuid and (query.lower() == backpack_uuid.lower() or q_lower in player_name.lower()):
                    results.append({
                        "playerName": player_name,
                        "backpackUuid": backpack_uuid,
                        "registry": registry_name,
                        "accessTime": format_timestamp_ms(access_time, tz) if access_time else ""
                    })

            elif mode == 'item':
                q_lower = query.lower()
                matched = False
                found_summary = []

                for iid, cnt in inv_items:
                    if q_lower in iid:
                        matched = True
                    if matched or len(found_summary) < 5:
                        found_summary.append(f"{iid} x{cnt}")

                for iid, cnt in up_items:
                    if q_lower in iid:
                        matched = True
                    if matched or len(found_summary) < 5:
                        found_summary.append(f"[Up] {iid} x{cnt}")

                if matched:
                    results.append({
                        "playerName": player_name,
                        "backpackUuid": backpack_uuid,
                        "registry": registry_name,
                        "accessTime": format_timestamp_ms(access_time, tz) if access_time else "",
                        "items_found": ", ".join(found_summary[:10])
                    })

            elif mode == 'upgrade':
                q_lower = query.lower()
                matched = False
                for iid, cnt in up_items:
                    if q_lower in iid:
                        matched = True
                        break
                if matched:
                    results.append({
                        "playerName": player_name,
                        "backpackUuid": backpack_uuid,
                        "registry": registry_name,
                        "accessTime": format_timestamp_ms(access_time, tz) if access_time else ""
                    })

        except Exception:
            continue

    return results

def looks_binary(path, read_bytes=4096):
    try:
        with open(path, 'rb') as f:
            head = f.read(read_bytes)
            if b'\x00' in head:
                return True
            if head.startswith(b'\x0a') or head.startswith(b'\x1f\x8b'):
                return True
    except Exception:
        pass
    return False

async def search_text_file_by_owner(path, owner_query, tz="Europe/Berlin"):
    rows = []
    owner_query_lower = owner_query.lower()

    async def on_block(block):
        info = extract_owner_from_block(block)
        name = info.get("playerName") or ""
        if name and owner_query_lower in name.lower():
            items = summary_inventory_from_block(block, max_items=10)
            rows.append({
                "playerName": name,
                "backpackUuid": info.get("backpackUuid"),
                "registry": info.get("registry"),
                "accessTime": format_timestamp_ms(info["accessTime"], tz) if info.get("accessTime") else "",
                "items": ", ".join(f"{it[0]} x{it[1] if it[1] is not None else '?'}" for it in items)
            })

    await scan_text_snbt_file(path, on_block)
    return rows

async def search_text_file_by_item(path, item_query, tz="Europe/Berlin"):
    rows = []
    patt = pattern_for_item(item_query)

    async def on_block(block):
        if patt.search(block):
            info = extract_owner_from_block(block)
            items = summary_inventory_from_block(block, max_items=20)
            rows.append({
                "playerName": info.get("playerName") or "",
                "backpackUuid": info.get("backpackUuid"),
                "registry": info.get("registry"),
                "accessTime": format_timestamp_ms(info["accessTime"], tz) if info.get("accessTime") else "",
                "items_found": ", ".join(f"{it[0]} x{it[1] if it[1] is not None else '?'}" for it in items)
            })

    await scan_text_snbt_file(path, on_block)
    return rows

async def search_text_file_by_upgrade(path, upgrade_query, tz="Europe/Berlin"):
    rows = []
    patt = pattern_for_upgrade(upgrade_query)

    async def on_block(block):
        if 'upgradeInventory' in block and patt.search(block):
            info = extract_owner_from_block(block)
            rows.append({
                "playerName": info.get("playerName") or "",
                "backpackUuid": info.get("backpackUuid"),
                "registry": info.get("registry"),
                "accessTime": format_timestamp_ms(info["accessTime"], tz) if info.get("accessTime") else ""
            })

    await scan_text_snbt_file(path, on_block)
    return rows

async def main_async(args):
    path = args.file
    tz = "Europe/Berlin"
    q = args.query
    mode = args.mode

    if looks_binary(path):
        try:
            rows = search_binary_nbt(path, mode, q, tz)
            if mode == 'owner':
                simple_table(rows, ["playerName", "backpackUuid", "registry", "accessTime"],
                             title=f"Backpacks for owner '{q}' (binary nbt)")
            elif mode == 'item':
                simple_table(rows, ["playerName", "backpackUuid", "registry", "accessTime", "items_found"],
                             title=f"Backpacks containing '{q}' (binary nbt)")
            elif mode == 'upgrade':
                simple_table(rows, ["playerName", "backpackUuid", "registry", "accessTime"],
                             title=f"Backpacks with upgrade '{q}' (binary nbt)")
            return
        except Exception as e:
            print("Binary NBT handling failed (falling back to text scan):", e, file=sys.stderr)
            import traceback
            traceback.print_exc()

    if mode == 'owner':
        rows = await search_text_file_by_owner(path, q, tz)
        simple_table(rows, ["playerName", "backpackUuid", "registry", "accessTime", "items"],
                     title=f"Backpacks for owner '{q}' (text scan)")
    elif mode == 'item':
        rows = await search_text_file_by_item(path, q, tz)
        simple_table(rows, ["playerName", "backpackUuid", "registry", "accessTime", "items_found"],
                     title=f"Backpacks containing '{q}' (text scan)")
    elif mode == 'upgrade':
        rows = await search_text_file_by_upgrade(path, q, tz)
        simple_table(rows, ["playerName", "backpackUuid", "registry", "accessTime"],
                     title=f"Backpacks with upgrade '{q}' (text scan)")
    else:
        print("unknown mode")

def parse_cli():
    p = argparse.ArgumentParser(description="Search sophisticatedbackpacks .dat files")
    p.add_argument("--file", "-f", required=True, help="Path to backpacks.dat")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--owner", action="store_true", help="Search by owner name or uuid")
    group.add_argument("--item", action="store_true", help="Search for item id (mod:item)")
    group.add_argument("--upgrade", action="store_true", help="Search for upgrade id (mod:upgrade_name)")
    p.add_argument("query", nargs=1, help="Query string (owner name/uuid or item id or upgrade id)")
    return p.parse_args()

def main():
    args_raw = parse_cli()
    if args_raw.owner:
        mode = 'owner'
    elif args_raw.item:
        mode = 'item'
    elif args_raw.upgrade:
        mode = 'upgrade'
    else:
        mode = None

    class Args:
        pass

    args = Args()
    args.file = args_raw.file
    args.mode = mode
    args.query = args_raw.query[0]
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)

if __name__ == "__main__":
    main()