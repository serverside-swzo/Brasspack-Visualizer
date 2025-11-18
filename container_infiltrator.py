import json


def load_containers(filepath):
    """Loads the container data from a JSON file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading JSON: {e}")
        return []


def matches_filter(container, args):
    """
    Checks if a container matches the combined arguments.
    """
    if getattr(args, 'nodungeon', False) and container.get('is_dungeon', False):
        return False

    if getattr(args, 'container_type', None):
        if args.container_type.lower() not in container.get('id', '').lower():
            return False

    items_raw = container.get('items', [])

    # Normalize raw items to a list of values for searching
    if isinstance(items_raw, dict):
        items_list = list(items_raw.values())
    elif isinstance(items_raw, list):
        items_list = items_raw
    else:
        items_list = []

    if getattr(args, 'item', None):
        found_item = False
        target_item = args.item.lower()
        for slot_data in items_list:
            if not isinstance(slot_data, dict): continue
            if target_item in slot_data.get('id', '').lower():
                found_item = True
                break
        if not found_item:
            return False

    if getattr(args, 'nbt', None):
        # Search within the raw string dump of items
        items_str = json.dumps(items_raw)
        if args.nbt not in items_str:
            return False

    return True


def normalize_container(c):
    """
    Converts a raw container dict into the standardized format.
    Handles both List and Dict formats for 'items'.
    """
    inventory_list = []
    raw_items = c.get('items', [])

    # Helper to fix keys like 'count' -> 'Count'
    def process_item(item_dict, slot_val):
        item_copy = item_dict.copy()

        # Ensure Slot exists
        if 'Slot' not in item_copy:
            item_copy['Slot'] = int(slot_val)
        else:
            item_copy['Slot'] = int(item_copy['Slot'])

        # Normalize Count
        if 'count' in item_copy:
            item_copy['Count'] = item_copy['count']
        elif 'Count' not in item_copy:
            item_copy['Count'] = 1

        # Normalize Tag/NBT
        if 'tag' not in item_copy and 'nbt' in item_copy:
            item_copy['tag'] = item_copy['nbt']

        return item_copy

    # CASE A: Items is a Dictionary {"0": {id...}, "1": {id...}}
    if isinstance(raw_items, dict):
        for slot_idx, item_data in raw_items.items():
            inventory_list.append(process_item(item_data, slot_idx))

    # CASE B: Items is a List [{Slot:0, id...}, {Slot:2, id...}]
    elif isinstance(raw_items, list):
        for i, item_data in enumerate(raw_items):
            if not isinstance(item_data, dict): continue
            # If 'Slot' key exists in the item, use it, otherwise use list index
            slot_ref = item_data.get('Slot', i)
            inventory_list.append(process_item(item_data, slot_ref))

    # Determine grid size
    max_slot = 0
    if inventory_list:
        max_slot = max(i['Slot'] for i in inventory_list)

    cols = 9
    rows = (max_slot // cols) + 1
    # Removed the limitation of 3 minimum rows here.
    # Visualizer now handles calculation, but we provide raw data correctly.
    if rows > 9: rows = 9

    return {
        'type': 'container',
        'id': c.get('id', 'minecraft:chest'),
        'x': c.get('x', '?'),
        'y': c.get('y', '?'),
        'z': c.get('z', '?'),
        'dimension': c.get('dimension', 'Unknown'),
        'is_dungeon': c.get('is_dungeon', False),
        'inventory': inventory_list,
        'columns': cols,
        'rows': rows,
        'uuid': f"{c.get('x')}_{c.get('y')}_{c.get('z')}",
        'playerName': 'Container'
    }