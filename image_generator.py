import json
import os
import sys

from PIL import Image, ImageDraw

Image.MAX_IMAGE_PIXELS = None
# --- CONSTANTS ---
ATLAS_JSON_PATH = "assets/atlas_map.json"
ATLAS_IMG_PATH = "assets/item_atlas.png"
SLOT_IMG_PATH = "assets/slots_background.png"
BORDER_IMG_PATH = "assets/container_9_slice.png"
FONT_JSON_PATH = "assets/font.json"
FONT_IMG_PATH = "assets/ascii.png"
OUTPUT_DIR = "backpack_images"

SLOT_SIZE = 128
ICON_SIZE = int(SLOT_SIZE * (16 / 18))
UI_SCALE = SLOT_SIZE / 18.0
GRID_COLS = 9
DEFAULT_HEADER_HEIGHT = 240
PADDING = 24

TEXT_SCALE_MAIN = 6
TEXT_SCALE_COUNT = 5
TEXT_SCALE_LABEL = 6

# --- GLOBAL RESOURCES ---
ATLAS_MAP = {}
ATLAS_IMAGE = None
SLOT_IMAGE = None
BORDER_IMAGE = None
BITMAP_FONT = None
MISSING_IDS = set()


class BitmapFont:
    """Handles rendering pixel-art text from a bitmap sheet."""

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
        pixels = img.load()
        w, h = img.size
        for x in range(w - 1, -1, -1):
            for y in range(h):
                if pixels[x, y][3] > 0:
                    return x + 1
        return w // 3

    def render(self, text, color=(255, 255, 255), shadow=True):
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
    """Loads all necessary assets (atlas, slots, font) into global variables."""
    global ATLAS_MAP, ATLAS_IMAGE, SLOT_IMAGE, BITMAP_FONT, BORDER_IMAGE

    print("[Init] Starting resource loading (this may take a moment)...")

    # 1. Load Atlas JSON
    print(f"[Init] Loading Atlas Map from {ATLAS_JSON_PATH}...")
    if not os.path.exists(ATLAS_JSON_PATH):
        print(f"[ERROR] {ATLAS_JSON_PATH} missing.")
        sys.exit(1)
    with open(ATLAS_JSON_PATH, 'r') as f:
        raw = json.load(f)
        ATLAS_MAP = raw.get('sprites', raw)
    print(f"[Init] Atlas Map loaded with {len(ATLAS_MAP)} entries.")

    # 2. Load Atlas Image
    print(f"[Init] Loading Atlas Image from {ATLAS_IMG_PATH}...")
    if not os.path.exists(ATLAS_IMG_PATH):
        print(f"[ERROR] {ATLAS_IMG_PATH} missing.")
        sys.exit(1)
    ATLAS_IMAGE = Image.open(ATLAS_IMG_PATH).convert("RGBA")
    ATLAS_IMAGE.load()
    print(f"[Init] Atlas Image loaded ({ATLAS_IMAGE.size[0]}x{ATLAS_IMAGE.size[1]}px).")

    # 3. Load Slot Background
    if os.path.exists(SLOT_IMG_PATH):
        try:
            SLOT_IMAGE = Image.open(SLOT_IMG_PATH).convert("RGBA")
            if SLOT_IMAGE.size != (SLOT_SIZE, SLOT_SIZE):
                SLOT_IMAGE = SLOT_IMAGE.resize((SLOT_SIZE, SLOT_SIZE), resample=Image.NEAREST)
            print("[Init] Custom Slot background loaded.")
        except Exception:
            SLOT_IMAGE = None
    if not SLOT_IMAGE:
        # Generate default slot image if custom one fails
        SLOT_IMAGE = Image.new("RGBA", (SLOT_SIZE, SLOT_SIZE), (139, 139, 139, 255))
        d = ImageDraw.Draw(SLOT_IMAGE)
        d.rectangle([0, 0, SLOT_SIZE - 1, SLOT_SIZE - 1], outline=(55, 55, 55), width=2)
        d.rectangle([2, 2, SLOT_SIZE - 1, SLOT_SIZE - 1], outline=(255, 255, 255), width=2)
        d.rectangle([2, 2, SLOT_SIZE - 4, SLOT_SIZE - 4], fill=(139, 139, 139))
        print("[Init] Generated default Slot background.")

    # 4. Load 9-Slice Border
    if os.path.exists(BORDER_IMG_PATH):
        BORDER_IMAGE = Image.open(BORDER_IMG_PATH).convert("RGBA")
        print("[Init] 9-Slice Border loaded.")
    else:
        print(f"[Init] Warning: {BORDER_IMG_PATH} not found. 9-slice border will be skipped.")

    # 5. Load Font
    BITMAP_FONT = BitmapFont()
    success = BITMAP_FONT.load(FONT_JSON_PATH, FONT_IMG_PATH)
    if not success:
        print("[ERROR] Failed to load sprite font. Text will be invisible.")

    # 6. Setup Output Directory
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        print(f"[Init] Created output directory: {OUTPUT_DIR}")


def get_texture_from_atlas(item_id):
    """Retrieves an item texture from the global ATLAS_IMAGE based on ID."""
    clean_id = str(item_id).replace('"', '').replace("'", "").strip().lower()
    coords = None
    if clean_id in ATLAS_MAP: coords = ATLAS_MAP[clean_id]
    if not coords and ":" not in clean_id: coords = ATLAS_MAP.get(f"minecraft:{clean_id}")
    if not coords and clean_id.startswith("minecraft:"): coords = ATLAS_MAP.get(clean_id.replace("minecraft:", ""))

    # Fallback logic for known container types
    if not coords and "chest" in clean_id: coords = ATLAS_MAP.get("chest")
    if not coords and "barrel" in clean_id: coords = ATLAS_MAP.get("barrel")
    if not coords and "shulker" in clean_id: coords = ATLAS_MAP.get("shulker_box")

    if not coords:
        if clean_id not in MISSING_IDS and clean_id not in ["air", "minecraft:air"]:
            if len(MISSING_IDS) < 5: print(f"[Debug] Missing ID: {clean_id}")
            MISSING_IDS.add(clean_id)
        return None

    x, y, w, h = coords['x'], coords['y'], coords['width'], coords['height']
    return ATLAS_IMAGE.crop((x, y, x + w, y + h))


def draw_sprite_text(target_img, pos, text, color=(255, 255, 255), scale=4, align="left"):
    """Draws pixel-art text onto an image canvas."""
    if not BITMAP_FONT or not text: return 0, 0
    rendered, w, h = BITMAP_FONT.render(text, color, shadow=True)
    if not rendered: return 0, 0
    new_w = rendered.width * scale
    new_h = rendered.height * scale
    final_text = rendered.resize((new_w, new_h), resample=Image.NEAREST)
    x, y = pos
    if align == "right": x = x - new_w
    target_img.paste(final_text, (x, y), final_text)
    return new_w, new_h


def measure_text_width(text, scale):
    """Measures the width of the rendered text."""
    if not BITMAP_FONT or not text: return 0
    rendered, w, h = BITMAP_FONT.render(text, shadow=True)
    if not rendered: return 0
    return rendered.width * scale


def apply_9_slice(content_img):
    """Applies a 9-slice border to the generated image."""
    if not BORDER_IMAGE: return content_img

    src_corner = 5
    dest_corner = int(src_corner * UI_SCALE)

    w, h = content_img.size

    # Create new canvas with padding
    new_w = w + (dest_corner * 2)
    new_h = h + (dest_corner * 2)
    new_img = Image.new("RGBA", (new_w, new_h), (0, 0, 0, 0))

    new_img.paste(content_img, (dest_corner, dest_corner))

    # Crop Source Parts
    tl_src = BORDER_IMAGE.crop((0, 0, 5, 5))
    t_src = BORDER_IMAGE.crop((5, 0, 6, 5))
    tr_src = BORDER_IMAGE.crop((6, 0, 11, 5))
    l_src = BORDER_IMAGE.crop((0, 5, 5, 6))
    r_src = BORDER_IMAGE.crop((6, 5, 11, 6))
    bl_src = BORDER_IMAGE.crop((0, 6, 5, 11))
    b_src = BORDER_IMAGE.crop((5, 6, 6, 11))
    br_src = BORDER_IMAGE.crop((6, 6, 11, 11))

    # Resize Corners
    tl = tl_src.resize((dest_corner, dest_corner), Image.NEAREST)
    tr = tr_src.resize((dest_corner, dest_corner), Image.NEAREST)
    bl = bl_src.resize((dest_corner, dest_corner), Image.NEAREST)
    br = br_src.resize((dest_corner, dest_corner), Image.NEAREST)

    # Resize Edges
    t = t_src.resize((w, dest_corner), Image.NEAREST)
    b = b_src.resize((w, dest_corner), Image.NEAREST)
    l = l_src.resize((dest_corner, h), Image.NEAREST)
    r = r_src.resize((dest_corner, h), Image.NEAREST)

    # Draw Corners
    new_img.paste(tl, (0, 0))
    new_img.paste(tr, (w + dest_corner, 0))
    new_img.paste(bl, (0, h + dest_corner))
    new_img.paste(br, (w + dest_corner, h + dest_corner))

    # Draw Edges
    new_img.paste(t, (dest_corner, 0))
    new_img.paste(b, (dest_corner, h + dest_corner))
    new_img.paste(l, (0, dest_corner))
    new_img.paste(r, (w + dest_corner, dest_corner))

    return new_img


def generate_backpack_image(data, main_icon_id=None):
    """Generates the main visualization image."""
    from data_parser import format_short_date, format_count  # Import helper functions

    is_container = data.get('type') == 'container'
    inv = data.get('inventory', {})
    upgrades = data.get('upgrades', [])

    # -- Determine Text Content --
    if is_container:
        line1 = f"Type: {data.get('id', 'Container')}"
        line2 = f"Pos: {data.get('x', '?')}, {data.get('y', '?')}, {data.get('z', '?')}"
        line3 = f"Dim: {data.get('dimension', 'Unknown')}"
        line4 = f"Dungeon: {'YES' if data.get('is_dungeon') else 'No'}"
        text_lines = [line1, line2, line3, line4]
    else:
        owner = data.get('playerName', 'Unknown')
        uuid = data.get('backpackUuid', 'Unknown')
        access = format_short_date(data.get('accessTimeRaw'))
        text_lines = [
            f"Owner: {owner}",
            f"Last: {access}",
            f"UUID: {uuid[:8]}..."
        ]

    max_text_width = 0
    for line in text_lines:
        w = measure_text_width(line, TEXT_SCALE_MAIN)
        if w > max_text_width: max_text_width = w

    head_size = 128
    head_x = PADDING
    text_start_x = head_x + head_size + 32
    text_end_x = text_start_x + max_text_width
    img_width = (GRID_COLS * SLOT_SIZE) + (PADDING * 2)

    # -- Header Layout Calculation --
    line_h = 65
    text_y_base = PADDING + 10
    text_block_bottom = text_y_base + (len(text_lines) * line_h)
    min_header_height = text_block_bottom + PADDING

    header_height = max(DEFAULT_HEADER_HEIGHT, min_header_height)

    # -- Upgrades Calculation (Backpacks Only) --
    upg_count = len(upgrades) if not is_container else 0
    collision = False
    upg_y = PADDING + 60

    if upg_count > 0:
        upg_block_width = (upg_count * SLOT_SIZE) + (max(0, upg_count - 1) * 10)
        upg_default_start_x = img_width - PADDING - upg_block_width

        collision = text_end_x + 20 > upg_default_start_x
        if collision:
            label_h = 8 * TEXT_SCALE_LABEL
            upg_y = text_block_bottom + label_h + 20
            upg_start_x = text_start_x
            header_height = max(header_height, int(upg_y + SLOT_SIZE + 20))
        else:
            upg_start_x = img_width - PADDING - SLOT_SIZE  # Start rightmost, work left

    # -- Inventory Grid Calculation --
    max_slot = max(inv.keys()) if inv else -1
    num_rows = (max_slot // GRID_COLS) + 1
    if num_rows < 1: num_rows = 1

    grid_height = num_rows * SLOT_SIZE
    img_height = header_height + grid_height + (PADDING * 2)

    img = Image.new("RGBA", (img_width, img_height), (198, 198, 198, 255))
    draw = ImageDraw.Draw(img)

    head_y = PADDING + 10

    # 1. Main Icon
    if SLOT_IMAGE:
        img.paste(SLOT_IMAGE, (head_x, head_y))

    if main_icon_id:
        m_icon = get_texture_from_atlas(main_icon_id)
        if m_icon:
            m_icon = m_icon.resize((ICON_SIZE, ICON_SIZE), resample=Image.NEAREST)
            off = (SLOT_SIZE - ICON_SIZE) // 2
            img.paste(m_icon, (head_x + off, head_y + off), m_icon)

    # 2. Text Data
    lbl_color = (255, 255, 255)
    for i, line in enumerate(text_lines):
        draw_sprite_text(img, (text_start_x, text_y_base + (i * line_h)), line, lbl_color, TEXT_SCALE_MAIN)

    # 3. Upgrades (Backpacks Only)
    if upgrades and not is_container:
        lbl_x = img_width - PADDING
        lbl_y = PADDING - 5
        lbl_align = "right"

        if collision:
            lbl_x = text_start_x
            lbl_y = upg_y - (8 * TEXT_SCALE_LABEL) - 5
            lbl_align = "left"

        draw_sprite_text(img, (lbl_x, lbl_y), "Upgrades:", lbl_color, TEXT_SCALE_LABEL, align=lbl_align)

        for i, (upg_id, count) in enumerate(upgrades):
            if collision:
                u_x = upg_start_x + (i * (SLOT_SIZE + 10))
            else:
                u_x = (img_width - PADDING - SLOT_SIZE) - (i * (SLOT_SIZE + 10))

            img.paste(SLOT_IMAGE, (u_x, int(upg_y)))
            icon = get_texture_from_atlas(upg_id)
            if icon:
                icon = icon.resize((ICON_SIZE, ICON_SIZE), resample=Image.NEAREST)
                off = (SLOT_SIZE - icon.width) // 2
                img.paste(icon, (u_x + off, int(upg_y) + off), icon)

    # 4. Inventory Grid
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
                count = item.get('count', 1)
                icon = get_texture_from_atlas(item['id'])
                if icon:
                    icon = icon.resize((ICON_SIZE, ICON_SIZE), resample=Image.NEAREST)
                    off_x = (SLOT_SIZE - icon.width) // 2
                    off_y = (SLOT_SIZE - icon.height) // 2
                    img.paste(icon, (x + off_x, y + off_y), icon)

                if count > 1:
                    c_str = format_count(count)
                    final_scale = TEXT_SCALE_COUNT

                    # Size optimization logic removed for brevity, assume default scale works
                    text_w = measure_text_width(c_str, final_scale)
                    text_h = BITMAP_FONT.char_height * final_scale
                    tx = (x + SLOT_SIZE) - text_w - 4
                    ty = (y + SLOT_SIZE) - text_h - 4
                    draw_sprite_text(img, (tx, ty), c_str, (255, 255, 255), final_scale)

    return apply_9_slice(img)


def save_img(data, main_icon_id=None):
    """Generates the image and saves it to the output directory."""
    try:
        if not main_icon_id:
            main_icon_id = data.get('id', 'sophisticatedbackpacks:backpack')

        img = generate_backpack_image(data, main_icon_id)

        # Filename
        if data.get('type') == 'container':
            safe_id = data.get('id', 'container').replace(':', '_')
            fname = f"{safe_id}_{data.get('x')}_{data.get('y')}_{data.get('z')}.png"
        else:
            fname = f"{data['backpackUuid']}.png"

        img.save(os.path.join(OUTPUT_DIR, fname), "PNG")
        return True
    except Exception as e:
        print(f"\nSave Error for {data.get('backpackUuid') or data.get('id', 'item')}: {e}")
        return False