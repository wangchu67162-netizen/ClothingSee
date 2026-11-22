#!/usr/bin/env python
"""Build the local image set for 衣见 ATELIER.

Strategy:
1. Generate deterministic, brand-consistent fallback images first (works offline).
2. Try curated Unsplash photos; if a download succeeds, replace the fallback with
   a locally stored, cropped and color-graded WebP (no runtime CDN dependency).
3. Create image variants, hero collages and a sample outfit image.

Usage:
    backend/.venv/Scripts/python.exe scripts/fetch_assets.py
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageStat

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.catalog_data import PRODUCTS, UNSPLASH_SOURCES  # noqa: E402

IMAGES = BACKEND / "app" / "static" / "images"
PRODUCTS_DIR = IMAGES / "products"
HERO_DIR = IMAGES / "hero"
SAMPLES_DIR = IMAGES / "samples"
FRONTEND_FALLBACK = ROOT / "frontend" / "public" / "images" / "fallback"
CONTACT_SHEET = ROOT / "docs" / "assets-contact-sheet.webp"

for directory in (PRODUCTS_DIR, HERO_DIR, SAMPLES_DIR, FRONTEND_FALLBACK):
    directory.mkdir(parents=True, exist_ok=True)

# calm, editorial palette per Chinese colour name
COLOR_RGB: dict[str, tuple[int, int, int]] = {
    "雾灰": (128, 132, 136),
    "曜石黑": (22, 23, 28),
    "燕麦": (190, 174, 150),
    "香槟金": (192, 160, 104),
    "墨黑": (18, 19, 24),
    "山岚灰": (139, 142, 145),
    "驼色": (169, 137, 103),
    "月白": (232, 229, 220),
    "黛青": (62, 82, 86),
    "烟粉": (196, 166, 164),
    "砚石黑": (38, 38, 42),
    "燕麦白": (225, 216, 201),
    "苔绿": (93, 108, 87),
    "初雪白": (242, 241, 237),
    "雾霾蓝": (122, 140, 153),
    "苔藓绿": (86, 104, 82),
    "奶咖": (178, 154, 128),
    "酒红": (101, 38, 48),
    "绛红": (138, 40, 50),
    "青瓷": (139, 166, 157),
    "流云灰": (150, 151, 153),
    "米白": (230, 224, 211),
    "沙丘蓝": (113, 134, 151),
    "做旧灰": (111, 113, 116),
    "香槟": (211, 185, 147),
    "星夜蓝": (35, 48, 75),
    "琥珀金": (192, 145, 74),
    "琥珀": (183, 124, 64),
    "透明": (210, 210, 205),
    "夜幕黑": (22, 22, 27),
}

CATEGORY_ACCENT = {
    "外套": (216, 190, 147),
    "上装": (232, 229, 220),
    "连衣裙": (255, 107, 61),
    "下装": (110, 139, 134),
    "配饰": (216, 190, 147),
}

FONT_CANDIDATES = [
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
    "C:/Windows/Fonts/STSONG.TTF",
]


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    if bold:
        candidates = [
            "C:/Windows/Fonts/msyhbd.ttc",
            "C:/Windows/Fonts/simhei.ttf",
            *FONT_CANDIDATES,
        ]
    else:
        candidates = FONT_CANDIDATES
    for path in candidates:
        try:
            if Path(path).exists():
                return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3))


def _vertical_gradient(size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    width, height = size
    image = Image.new("RGB", size, top)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        draw.line([(0, y), (width, y)], fill=_mix(top, bottom, y / max(height - 1, 1)))
    return image


def _grain(image: Image.Image, seed: str, opacity: float = 0.05) -> Image.Image:
    image = image.convert("RGB")
    rng = np.random.default_rng(int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16))
    width, height = image.size
    noise = rng.normal(0, 26, (height // 2, width // 2)).astype(np.float32)
    noise_img = Image.fromarray(np.clip(noise + 128, 0, 255).astype(np.uint8)).resize((width, height), Image.Resampling.BILINEAR)
    grain = Image.merge("RGB", (noise_img, noise_img, noise_img))
    return Image.blend(image, grain, opacity)


def _garment_silhouette(draw: ImageDraw.ImageDraw, category: str, accent: tuple[int, int, int]) -> None:
    ivory = (242, 236, 224, 62)
    gold = (216, 190, 147, 90)
    line = (242, 236, 224, 120)
    if category == "外套":
        draw.polygon([(340, 310), (430, 270), (470, 300), (560, 300), (600, 270), (690, 310), (735, 560), (650, 610), (625, 1010), (325, 1010), (300, 610), (205, 560)], fill=ivory)
        draw.line([(470, 300), (470, 1000)], fill=line, width=3)
        draw.line([(430, 270), (400, 430), (300, 610)], fill=gold, width=4)
        draw.line([(600, 270), (630, 430), (735, 560)], fill=gold, width=4)
        draw.rectangle([(330, 610), (615, 650)], fill=(32, 32, 38, 70))
        draw.line([(380, 300), (470, 400), (560, 300)], fill=line, width=3)
    elif category == "上装":
        draw.polygon([(345, 350), (430, 300), (470, 330), (550, 330), (590, 300), (675, 350), (700, 620), (620, 640), (600, 980), (420, 980), (400, 640), (320, 620)], fill=ivory)
        draw.line([(470, 330), (500, 500), (530, 330)], fill=line, width=3)
        draw.line([(430, 300), (390, 520), (320, 620)], fill=gold, width=4)
        draw.line([(590, 300), (630, 520), (700, 620)], fill=gold, width=4)
        for y in range(430, 900, 60):
            draw.arc([(430, y), (570, y + 32)], 200, 340, fill=(255, 255, 255, 26), width=2)
    elif category == "连衣裙":
        draw.polygon([(430, 300), (470, 300), (485, 480), (560, 980), (340, 980), (455, 480), (470, 300)], fill=ivory)
        draw.polygon([(470, 300), (500, 300), (515, 480), (560, 980), (340, 980), (425, 480)], fill=(255, 255, 255, 20))
        draw.line([(400, 470), (500, 470)], fill=gold, width=4)
        draw.line([(470, 300), (470, 470)], fill=line, width=2)
        for x in (390, 430, 510, 550):
            draw.line([(470, 500), (x, 900)], fill=(255, 255, 255, 18), width=2)
    elif category == "下装":
        draw.polygon([(370, 420), (630, 420), (610, 980), (510, 980), (500, 560), (400, 560), (390, 980), (290, 980)], fill=ivory)
        draw.rectangle([(370, 420), (630, 470)], fill=(32, 32, 38, 60))
        draw.line([(500, 470), (500, 900)], fill=line, width=2)
        draw.line([(420, 500), (400, 940)], fill=gold, width=2)
        draw.line([(580, 500), (600, 940)], fill=gold, width=2)
    else:  # 配饰
        draw.rounded_rectangle([(350, 430), (550, 850)], radius=34, outline=(242, 236, 224, 85), width=3)
        draw.arc([(390, 260), (510, 470)], 180, 350, fill=gold, width=5)
        draw.ellipse([(430, 610), (470, 650)], fill=(216, 190, 147, 95))
        draw.arc([(550, 470), (650, 900)], 280, 80, fill=(255, 255, 255, 50), width=2)


def generate_fallback(product: dict) -> Image.Image:
    primary = COLOR_RGB.get(product["colors"][0], (120, 120, 120))
    accent = CATEGORY_ACCENT.get(product["category"], (216, 190, 147))
    size = (900, 1200)
    top = _mix((12, 13, 18), primary, 0.18)
    bottom = _mix((7, 7, 11), primary, 0.42)
    image = _vertical_gradient(size, top, bottom)

    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for cx, cy, r, alpha in (
        (210, 250, 360, 60),
        (760, 360, 420, 48),
        (500, 900, 520, 35),
    ):
        draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], fill=(*accent, alpha))
    overlay = overlay.filter(ImageFilter.GaussianBlur(90))
    image = Image.alpha_composite(image.convert("RGBA"), overlay)

    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    # delicate frame and vertical labels
    draw.rectangle([(34, 34), (866, 1166)], outline=(245, 239, 230, 34), width=1)
    draw.line([(74, 128), (74, 1070)], fill=(216, 190, 147, 90), width=2)
    _garment_silhouette(draw, product["category"], accent)

    brand_font = _font(22)
    name_font = _font(66, bold=True)
    meta_font = _font(24)
    draw.text((106, 78), "衣见 ATELIER", font=brand_font, fill=(245, 239, 230, 200))
    draw.text((106, 1050), product["name"], font=name_font, fill=(245, 239, 230, 235))
    draw.text(
        (108, 1124),
        f'{product["category"]}  ·  {product["colors"][0]}  ·  ¥{int(product["price"])}',
        font=meta_font,
        fill=(216, 190, 147, 225),
    )
    draw.text((790, 78), product["sku"].upper(), font=_font(18), fill=(245, 239, 230, 110))
    image = Image.alpha_composite(image, overlay)

    image = _grain(image, product["sku"], opacity=0.045)
    return image.convert("RGB")


def _load_remote(photo_id: str) -> Image.Image | None:
    url = f"https://images.unsplash.com/{photo_id}?auto=format&fit=crop&w=1400&q=88"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 YijianAssetBuilder/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            data = response.read()
        image = Image.open(io.BytesIO(data))
        image = ImageOps.exif_transpose(image).convert("RGB")
        return ImageOps.fit(image, (900, 1200), method=Image.Resampling.LANCZOS, centering=(0.5, 0.38))
    except Exception:
        return None


def _vignette(image: Image.Image) -> Image.Image:
    width, height = image.size
    overlay = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(overlay)
    draw.ellipse([(-width * 0.22, -height * 0.16), (width * 1.22, height * 1.16)], fill=255)
    overlay = overlay.filter(ImageFilter.GaussianBlur(180))
    dark = Image.new("RGB", (width, height), (6, 6, 9))
    return Image.composite(image, dark, overlay)


def _variants(image: Image.Image, product: dict) -> list[Image.Image]:
    result = [image]
    width, height = image.size
    # close crop
    alt1 = ImageOps.fit(image.crop((width * 0.08, height * 0.05, width * 0.92, height * 0.88)), (900, 1200), method=Image.Resampling.LANCZOS)
    alt1 = Image.blend(alt1, Image.new("RGB", alt1.size, COLOR_RGB.get(product["colors"][0], (20, 20, 20))), 0.08)
    result.append(_vignette(alt1))
    # detail crop, cooler grade
    alt2 = ImageOps.fit(image.crop((width * 0.16, height * 0.20, width * 0.84, height * 0.80)), (900, 1200), method=Image.Resampling.LANCZOS)
    alt2 = Image.blend(alt2, Image.new("RGB", alt2.size, (12, 18, 24)), 0.18)
    result.append(alt2)
    return result


def _save_webp(image: Image.Image, path: Path) -> None:
    image.save(path, "WEBP", quality=86, method=6)


def build_products(download: bool = True) -> dict:
    report = {"downloaded": [], "fallback": []}
    for index, product in enumerate(PRODUCTS):
        sku = product["sku"]
        fallback = generate_fallback(product)
        variants = _variants(fallback, product)
        remote = _load_remote(UNSPLASH_SOURCES.get(sku, "")) if download and UNSPLASH_SOURCES.get(sku) else None
        if remote is not None:
            variants = _variants(_vignette(remote), product)
            report["downloaded"].append(sku)
        else:
            report["fallback"].append(sku)
        _save_webp(variants[0], PRODUCTS_DIR / f"{sku}.webp")
        _save_webp(variants[1], PRODUCTS_DIR / f"{sku}-alt1.webp")
        _save_webp(variants[2], PRODUCTS_DIR / f"{sku}-alt2.webp")
        print(f"[{index + 1:02d}/{len(PRODUCTS)}] {sku} {'photo' if remote else 'generated'}")
    return report


def _load_product_image(sku: str) -> Image.Image:
    path = PRODUCTS_DIR / f"{sku}.webp"
    if path.exists():
        return Image.open(path).convert("RGB")
    return generate_fallback(next(p for p in PRODUCTS if p["sku"] == sku))


def build_heroes() -> None:
    groups = [
        ["ys-ow-001", "ys-tp-001", "ys-bt-001"],
        ["ys-dr-003", "ys-ac-001", "ys-dr-001"],
        ["ys-ow-003", "ys-tp-002", "ys-ac-003"],
    ]
    for index, skus in enumerate(groups, start=1):
        canvas = Image.new("RGB", (1600, 1000), (7, 7, 11))
        for pos, sku in enumerate(skus):
            image = _load_product_image(sku).resize((720, 960), Image.Resampling.LANCZOS)
            x = [40, 450, 860][pos]
            y = [40, 10, 40][pos]
            canvas.paste(image, (x, y))
            overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            draw.rectangle([(x + 20, y + 20), (x + 700, y + 940)], outline=(245, 239, 230, 40), width=1)
            canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
        veil = Image.new("RGBA", canvas.size, (5, 5, 9, 70))
        canvas = Image.alpha_composite(canvas.convert("RGBA"), veil).convert("RGB")
        draw = ImageDraw.Draw(canvas)
        draw.text((60, 42), "衣见 ATELIER", font=_font(30), fill=(245, 239, 230))
        draw.text((1200, 900), f"CHAPTER 0{index}", font=_font(22), fill=(216, 190, 147))
        _save_webp(canvas, HERO_DIR / f"hero-{index}.webp")


def build_sample_outfit() -> None:
    canvas = Image.new("RGB", (1200, 1600), (8, 8, 12))
    skus = ["ys-ow-001", "ys-tp-001", "ys-bt-001"]
    for pos, sku in enumerate(skus):
        image = _load_product_image(sku).resize((560, 746), Image.Resampling.LANCZOS)
        x = [30, 610, 320][pos]
        y = [60, 60, 840][pos]
        canvas.paste(image, (x, y))
        overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        draw.rectangle([(x + 14, y + 14), (x + 546, y + 732)], outline=(245, 239, 230, 48), width=1)
        canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(canvas)
    draw.text((60, 30), "今日穿搭提案 / OUTFIT STUDY", font=_font(26), fill=(245, 239, 230))
    draw.text((60, 1480), "暮色长风衣 · 云缎真丝衬衫 · 流云阔腿裤", font=_font(28), fill=(216, 190, 147))
    _save_webp(canvas, SAMPLES_DIR / "outfit-demo.webp")


def build_fallback_svg() -> None:
    svg = """<svg xmlns="http://www.w3.org/2000/svg" width="900" height="1200" viewBox="0 0 900 1200">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#17171f"/><stop offset="1" stop-color="#0a0a0f"/></linearGradient></defs>
<rect width="900" height="1200" fill="url(#g)"/>
<rect x="34" y="34" width="832" height="1132" fill="none" stroke="#d8be93" stroke-opacity=".25"/>
<path d="M330 330 L420 280 L470 330 L560 330 L610 280 L700 340 L720 620 L640 650 L620 1000 L400 1000 L380 650 L300 620 Z" fill="#f5efe6" fill-opacity=".08" stroke="#d8be93" stroke-opacity=".5" stroke-width="2"/>
<text x="100" y="1080" fill="#f5efe6" font-family="serif" font-size="64">衣见 ATELIER</text>
<text x="104" y="1130" fill="#d8be93" font-family="sans-serif" font-size="24">IMAGE FALLBACK</text>
</svg>"""
    (FRONTEND_FALLBACK / "garment.svg").write_text(svg, encoding="utf-8")


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: float,
    size: int,
    bold: bool = False,
    min_size: int = 14,
) -> ImageFont.FreeTypeFont:
    """Shrink the font until the text fits in max_width (guards against overflow)."""
    font = _font(size, bold=bold)
    while size > min_size and draw.textlength(text, font=font) > max_width:
        size -= 1
        font = _font(size, bold=bold)
    return font


def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return mask


def _manifest_sources() -> dict[str, str]:
    sources = {product["sku"]: "未知" for product in PRODUCTS}
    try:
        manifest = json.loads((IMAGES / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return sources
    for sku in manifest.get("downloaded", []):
        if sku in sources:
            sources[sku] = "下载"
    for sku in manifest.get("fallback", []):
        if sku in sources:
            sources[sku] = "兜底"
    return sources


def build_contact_sheet(output: Path = CONTACT_SHEET, columns: int = 4) -> Path:
    """Render docs/assets-contact-sheet.webp with all product thumbs + name/SKU."""
    margin = 56
    gap = 28
    canvas_width = 1600
    cell_width = (canvas_width - margin * 2 - gap * (columns - 1)) // columns
    thumb_width = cell_width
    thumb_height = round(thumb_width * 4 / 3)
    label_height = 94
    cell_height = thumb_height + label_height
    rows = (len(PRODUCTS) + columns - 1) // columns
    header_height = 210
    footer_height = 92
    canvas_height = header_height + rows * cell_height + (rows - 1) * gap + footer_height

    background = (10, 10, 15)
    card = (19, 19, 25)
    line_color = (46, 44, 40)
    ivory = (242, 236, 224)
    gold = (216, 190, 147)
    muted = (150, 148, 142)

    canvas = Image.new("RGB", (canvas_width, canvas_height), background)
    draw = ImageDraw.Draw(canvas)

    draw.text((margin, 40), "衣见 ATELIER", font=_font(24), fill=gold)
    draw.text((margin, 78), "商品素材质检总览", font=_font(46, bold=True), fill=ivory)
    draw.text((margin, 142), "主图 / alt1 / alt2 · hero-1-3 · 样例穿搭 · manifest.json", font=_font(20), fill=muted)
    summary = f"{len(PRODUCTS)} 个 SKU · {len(PRODUCTS) * 3} 张商品图 · 900 × 1200 WebP"
    summary_font = _font(22)
    summary_width = draw.textlength(summary, font=summary_font)
    draw.text((canvas_width - margin - summary_width, 112), summary, font=summary_font, fill=ivory)
    draw.line([(margin, 176), (canvas_width - margin, 176)], fill=line_color, width=1)

    sources = _manifest_sources()
    for index, product in enumerate(PRODUCTS):
        row, column = divmod(index, columns)
        x = margin + column * (cell_width + gap)
        y = header_height + row * (cell_height + gap)
        draw.rounded_rectangle(
            [x, y, x + cell_width, y + cell_height],
            radius=18,
            fill=card,
            outline=line_color,
            width=1,
        )

        with Image.open(PRODUCTS_DIR / f"{product['sku']}.webp") as source:
            thumb = ImageOps.fit(source.convert("RGB"), (thumb_width, thumb_height), Image.Resampling.LANCZOS)
        canvas.paste(thumb, (x, y), _rounded_mask((thumb_width, thumb_height), 14))
        draw.rounded_rectangle(
            [x, y, x + thumb_width - 1, y + thumb_height - 1],
            radius=14,
            outline=(54, 51, 46),
            width=1,
        )

        chip = f"{index + 1:02d}"
        chip_font = _font(18)
        chip_width = draw.textlength(chip, font=chip_font)
        draw.rounded_rectangle(
            [x + 14, y + 14, x + 14 + chip_width + 20, y + 48],
            radius=17,
            fill=(8, 8, 12),
            outline=(74, 67, 54),
            width=1,
        )
        draw.text((x + 24, y + 21), chip, font=chip_font, fill=gold)

        name_font = _fit_text(draw, product["name"], cell_width - 24, 32, bold=True, min_size=22)
        draw.text((x + 12, y + thumb_height + 12), product["name"], font=name_font, fill=ivory)

        badge = sources.get(product["sku"], "未知")
        badge_font = _font(15)
        badge_width = draw.textlength(badge, font=badge_font) + 22
        if badge == "下载":
            badge_fill, badge_line, badge_text = (30, 27, 21), (116, 100, 68), gold
        else:
            badge_fill, badge_line, badge_text = (25, 25, 30), (76, 76, 84), (176, 176, 184)
        draw.rounded_rectangle(
            [x + cell_width - 12 - badge_width, y + thumb_height + 54, x + cell_width - 12, y + thumb_height + 82],
            radius=14,
            fill=badge_fill,
            outline=badge_line,
            width=1,
        )
        draw.text(
            (x + cell_width - 12 - badge_width + 11, y + thumb_height + 59),
            badge,
            font=badge_font,
            fill=badge_text,
        )

        meta = f'{product["category"]} · {product["sku"].upper()}'
        meta_font = _fit_text(draw, meta, cell_width - 24 - badge_width - 8, 19, min_size=14)
        draw.text((x + 12, y + thumb_height + 57), meta, font=meta_font, fill=muted)

    grid_bottom = header_height + rows * cell_height + (rows - 1) * gap
    draw.line([(margin, grid_bottom + 20), (canvas_width - margin, grid_bottom + 20)], fill=line_color, width=1)
    downloaded = sum(1 for value in sources.values() if value == "下载")
    fallback = sum(1 for value in sources.values() if value == "兜底")
    left = f"清单：backend/app/static/images/manifest.json · 下载 {downloaded} 件 / 本地生成兜底 {fallback} 件"
    right = "全部素材本地化 · 运行时零外链"
    footer_font = _font(19)
    draw.text((margin, grid_bottom + 38), left, font=footer_font, fill=muted)
    right_width = draw.textlength(right, font=footer_font)
    draw.text((canvas_width - margin - right_width, grid_bottom + 38), right, font=footer_font, fill=muted)

    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, "WEBP", quality=90, method=6)
    print(f"Contact sheet: {output} ({canvas_width}x{canvas_height})")
    return output


def _check_image(path: Path, minimum: tuple[int, int] | None = None) -> list[str]:
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            problems = []
            if image.format != "WEBP":
                problems.append(f"{path.relative_to(ROOT)}：格式为 {image.format}，应为 WEBP")
            if minimum and (image.width < minimum[0] or image.height < minimum[1]):
                problems.append(
                    f"{path.relative_to(ROOT)}：尺寸 {image.width}×{image.height}，应不小于 {minimum[0]}×{minimum[1]}"
                )
            return problems
    except FileNotFoundError:
        return [f"缺少文件：{path.relative_to(ROOT)}"]
    except OSError as exc:
        return [f"无法解码：{path.relative_to(ROOT)}（{exc}）"]


def verify_assets(deep: bool = True) -> bool:
    """Validate the local asset set and manifest, printing a Chinese report."""
    problems: list[str] = []
    checked = 0
    for product in PRODUCTS:
        for suffix in ("", "-alt1", "-alt2"):
            path = PRODUCTS_DIR / f"{product['sku']}{suffix}.webp"
            if not path.exists():
                problems.append(f"缺少文件：{path.relative_to(ROOT)}")
                continue
            try:
                with Image.open(path) as image:
                    image.verify()
                with Image.open(path) as image:
                    if image.format != "WEBP":
                        problems.append(f"{path.relative_to(ROOT)}：格式为 {image.format}，应为 WEBP")
                    elif image.size != (900, 1200):
                        problems.append(
                            f"{path.relative_to(ROOT)}：尺寸 {image.size[0]}×{image.size[1]}，应为 900×1200"
                        )
                checked += 1
            except OSError as exc:
                problems.append(f"无法解码：{path.relative_to(ROOT)}（{exc}）")

    hero_passed = 0
    for name, minimum in (
        ("hero/hero-1.webp", (1200, 800)),
        ("hero/hero-2.webp", (1200, 800)),
        ("hero/hero-3.webp", (1200, 800)),
        ("samples/outfit-demo.webp", (900, 1200)),
    ):
        found = _check_image(IMAGES / name, minimum=minimum)
        problems.extend(found)
        if not found:
            hero_passed += 1

    downloaded: set[str] = set()
    fallback: set[str] = set()
    manifest_ok = True
    manifest_path = IMAGES / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for key in ("downloaded", "fallback"):
            value = manifest.get(key)
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                problems.append(f"manifest.json：{key} 应为字符串数组")
                manifest_ok = False
        if manifest_ok:
            downloaded = set(manifest["downloaded"])
            fallback = set(manifest["fallback"])
            if len(downloaded) != len(manifest["downloaded"]) or len(fallback) != len(manifest["fallback"]):
                problems.append("manifest.json：存在重复 SKU")
            if downloaded & fallback:
                problems.append(f"manifest.json：SKU 同时出现在两个来源列表：{sorted(downloaded & fallback)}")
            catalog = {product["sku"] for product in PRODUCTS}
            missing = sorted(catalog - (downloaded | fallback))
            extra = sorted((downloaded | fallback) - catalog)
            if missing:
                problems.append(f"manifest.json：缺少 SKU {missing}")
            if extra:
                problems.append(f"manifest.json：出现未知 SKU {extra}")
    except (OSError, json.JSONDecodeError) as exc:
        problems.append(f"manifest.json 无法读取或解析：{exc}")
        manifest_ok = False

    if deep and manifest_ok:
        # Pixel-compare stored mains with freshly generated fallbacks: catches a wrong source label.
        for product in PRODUCTS:
            sku = product["sku"]
            path = PRODUCTS_DIR / f"{sku}.webp"
            if not path.exists():
                continue
            with Image.open(path) as stored:
                stored_rgb = stored.convert("RGB")
            diff = ImageStat.Stat(ImageChops.difference(stored_rgb, generate_fallback(product))).mean
            is_generated = sum(diff) / len(diff) < 8
            labelled_generated = sku in fallback
            if is_generated != labelled_generated:
                problems.append(
                    f"manifest.json：{sku} 来源标注与主图文件不一致（标注为{'兜底' if labelled_generated else '下载'}）"
                )

    if CONTACT_SHEET.exists():
        problems.extend(_check_image(CONTACT_SHEET))
    else:
        print("提示：docs/assets-contact-sheet.webp 尚未生成（可运行 --contact-sheet）。")

    print("=== 商品素材质检 ===")
    print(f"商品图：{checked}/{len(PRODUCTS) * 3} 张可解码（WebP 900×1200）")
    print(f"hero / 样例图：{hero_passed}/4 张通过")
    if manifest_ok:
        print(f"manifest：下载 {len(downloaded)} 件 / 兜底 {len(fallback)} 件")
    if problems:
        print(f"发现 {len(problems)} 个问题：")
        for problem in problems:
            print(f" - {problem}")
        print("结论：未通过")
        return False
    print("结论：全部通过（WebP 可读、尺寸 900×1200、manifest 与文件一致）")
    return True


def main() -> None:
    try:  # Windows Git Bash 默认 GBK 管道理应输出 UTF-8 中文
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    parser = argparse.ArgumentParser(description="衣见 ATELIER 本地素材构建与质检")
    parser.add_argument("--verify", action="store_true", help="仅校验既有素材与 manifest，不下载、不重建")
    parser.add_argument("--contact-sheet", action="store_true", help="仅重新生成 docs/assets-contact-sheet.webp")
    parser.add_argument("--no-download", action="store_true", help="跳过 Unsplash 下载，全部使用本地生成兜底图")
    args = parser.parse_args()

    if args.verify:
        raise SystemExit(0 if verify_assets() else 1)
    if args.contact_sheet:
        build_contact_sheet()
        return

    report = build_products(download=not args.no_download)
    build_heroes()
    build_sample_outfit()
    build_fallback_svg()
    manifest = {
        "brand": "衣见 ATELIER",
        "source": "Curated Unsplash photos downloaded at build time; generated fallbacks otherwise.",
        "downloaded": report["downloaded"],
        "fallback": report["fallback"],
    }
    (IMAGES / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    build_contact_sheet()
    print(f"\nDone. downloaded={len(report['downloaded'])}, fallback={len(report['fallback'])}")
    print(f"Images: {IMAGES}")


if __name__ == "__main__":
    main()
