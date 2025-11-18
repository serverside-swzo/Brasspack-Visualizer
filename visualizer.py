import argparse
import asyncio
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import data_parser
# Import the new modules
import image_generator

# Assume infiltrator is available from the environment
try:
    import infiltrator
except ImportError:
    print("Error: 'infiltrator.py' not found.")
    sys.exit(1)

# Import container specific logic if needed
try:
    import container_infiltrator
except ImportError:
    # This is fine if the user only uses .dat files
    container_infiltrator = None


def matches_filter(data, args):
    """Checks if the data item matches the provided CLI filters."""

    # Container Specifics
    if data.get('type') == 'container':
        if getattr(args, 'nodungeon', False) and data.get('is_dungeon'):
            return False
        if getattr(args, 'container_type', None):
            if args.container_type.lower() not in data.get('id', '').lower():
                return False
        if getattr(args, 'nbt', None):
            # Loose nbt check (converted to string)
            if args.nbt not in json.dumps(data):
                return False

    # Inventory Item Check (Applies to both)
    if args.item:
        q = args.item.lower()
        found = False
        for item in data.get('inventory', {}).values():
            if q in item.get('id', '').lower():
                found = True
                break
        if not found: return False

    # Owner Check (Backpack only)
    if args.owner:
        q = args.owner.lower()
        pname = data.get('playerName', '').lower()
        puuid = data.get('backpackUuid', '').lower()
        if q not in pname and q not in puuid:
            return False

    # Upgrade Check (Backpack only)
    if args.upgrade:
        q = args.upgrade.lower()
        found = False
        for u_id, _ in data.get('upgrades', []):
            if q in u_id.lower():
                found = True
                break
        if not found: return False

    # Legacy Positional Query (for backward compatibility)
    if args.query:
        q = args.query.lower()
        found_any = False
        if q in data.get('playerName', '').lower(): found_any = True
        if q in data.get('backpackUuid', '').lower(): found_any = True

        if not found_any:
            for item in data.get('inventory', {}).values():
                if q in item.get('id', '').lower():
                    found_any = True;
                    break

        if not found_any:
            for u_id, _ in data.get('upgrades', []):
                if q in u_id.lower():
                    found_any = True;
                    break

        if not found_any: return False

    return True


async def main():
    p = argparse.ArgumentParser(description="Backpack & Container Visualizer")
    p.add_argument("-f", "--file", required=True, help="Path to .dat or .json file")

    p.add_argument("--mode", choices=['backpack', 'container'], default='backpack',
                   help="Explicitly set processing mode")

    # Filters
    p.add_argument("--owner", help="Filter by Owner Name/UUID (Backpacks)")
    p.add_argument("--item", help="Filter by Item ID (Both)")
    p.add_argument("--upgrade", help="Filter by Upgrade ID (Backpacks)")
    p.add_argument("--nodungeon", action="store_true", help="Exclude dungeons (Containers)")
    p.add_argument("--ctype", "--container-type", dest="container_type", help="Filter by Container ID (Containers)")
    p.add_argument("--nbt", help="Filter by NBT string (Containers)")

    # Legacy positional argument
    p.add_argument("query", nargs="?", help="General query string (Owner, Item, or Upgrade)")

    args = p.parse_args()

    # Auto-detect mode based on file extension if mode wasn't set explicitly
    if args.file.endswith('.json') and args.mode == 'backpack':
        args.mode = 'container'
        print("[Main] Detected '.json' extension, switching mode to 'container'.")
    elif args.file.endswith('.dat') and args.mode == 'container':
        args.mode = 'backpack'
        print("[Main] Detected '.dat' extension, switching mode to 'backpack'.")

    # Load image and font resources
    print("\n" + "=" * 50)
    image_generator.load_resources()
    print("=" * 50 + "\n")

    items_to_process = []

    if args.mode == 'container':
        if not container_infiltrator:
            print("[ERROR] Container mode requires 'container_infiltrator.py' which is not available.")
            return

        print(f"[Main] Reading container data from: {args.file}...")
        raw_containers = container_infiltrator.load_containers(args.file)

        for c in raw_containers:
            # Normalize and format the container data for the visualizer
            norm = container_infiltrator.normalize_container(c)
            inv_dict = {}
            for item in norm.get('inventory', []):
                inv_dict[item.get('Slot')] = item
            norm['inventory'] = inv_dict  # Convert list of items to slot map

            if matches_filter(norm, args):
                items_to_process.append(norm)
    else:
        print(f"[Main] Reading NBT backpack data from: {args.file}...")
        for bp in data_parser.parse_all_backpacks(args.file):
            if matches_filter(bp, args):
                items_to_process.append(bp)

    count = len(items_to_process)
    print(f"[Main] Found {count} items matching filters.")
    if count == 0: return

    if count > 50:
        if input(f"Generate {count} images? [y/N] ").lower() != 'y': return

    print("Generating images...")
    loop = asyncio.get_running_loop()

    # Use ThreadPoolExecutor for CPU-bound PIL operations
    with ThreadPoolExecutor(max_workers=os.cpu_count() + 2) as ex:
        tasks = []
        for item in items_to_process:
            # Pass data and a default icon ID (None means use data['id'])
            tasks.append(loop.run_in_executor(ex, image_generator.save_img, item, None))

        completed = 0
        total = len(tasks)
        bar_len = 30

        print(f"Progress: 0/{total} (0%)", end="\r")
        for f in asyncio.as_completed(tasks):
            await f
            completed += 1

            # Progress Bar Logic
            percent = int((completed / total) * 100)
            filled = int(bar_len * completed / total)
            bar = "=" * filled + "-" * (bar_len - filled)
            print(f"\r[{bar}] {percent}% ({completed}/{total})", end="")
            sys.stdout.flush()

    print(f"\n[Done] Images saved to {os.path.abspath(image_generator.OUTPUT_DIR)}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProcess interrupted.")