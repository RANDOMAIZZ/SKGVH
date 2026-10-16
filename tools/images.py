#!/usr/bin/env python3
"""
Пайплайн подготовки изображений для сайта СКГВХ.

Что делает:
  * smart-crop + ресайз исходных фото под нужные пропорции
  * «ремонт» выцветших снимков (mash0003) — контраст/насыщенность/резкость
  * фирменная цветокоррекция (split-tone: тени -> тёмно-синий, света -> тёплый белый)
  * вывод в WebP + JPEG-fallback, ретина-версии
  * responsive-наборы для hero / баннеров / галереи
  * favicon-набор + PWA-иконки из исходного favicon.ico
  * OG-картинка для соцсетей 1200x630

Запуск:  python tools/images.py
Результат: public/img/... , public/favicon*
"""

import json
import math
import os
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps, ImageStat

# Консоль Windows по умолчанию cp1251 — принудительно UTF-8, иначе падает на «→»
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "assets-src"
OUT = ROOT / "public"

# ── фирменная палитра (см. src/data/site.json — держим в синхроне) ───────────────
NAVY = (8, 19, 46)        # тени
BLUE = (75, 126, 255)     # основной синий из логотипа
AQUA = (56, 189, 248)     # акцент «вода»
WARM = (255, 246, 235)    # света

QUALITY_WEBP = 82
QUALITY_JPEG = 84
# Фоновая фотография занимает весь первый экран, поэтому даже заметная
# потеря качества на ней незаметна, а трафик экономится заметно
HERO_QUALITY = 72

_img_index: list[dict] = []


# ────────────────────────────────────────────────────────────────────────────────
# Утилиты
# ────────────────────────────────────────────────────────────────────────────────
def load(rel: str) -> Image.Image:
    """Открыть исходник и привести к RGB."""
    p = SRC / rel
    if not p.exists():
        raise SystemExit(f"[!] Нет исходника: {p}")
    im = Image.open(p)
    if im.mode in ("P", "LA", "L"):
        im = im.convert("RGBA")
    if im.mode == "RGBA":
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[3])
        im = bg
    return im.convert("RGB")


def smart_crop(im: Image.Image, ratio: float, anchor: float = 0.5) -> Image.Image:
    """
    Кадрирование под соотношение сторон ratio (w/h).
    anchor — вертикальный центр кадра (0 = верх, 0.5 = середина, 1 = низ).
    Для пейзажей с небом сверху обычно нужен anchor ~0.6-0.8, чтобы
    гора осталась в кадре, а сверху было место под текст.
    """
    w, h = im.size
    cur = w / h
    if cur > ratio:                      # слишком широкий -> режем по ширине
        new_w = int(round(h * ratio))
        left = (w - new_w) // 2
        im = im.crop((left, 0, left + new_w, h))
    else:                                # слишком высокий -> режем по высоте
        new_h = int(round(w / ratio))
        top = int(round((h - new_h) * anchor))
        top = max(0, min(top, h - new_h))
        im = im.crop((0, top, w, top + new_h))
    return im


def _percentile_stretch(im: Image.Image, lo_p: float, hi_p: float) -> Image.Image:
    """Линейная растяжка каждого канала между перцентилями гистограммы.

    Мягче, чем ImageOps.autocontrast: не выжигает шум и полосы JPEG,
    характерные для сильно выцветших снимков.
    """
    stretched = []
    for ch in im.split():
        hist = ch.histogram()
        total = sum(hist)
        lo_target = lo_p / 100.0 * total
        hi_target = hi_p / 100.0 * total

        lo = 0
        hi = 255
        cum = 0
        lo_found = False
        for v, c in enumerate(hist):
            cum += c
            if not lo_found and cum >= lo_target:
                lo = v
                lo_found = True
            if cum >= hi_target:
                hi = v
                break
        if hi <= lo:
            hi = lo + 1

        scale = 255.0 / (hi - lo)
        lut = [max(0, min(255, int(round((v - lo) * scale)))) for v in range(256)]
        stretched.append(ch.point(lut))
    return Image.merge(im.mode, stretched)


def restore(im: Image.Image, strength: float = 1.0) -> Image.Image:
    """
    Реанимация выцветшего снимка (mash0003: std всего 8/7/12 — почти плоский).

    Порядок важен: сначала мягкая перцентильная растяжка, затем медианный
    фильтр (гасит усиленный шум и полосы квантования), и только потом
    лёгкий unsharp + скромный буст насыщенности.
    """
    if strength <= 0:
        return im

    #Чем «глуше» снимок, тем шире окно растяжки
    st = ImageStat.Stat(im.convert("RGB"))
    flatness = 1.0 - min(1.0, (sum(st.stddev) / 3.0) / 24.0)

    lo_p = 0.5 + 1.5 * flatness
    hi_p = 99.5 - 1.5 * flatness

    out = _percentile_stretch(im, lo_p, hi_p)

    # Денойзинг: радиус тем больше, чем площе исходник
    size = 3 if flatness < 0.6 else 5
    out = out.filter(ImageFilter.MedianFilter(size))

    out = ImageEnhance.Color(out).enhance(1.0 + 0.16 * strength)
    out = ImageEnhance.Contrast(out).enhance(1.0 + 0.06 * strength)
    out = out.filter(ImageFilter.UnsharpMask(radius=2, percent=int(55 * strength), threshold=4))
    return out


def split_tone(im: Image.Image, amount: float = 0.30) -> Image.Image:
    """
    Фирменная цветокоррекция: тени уходят в тёмно-синий, света — в тёплый белый.
    amount 0 = исходник, 1 = максимум выраженности.
    """
    if amount <= 0:
        return im
    grey = im.convert("L")

    # Карты: тени -> NAVY, света -> WARM
    shadow_map = ImageOps.colorize(grey, black=NAVY, white=(128, 138, 160))
    light_map = ImageOps.colorize(grey, black=(70, 88, 120), white=WARM)

    toned = Image.blend(im, shadow_map, amount * 0.55)
    toned = Image.blend(toned, light_map, amount * 0.30)

    # Вернуть немного «водного» синего в средние тона
    aqua_map = ImageOps.colorize(grey, black=NAVY, white=AQUA)
    toned = Image.blend(toned, aqua_map, amount * 0.12)
    return toned


def balance_channels(im: Image.Image, r: float = 1.0, g: float = 1.0, b: float = 1.0) -> Image.Image:
    """Подкрутка каналовRGB множителями — грубая, но действенная
    коррекция цветового отсвета (например, зелёного каста на скане)."""
    if (r, g, b) == (1.0, 1.0, 1.0):
        return im
    chans = list(im.split())
    gains = (r, g, b)
    for i, gain in enumerate(gains):
        if gain == 1.0 or i >= len(chans):
            continue
        lut = [min(255, int(round(v * gain))) for v in range(256)]
        chans[i] = chans[i].point(lut)
    return Image.merge(im.mode, chans)


def grade(im: Image.Image, tone: float = 0.30, contrast: float = 1.06,
          saturate: float = 1.10, sharp: bool = True) -> Image.Image:
    """Единая «фирменная» обработка кадра."""
    out = ImageEnhance.Color(im).enhance(saturate)
    out = ImageEnhance.Contrast(out).enhance(contrast)
    out = split_tone(out, tone)
    if sharp:
        out = out.filter(ImageFilter.UnsharpMask(radius=1, percent=70, threshold=3))
    return out


def darken_for_text(im: Image.Image, strength: float = 0.30) -> Image.Image:
    """
    Затемнить нижнюю часть кадра градиентом, чтобы белый текст поверх
    гарантированно проходил по WCAG AA. Возвращает RGB.
    """
    w, h = im.size
    overlay = Image.new("L", (1, h))
    px = overlay.load()
    for y in range(h):
        t = y / max(1, h - 1)
        # 0 сверху -> strength к низу, с плавным нарастанием
        px[0, y] = int(255 * strength * (t ** 1.6))
    mask = overlay.resize((w, h))
    dark = Image.new("RGB", (w, h), NAVY)
    return Image.composite(dark, im, mask)


def save(im: Image.Image, name: str, *, webp: bool = True, jpeg: bool = True,
         baseline: int | None = None, quality: int | None = None) -> None:
    """Сохранить в public/img, зарегистрировать для srcset-манифеста.

    quality — переопределение WebP-качества для отдельных файлов.
    Фоновая картинка большого размера tolerает к сжатию лучше,
    чем галерея, поэтому для неё качество ниже.
    """
    dest_dir = OUT / "img"
    dest_dir.mkdir(parents=True, exist_ok=True)
    stem = dest_dir / name

    made = []
    if jpeg:
        p = stem.with_suffix(".jpg")
        im.convert("RGB").save(p, "JPEG", quality=QUALITY_JPEG,
                               optimize=True, progressive=True, subsampling=1)
        made.append(p)
    if webp:
        p = stem.with_suffix(".webp")
        im.save(p, "WEBP", quality=quality or QUALITY_WEBP, method=6)
        made.append(p)

    w, h = im.size
    entry = {"name": stem.name, "w": w, "h": h}
    if baseline is not None:
        entry["base"] = baseline
    _img_index.append(entry)


def resize_to(im: Image.Image, width: int, ratio: float | None = None,
              anchor: float = 0.5) -> Image.Image:
    if ratio:
        im = smart_crop(im, ratio, anchor)
    h = max(1, int(round(im.size[1] * width / im.size[0])))
    return im.resize((width, h), Image.LANCZOS)


# ────────────────────────────────────────────────────────────────────────────────
# 1. HERO — главный баннер из mash0001
# ────────────────────────────────────────────────────────────────────────────────
def build_hero() -> None:
    print("→ hero (mash0001)")
    src = load("img/mash0001.jpg")

    # Кадр 16:9, смещённый вниз: гора и вышка в кадре, сверху — небо под заголовок
    base = smart_crop(src, 16 / 9, anchor=0.72)
    base = grade(base, tone=0.22, contrast=1.06, saturate=1.06)
    # Затемнение внутри картинки минимальное: сайт тёмный, и текст закрывает
    # CSS-скрим. Прежнее значение 0.34 «съедало» саму фотографию.
    base = darken_for_text(base, strength=0.12)

    for w in (1920, 1440, 1024, 768, 480):
        save(resize_to(base, w), f"hero-{w}", baseline=1920, quality=HERO_QUALITY)

    # Квадратная/портретная обрезка для мобильного hero
    mob = smart_crop(src, 4 / 5, anchor=0.80)
    mob = grade(mob, tone=0.22, contrast=1.05, saturate=1.05)
    mob = darken_for_text(mob, strength=0.40)
    for w in (900, 560):
        save(resize_to(mob, w), f"hero-m-{w}", baseline=900, quality=HERO_QUALITY)


# ────────────────────────────────────────────────────────────────────────────────
# 2. ШИРОКИЙ БАННЕР из mash0002
# ────────────────────────────────────────────────────────────────────────────────
def build_banner() -> None:
    print("→ banner (mash0002)")
    src = load("img/mash0002.jpg")
    base = smart_crop(src, 1920 / 560, anchor=0.55)
    base = grade(base, tone=0.32, contrast=1.07, saturate=1.12)
    base = darken_for_text(base, strength=0.30)
    for w in (1920, 1280, 800):
        save(resize_to(base, w), f"banner-{w}", baseline=1920)


# ────────────────────────────────────────────────────────────────────────────────
# 3. ГАЛЕРЕЯ — включая «ремонт» выцветшего mash0003
# ────────────────────────────────────────────────────────────────────────────────
def build_gallery() -> None:
    print("→ gallery")
    plan = [
        ("img/mash0001.jpg", "g-mashuk-01", False, 4 / 3, 0.55),
        ("img/mash0002.jpg", "g-mashuk-02", False, 4 / 3, 0.50),
        # mash0003.jpg исключён намеренно: исходник некачественный
        # (std = 8/7/12, размытый JPEG), реставрация даёт неон и пятна —
        # лучше 4 хороших кадра, чем 5 с одним плохим.
        ("img/Znakomtes_Konstantin_Nosov.jpg", "g-nosov-book", False, 4 / 3, 0.50),
        ("img/nosovkn.gif", "g-nosov-portrait", False, 4 / 5, 0.45),
    ]

    # Портрет — единственный кадр, где фирменный split-tone неуместен:
    # в исходном GIF сильный зелёный отсвет, а тонирование в холод усугубляет
    # его до отвратительного. Поэтому tone = 0 и ручная компенсация канала.
    portrait_balance = {"g-nosov-portrait": (1.06, 0.95, 0.99)}

    for rel, name, needs_restore, ratio, anchor in plan:
        im = load(rel)
        tone, sat = 0.24, 1.08
        if needs_restore:
            im = restore(im, strength=1.0)
            # Восстановленный кадр нельзя дополнительно тонировать —
            # он и так на пределе, лишний split-tone даёт неон
            tone, sat = 0.10, 1.04
        if name in portrait_balance:
            tone, sat = 0.0, 1.02
        im = smart_crop(im, ratio, anchor)

        if name in portrait_balance:
            im = balance_channels(im, *portrait_balance[name])

        im = grade(im, tone=tone, contrast=1.05, saturate=sat)
        for w in (1200, 800, 480):
            save(resize_to(im, w), f"{name}-{w}", baseline=1200)


# ────────────────────────────────────────────────────────────────────────────────
# 4. ЛОГОТИПЫ
# ────────────────────────────────────────────────────────────────────────────────
def build_logos() -> None:
    print("→ logos")
    src = load("img/logo-blue-black100.png")

    # Основной — с прозрачностью, для шапки на светлом
    for w in (64, 40, 32):
        r = src.resize((w, w), Image.LANCZOS)
        p = OUT / "img" / f"logo-{w}.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        r.save(p, "PNG", optimize=True)
        _img_index.append({"name": f"img/{p.name}", "w": w, "h": w})

    # Светлая версия для тёмного футера: перекрасить в белый, сохранить альфу
    blue = Image.open(SRC / "img/logo-blue-black100.png").convert("RGBA")
    alpha = blue.split()[3]
    white = Image.new("RGBA", blue.size, (255, 255, 255, 0))
    white.putalpha(alpha)
    for w in (48, 32):
        r = white.resize((w, w), Image.LANCZOS)
        p = OUT / "img" / f"logo-white-{w}.png"
        r.save(p, "PNG", optimize=True)

    # Полноцветный логотип для OG и печати
    p = OUT / "img" / "logo-full.png"
    src.resize((256, 256), Image.LANCZOS).save(p, "PNG", optimize=True)


# ────────────────────────────────────────────────────────────────────────────────
# 5. FAVICON-набор + PWA-иконки
# ────────────────────────────────────────────────────────────────────────────────
def build_icons() -> None:
    print("→ icons")
    src = Image.open(SRC / "favicon.ico")

    # apple-touch-icon — 180x180, без прозрачности (iOS сам рисует скругления)
    ap = src.convert("RGBA").resize((180, 180), Image.LANCZOS)
    bg = Image.new("RGBA", (180, 180), (255, 255, 255, 255))
    bg.alpha_composite(ap)
    bg.convert("RGB").save(OUT / "apple-touch-icon.png", "PNG", optimize=True)

    # maskable icon — с безопасным полем (зона маски = центральные 80%)
    for w in (192, 512):
        base = Image.open(SRC / "img/logo-blue-black100.png").convert("RGBA")
        canvas = Image.new("RGBA", (w, w), (8, 19, 46, 255))
        inner = base.resize((int(w * 0.62), int(w * 0.62)), Image.LANCZOS)
        canvas.alpha_composite(inner, ((w - inner.size[0]) // 2, (w - inner.size[1]) // 2))
        canvas.save(OUT / f"icon-{w}.png", "PNG", optimize=True)

    # favicon.ico со всеми размерами
    frames = [src.convert("RGBA").resize((s, s), Image.LANCZOS) for s in (16, 32, 48)]
    frames[0].save(OUT / "favicon.ico", format="ICO",
                   sizes=[(16, 16), (32, 32), (48, 48)],
                   append_images=frames[1:])

    # favicon.svg — векторная обёртка (современные браузеры)
    svg = OUT / "favicon.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<rect width="100" height="100" rx="18" fill="#0d1f4d"/>'
        '<path d="M50 14 59 40 86 32 67 52 86 72 59 64 50 90 41 64 14 72 33 52 14 32 41 40Z" '
        'fill="#4b7eff"/>'
        "</svg>\n", encoding="utf-8")


# ────────────────────────────────────────────────────────────────────────────────
# 6. OG-КАРТИНКА 1200x630
# ────────────────────────────────────────────────────────────────────────────────
def build_og() -> None:
    print("→ og-image")
    src = load("img/mash0001.jpg")
    # smart_crop только кадрирует — приводим к точному размеру OG-картинки
    base = resize_to(smart_crop(src, 1200 / 630, anchor=0.70), 1200)
    if base.size != (1200, 630):
        base = smart_crop(base, 1200 / 630, anchor=0.5).resize((1200, 630), Image.LANCZOS)
    base = grade(base, tone=0.26, contrast=1.06, saturate=1.04)
    base = darken_for_text(base, strength=0.55)

    d = ImageDraw.Draw(base, "RGBA")
    d.rectangle([0, 0, 1200, 630], fill=(8, 19, 46, 110))
    d.rectangle([64, 300, 72, 430], fill=(75, 126, 255, 255))

    try:
        title_font = ImageFont.truetype("arialbd.ttf", 60)
        sub_font = ImageFont.truetype("arial.ttf", 29)
    except OSError:
        title_font = ImageFont.load_default()
        sub_font = ImageFont.load_default()

    d.text((100, 316), "СЕВКАВГИПРОВОДХОЗ", font=title_font, fill=(255, 255, 255, 255))
    d.text((100, 396), "Проектирование · Изыскания · Мелиорация", font=sub_font,
           fill=(196, 218, 255, 255))

    assert base.size == (1200, 630), f"OG должен быть 1200x630, получено {base.size}"
    base.save(OUT / "img" / "og-image.jpg", "JPEG", quality=86, optimize=True, progressive=True)
    _img_index.append({"name": "img/og-image.jpg", "w": 1200, "h": 630})


# ────────────────────────────────────────────────────────────────────────────────
def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"[!] Нет папки исходников: {SRC}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "img").mkdir(parents=True, exist_ok=True)

    build_hero()
    build_banner()
    build_gallery()
    build_logos()
    build_icons()
    build_og()

    # манифест размеров — build.py использует его для srcset/sizes
    manifest = OUT / "img" / "_manifest.json"
    manifest.write_text(json.dumps(_img_index, ensure_ascii=False, indent=1), encoding="utf-8")

    total = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    n = sum(1 for f in OUT.rglob("*") if f.is_file())
    print(f"\n[OK] {n} файлов, {total/1024:.0f} КБ → {OUT}")


if __name__ == "__main__":
    sys.exit(main())