import argparse
import asyncio
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from io import BytesIO
"""
Usage:
    python backpack_visualizer.py -f sophisticatedbackpacks.dat --item minecraft:flint
    python backpack_visualizer.py -f sophisticatedbackpacks.dat --owner swzo
    python backpack_visualizer.py -f sophisticatedbackpacks.dat --upgrade sophisticatedbackpacks:stack_upgrade_tier_1
"""
try:
    import aiohttp
    import nbtlib
    from PIL import Image, ImageDraw, ImageOps

    Image.MAX_IMAGE_PIXELS = None

except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Please run: pip install nbtlib pillow aiohttp")
    sys.exit(1)

try:
    import infiltrator
except ImportError:
    print("Error: 'infiltrator.py' not found in the current directory.")
    sys.exit(1)

ATLAS_JSON_PATH = "assets/atlas_map.json"
ATLAS_IMG_PATH = "assets/item_atlas.png"
SLOT_IMG_PATH = "assets/slots_background.png"
FONT_JSON_PATH = "assets/font.json"
FONT_IMG_PATH = "assets/ascii.png"
OUTPUT_DIR = "backpack_images"

SLOT_SIZE = 128

ICON_SIZE = int(SLOT_SIZE * (16 / 18))

GRID_COLS = 9
DEFAULT_HEADER_HEIGHT = 240
PADDING = 24

TEXT_SCALE_MAIN = 6
TEXT_SCALE_COUNT = 5
TEXT_SCALE_LABEL = 6

ATLAS_MAP = {}
ATLAS_IMAGE = None
SLOT_IMAGE = None
BITMAP_FONT = None

MISSING_IDS = set()

class BitmapFont:
    def __init__(self):
        self.chars = {}
        self.char_height = 8
        self.space_width = 4

    def load(self, json_path, img_path):
        if not os.path.exists(json_path) or not os.path.exists(img_path):
            print(f"[Font] Error: {json_path} or {img_path} missing.")
            return False

        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                config = json.load(f)

            provider = next((p for p in config.get('providers', []) if p.get('type') == 'bitmap'), None)
            if not provider:
                print("[Font] No 'bitmap' provider found in json.")
                return False

            sheet = Image.open(img_path).convert("RGBA")
            sheet_w, sheet_h = sheet.size

            rows = provider.get('chars', [])
            if not rows: return False

            cell_w = sheet_w // 16
            cell_h = sheet_h // 16
            self.char_height = cell_h
            self.space_width = max(2, cell_w // 2)

            for r, row_str in enumerate(rows):
                for c, char in enumerate(row_str):
                    if not char: continue

                    x = c * cell_w
                    y = r * cell_h
                    char_img = sheet.crop((x, y, x + cell_w, y + cell_h))

                    width = self._calculate_width(char_img)
                    self.chars[char] = (char_img, width)

            if ' ' not in self.chars:
                self.chars[' '] = (Image.new("RGBA", (self.space_width, self.char_height)), self.space_width)

            print(f"[Font] Loaded {len(self.chars)} characters.")
            return True
        except Exception as e:
            print(f"[Font] Load failed: {e}")
            return False

    def _calculate_width(self, img):
        """Scans the character image to find effective pixel width (tight fit)."""
        pixels = img.load()
        w, h = img.size
        for x in range(w - 1, -1, -1):
            for y in range(h):
                if pixels[x, y][3] > 0:
                    return x + 1
        return w // 3

    def render(self, text, color=(255, 255, 255), shadow=True):
        """
        Renders text to a PIL Image with shadow and variable width.
        Returns (Image, total_width_cursor, height)
        Note: Image width is total_width_cursor + 2 (for shadow/padding)
        """
        if not text: return None, 0, 0

        text_chars = [self.chars.get(c, self.chars.get('?')) for c in text]
        text_chars = [tc for tc in text_chars if tc]
        if not text_chars: return None, 0, 0

        gap = 1

        total_width = sum(tc[1] for tc in text_chars) + max(0, (len(text_chars) - 1) * gap)
        height = self.char_height

        canvas = Image.new("RGBA", (total_width + 2, height + 2), (0, 0, 0, 0))

        r, g, b = color[:3]
        shadow_color = (int(r * 0.25), int(g * 0.25), int(b * 0.25), 255)
        main_color = (r, g, b, 255)

        x_cursor = 0

        for char_img, w in text_chars:
            if not char_img:
                x_cursor += w + gap
                continue

            mask = char_img.split()[-1]

            if shadow:
                shadow_layer = Image.new("RGBA", char_img.size, shadow_color)
                canvas.paste(shadow_layer, (x_cursor + 1, 1), mask)

            color_layer = Image.new("RGBA", char_img.size, main_color)
            canvas.paste(color_layer, (x_cursor, 0), mask)

            x_cursor += w + gap

        return canvas, total_width, height

def load_resources():
    global ATLAS_MAP, ATLAS_IMAGE, SLOT_IMAGE, BITMAP_FONT

    print(f"[Init] Loading Atlas Map from {ATLAS_JSON_PATH}...")
    if not os.path.exists(ATLAS_JSON_PATH):
        print(f"Error: {ATLAS_JSON_PATH} missing.")
        sys.exit(1)
    with open(ATLAS_JSON_PATH, 'r') as f:
        raw = json.load(f)
        ATLAS_MAP = raw.get('sprites', raw)

    print(f"[Init] Loading Atlas Image from {ATLAS_IMG_PATH}...")
    if not os.path.exists(ATLAS_IMG_PATH):
        print(f"Error: {ATLAS_IMG_PATH} missing.")
        sys.exit(1)
    ATLAS_IMAGE = Image.open(ATLAS_IMG_PATH).convert("RGBA")
    ATLAS_IMAGE.load()

    if os.path.exists(SLOT_IMG_PATH):
        try:
            SLOT_IMAGE = Image.open(SLOT_IMG_PATH).convert("RGBA")
            if SLOT_IMAGE.size != (SLOT_SIZE, SLOT_SIZE):
                SLOT_IMAGE = SLOT_IMAGE.resize((SLOT_SIZE, SLOT_SIZE), resample=Image.NEAREST)
        except Exception:
            SLOT_IMAGE = None

    if not SLOT_IMAGE:
        SLOT_IMAGE = Image.new("RGBA", (SLOT_SIZE, SLOT_SIZE), (139, 139, 139, 255))
        d = ImageDraw.Draw(SLOT_IMAGE)
        d.rectangle([0, 0, SLOT_SIZE - 1, SLOT_SIZE - 1], outline=(55, 55, 55), width=2)
        d.rectangle([2, 2, SLOT_SIZE - 1, SLOT_SIZE - 1], outline=(255, 255, 255), width=2)
        d.rectangle([2, 2, SLOT_SIZE - 4, SLOT_SIZE - 4], fill=(139, 139, 139))

    print("[Init] Loading Sprite Font...")
    BITMAP_FONT = BitmapFont()
    success = BITMAP_FONT.load(FONT_JSON_PATH, FONT_IMG_PATH)
    if not success:
        print("WARNING: Failed to load sprite font. Text will be invisible.")

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

def format_short_date(timestamp_ms):
    if not timestamp_ms: return "Never"
    try:
        dt = datetime.fromtimestamp(timestamp_ms / 1000)
        return dt.strftime("%y-%m-%d %H:%M")
    except:
        return "Invalid"

def format_count(count):
    """Formats large numbers into 10k, 1M, 1B format."""
    if count < 10000:
        return str(count)

    n = float(count)
    for suffix in ['k', 'M', 'B', 'T']:
        n /= 1000.0
        if n < 1000:

            if n >= 10:
                return f"{int(n)}{suffix}"
            else:
                s = f"{n:.1f}"
                if s.endswith('.0'): s = s[:-2]
                return f"{s}{suffix}"

    return "INF"

def get_texture_from_atlas(item_id):
    clean_id = str(item_id).replace('"', '').replace("'", "").strip().lower()
    coords = None

    if clean_id in ATLAS_MAP: coords = ATLAS_MAP[clean_id]
    if not coords and ":" not in clean_id: coords = ATLAS_MAP.get(f"minecraft:{clean_id}")
    if not coords and clean_id.startswith("minecraft:"): coords = ATLAS_MAP.get(clean_id.replace("minecraft:", ""))

    if not coords:
        short = clean_id.split(":")[-1]
        for k in ATLAS_MAP:
            if k == short or k.endswith(f":{short}"):
                coords = ATLAS_MAP[k]
                break

    if not coords:
        if clean_id not in MISSING_IDS and clean_id not in ["air", "minecraft:air"]:
            if len(MISSING_IDS) < 5: print(f"[Debug] Missing ID: {clean_id}")
            MISSING_IDS.add(clean_id)
        return None

    x, y, w, h = coords['x'], coords['y'], coords['width'], coords['height']
    return ATLAS_IMAGE.crop((x, y, x + w, y + h))

def draw_sprite_text(target_img, pos, text, color=(255, 255, 255), scale=4, align="left"):
    """
    Renders text using the sprite font, upscales it, and pastes it onto the target.
    Returns the width and height of the drawn text block.
    """
    if not BITMAP_FONT or not text: return 0, 0

    rendered, w, h = BITMAP_FONT.render(text, color, shadow=True)
    if not rendered: return 0, 0

    new_w = rendered.width * scale
    new_h = rendered.height * scale

    final_text = rendered.resize((new_w, new_h), resample=Image.NEAREST)

    x, y = pos
    if align == "right":
        x = x - new_w

    target_img.paste(final_text, (x, y), final_text)

    return new_w, new_h

def measure_text_width(text, scale):
    """Calculates the width of the text in pixels after scaling, without drawing."""
    if not BITMAP_FONT or not text: return 0

    rendered, w, h = BITMAP_FONT.render(text, shadow=True)
    if not rendered: return 0

    return rendered.width * scale

def generate_backpack_image(data, head_bytes):
    inv = data.get('inventory', {})
    upgrades = data.get('upgrades', [])
    owner = data.get('playerName', 'Unknown')
    uuid = data.get('backpackUuid', 'Unknown')
    access = format_short_date(data.get('accessTimeRaw'))

    txt_owner = f"Owner: {owner}"
    txt_access = f"Last: {access}"
    txt_uuid = f"UUID: {uuid[:8]}..."

    w_owner = measure_text_width(txt_owner, TEXT_SCALE_MAIN)
    w_access = measure_text_width(txt_access, TEXT_SCALE_MAIN)
    w_uuid = measure_text_width(txt_uuid, TEXT_SCALE_MAIN)

    max_text_width = max(w_owner, w_access, w_uuid)

    head_size = 128
    head_x = PADDING

    text_start_x = head_x + head_size + 32
    text_end_x = text_start_x + max_text_width

    img_width = (GRID_COLS * SLOT_SIZE) + (PADDING * 2)

    upg_count = len(upgrades)
    upg_block_width = 0
    if upg_count > 0:

        upg_block_width = (upg_count * SLOT_SIZE) + (max(0, upg_count - 1) * 10)

    upg_default_start_x = img_width - PADDING - upg_block_width

    collision = text_end_x + 20 > upg_default_start_x

    header_height = DEFAULT_HEADER_HEIGHT

    upg_y = PADDING + 60
    upg_start_x = img_width - PADDING - SLOT_SIZE

    line_h = 65
    text_y_base = PADDING + 10

    if collision and upg_count > 0:

        text_block_bottom = text_y_base + (2 * line_h) + (8 * TEXT_SCALE_MAIN)

        upg_y = text_block_bottom + 90

        upg_start_x = text_start_x + ((upg_count - 1) * (SLOT_SIZE + 10))

        header_height = int(upg_y + SLOT_SIZE + 20)

    inv = data.get('inventory', {})
    max_slot = max(inv.keys()) if inv else -1
    num_rows = max(1, (max_slot // GRID_COLS) + 1)
    grid_height = num_rows * SLOT_SIZE

    img_height = header_height + grid_height + (PADDING * 2)

    img = Image.new("RGBA", (img_width, img_height), (198, 198, 198, 255))
    draw = ImageDraw.Draw(img)

    head_y = PADDING + 10

    draw.rectangle([head_x, head_y, head_x + head_size, head_y + head_size], fill=(50, 50, 50))

    if head_bytes:
        try:
            h_img = Image.open(BytesIO(head_bytes)).convert("RGBA")
            h_img = h_img.resize((head_size, head_size), resample=Image.NEAREST)

            img.paste(h_img, (head_x, head_y), h_img)
        except Exception as e:
            print(f"[Warn] Failed to render head: {e}")

    draw.rectangle([head_x - 4, head_y - 4, head_x + head_size + 4, head_y + head_size + 4], outline="black", width=4)

    lbl_color = (255, 255, 255)
    draw_sprite_text(img, (text_start_x, text_y_base), txt_owner, lbl_color, TEXT_SCALE_MAIN)
    draw_sprite_text(img, (text_start_x, text_y_base + line_h), txt_access, lbl_color, TEXT_SCALE_MAIN)
    draw_sprite_text(img, (text_start_x, text_y_base + (line_h * 2)), txt_uuid, lbl_color, TEXT_SCALE_MAIN)

    if upgrades:

        lbl_x = img_width - PADDING
        lbl_y = PADDING - 5
        lbl_align = "right"

        if collision:
            lbl_x = text_start_x
            lbl_y = upg_y - (8 * TEXT_SCALE_LABEL) - 5
            lbl_align = "left"

        draw_sprite_text(img, (lbl_x, lbl_y), "Upgrades:", lbl_color, TEXT_SCALE_LABEL, align=lbl_align)

        for i, (upg_id, count) in enumerate(upgrades):
            u_x = upg_start_x - (i * (SLOT_SIZE + 10))

            img.paste(SLOT_IMAGE, (u_x, int(upg_y)))
            icon = get_texture_from_atlas(upg_id)
            if icon:
                icon = icon.resize((ICON_SIZE, ICON_SIZE), resample=Image.NEAREST)
                off = (SLOT_SIZE - icon.width) // 2
                img.paste(icon, (u_x + off, int(upg_y) + off), icon)

    grid_start_x = PADDING
    grid_start_y = header_height + PADDING

    for row in range(num_rows):
        for col in range(GRID_COLS):
            slot_idx = (row * GRID_COLS) + col
            x = grid_start_x + (col * SLOT_SIZE)
            y = grid_start_y + (row * SLOT_SIZE)

            img.paste(SLOT_IMAGE, (x, y))

            if slot_idx in inv:
                item = inv[slot_idx]
                count = item['count']
                icon = get_texture_from_atlas(item['id'])
                if icon:
                    icon = icon.resize((ICON_SIZE, ICON_SIZE), resample=Image.NEAREST)
                    off_x = (SLOT_SIZE - icon.width) // 2
                    off_y = (SLOT_SIZE - icon.height) // 2
                    img.paste(icon, (x + off_x, y + off_y), icon)

                if count > 1:

                    c_str = format_count(count)

                    max_w = SLOT_SIZE - 8

                    final_scale = TEXT_SCALE_COUNT

                    for s in range(TEXT_SCALE_COUNT, 0, -1):
                        w = measure_text_width(c_str, s)
                        if w <= max_w:
                            final_scale = s
                            break
                        final_scale = s

                    text_w = measure_text_width(c_str, final_scale)
                    text_h = BITMAP_FONT.char_height * final_scale

                    tx = (x + SLOT_SIZE) - text_w - 4

                    ty = (y + SLOT_SIZE) - text_h - 4

                    draw_sprite_text(img, (tx, ty), c_str, (255, 255, 255), final_scale)

    return img

def parse_all_backpacks(file_path):
    print(f"[Scan] Reading NBT file: {file_path}...")
    try:
        doc = nbtlib.load(file_path)
    except Exception as e:
        print(f"Fatal Error reading NBT: {e}")
        return

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
        print("Error: Could not locate 'backpackContents'.")
        return

    access_log = infiltrator.safe_get(data_payload, 'accessLogRecords', [])
    contents_list = infiltrator.safe_get(data_payload, 'backpackContents', [])
    owner_index = infiltrator.build_owner_index_from_access_log(access_log)

    print(f"[Scan] Found {len(contents_list)} backpacks.")

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
                'backpackUuid': uuid,
                'playerName': rec.get('playerName', "Unknown"),
                'accessTimeRaw': rec.get('accessTime'),
                'inventory': inv_map,
                'upgrades': upg_list
            }
        except:
            continue

def matches_filter(bp, args):
    if not (args.owner or args.item or args.upgrade): return True
    q = args.query.lower() if args.query else ""
    if args.owner:
        return q in bp['playerName'].lower() or q in bp['backpackUuid'].lower()
    if args.item:
        for it in bp['inventory'].values():
            if q in it['id'].lower(): return True
        return False
    if args.upgrade:
        for u, _ in bp['upgrades']:
            if q in u.lower(): return True
        return False
    return False

async def fetch_skin(session, name):
    if not name or name == "Unknown": return None
    try:
        async with session.get(f"https://minotar.net/helm/{name}/128.png", headers={"User-Agent": "BV/1.0"},
                               timeout=5) as r:
            if r.status == 200: return await r.read()
    except:
        pass
    return None

def save_img(data, head):
    try:
        img = generate_backpack_image(data, head)
        img.save(os.path.join(OUTPUT_DIR, f"{data['backpackUuid']}.png"), "PNG")
        return True
    except Exception as e:
        print(f"Save Error {data['backpackUuid']}: {e}")
        return False

async def main():
    p = argparse.ArgumentParser()
    p.add_argument("-f", "--file", required=True)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--owner", action="store_true")
    g.add_argument("--item", action="store_true")
    g.add_argument("--upgrade", action="store_true")
    p.add_argument("query", nargs="?")
    args = p.parse_args()

    if (args.owner or args.item or args.upgrade) and not args.query:
        p.error("Query required for filter.")

    load_resources()

    bps = [bp for bp in parse_all_backpacks(args.file) if matches_filter(bp, args)]
    count = len(bps)
    print(f"[Main] Found {count} backpacks.")
    if count == 0: return

    if count > 24:
        if input(f"Generate {count} images? [y/N] ").lower() != 'y': return

    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=os.cpu_count() + 2) as ex:
        async with aiohttp.ClientSession() as sess:
            tasks = []
            sem = asyncio.Semaphore(20)

            async def worker(bp):
                async with sem:
                    head = await fetch_skin(sess, bp['playerName'])
                    await loop.run_in_executor(ex, save_img, bp, head)
                    print(".", end="", flush=True)

            for bp in bps: tasks.append(asyncio.create_task(worker(bp)))
            await asyncio.gather(*tasks)

    print(f"\n[Done] Images saved to {os.path.abspath(OUTPUT_DIR)}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass