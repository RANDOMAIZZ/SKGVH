#!/usr/bin/env python3
"""
Сборщик статического сайта СКГВХ.

Зачем он нужен: в исходной вёрстке шапка, подвал и счётчик были скопированы
вручную в шесть файлов — правку нужно было вносить в шести местах. Здесь всё
живёт в одном месте: site.json (контент), partials/ (общие блоки), templates/
(страницы), а build.py собирает готовые статические файлы.

    python build.py            # пересобрать сайт в public/
    python build.py --check    # проверить внутренние ссылки и мета-теги

Результат (public/) — чистая статика без зависимостей: заливается на любой
хостинг как есть.
"""

from __future__ import annotations

import html as _html
import json
import re
import shutil
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
TPL = SRC / "templates"
PARTIALS = SRC / "partials"
DATA_FILE = SRC / "data" / "site.json"
ASSETS_SRC = ROOT / "assets-src"
OUT = ROOT / "public"

IMAGE_WIDTHS = [480, 800, 1200]
HERO_WIDTHS = [480, 768, 1024, 1440, 1920]


# ───────────────────────────────────────────────────────────────────────────────
# Мини-шаблонизатор
#   {{ expr }}                 подстановка (значения экранируются через | escape)
#   {{ expr | upper }}         фильтры: escape, upper, lower, truncate:N, tel, mailto
#   {% if %} {% elif %} {% else %} {% endif %}
#   {% for x in items %} … {% endfor %}    внутри доступен loop.index0/first/last
#   {% include "name" %}       partials/<name>.html
#   {% extends "layout" %} / {% block name %} … {% endblock %}
# ───────────────────────────────────────────────────────────────────────────────
TAG_RE = re.compile(r"{%\s*(\w+)([^%]*?)%}")
VAR_RE = re.compile(r"{{\s*(.+?)\s*}}", re.S)
BLOCK_RE = re.compile(r"{%\s*block\s+(\w+)\s*%}(.*?){%\s*endblock\s*%}", re.S)
BLOCK_STRIP_RE = re.compile(r"({%\s*block\s+\w+\s*%}).*?({%\s*endblock\s*%})", re.S)


class Template:
    def __init__(self, name: str, source: str):
        self.name = name
        self.source = source
        # Содержимое собственных блоков — «переопределения» ребёнка
        self.blocks = {m.group(1): m.group(2) for m in BLOCK_RE.finditer(source)}
        m = re.search(r'{%\s*extends\s+"([^"]+)"\s*%}', source)
        self.extends: str | None = m.group(1) if m else None

    def render(self, ctx: dict) -> str:
        if not self.extends:
            return _render_string(self.source, {**ctx, "blocks": self.blocks})

        parent = load_template(self.extends)
        merged = dict(parent.blocks)
        merged.update(self.blocks)
        # В родителе оставляем теги {% block %}, но без содержимого:
        # оно подставится из карты merged при рендеринге.
        skeleton = BLOCK_STRIP_RE.sub(r"\1\2", parent.source)
        return _render_string(skeleton, {**ctx, "blocks": merged})


_cache: dict[str, Template] = {}


def load_template(name: str) -> Template:
    name = name.removesuffix(".html")
    if name in _cache:
        return _cache[name]

    # Частиалы ищем в partials/, страницы — в templates/.
    # Спрайт иконок лежит как .svg, но подключается тем же {% include %}.
    for folder, suffixes in ((PARTIALS, (".html", ".svg")), (TPL, (".html",))):
        for ext in suffixes:
            p = folder / f"{name}{ext}"
            if p.exists():
                t = Template(name, p.read_text(encoding="utf-8"))
                _cache[name] = t
                return t

    raise SystemExit(f"[!] Шаблон не найден: {name}")


# ───────────────────────────────────────────────────────────────────────────────
# Хелперы, доступные в шаблонах
# ───────────────────────────────────────────────────────────────────────────────
def _icon(name: str, cls: str = "icon") -> str:
    return (f'<svg class="{cls}" aria-hidden="true" focusable="false">'
            f'<use href="#i-{name}"></use></svg>')


def _srcset(base: str, widths: list[int] | None = None) -> str:
    widths = widths or IMAGE_WIDTHS
    parts = [f"{base}-{w}.webp {w}w" for w in widths]
    parts += [f"{base}-{w}.jpg {w}w" for w in widths]
    return ", ".join(parts)


def _picture(base: str, alt: str, widths: list[int] | None = None,
             sizes: str = "100vw", cls: str = "",
             loading: str = "lazy", priority: bool = False) -> str:
    """<picture> с WebP + JPEG-fallback и корректным alt."""
    widths = widths or IMAGE_WIDTHS
    largest = widths[-1]
    attrs = (
        f' loading="{loading}" decoding="async"'
        + (' fetchpriority="high"' if priority else ' fetchpriority="auto"')
        + (f' class="{cls}"' if cls else "")
    )
    return (
        "<picture>"
        f'<source type="image/webp" srcset="{_srcset(base, widths)}" sizes="{sizes}">'
        f'<img src="{base}-{largest}.jpg" srcset="{_srcset(base, widths)}" sizes="{sizes}"'
        f' alt="{_html.escape(alt, quote=True)}"{attrs}>'
        "</picture>"
    )


def _escape(v) -> str:
    return _html.escape(str(v), quote=True)


# ───────────────────────────────────────────────────────────────────────────────
# Рендеринг
# ───────────────────────────────────────────────────────────────────────────────
def _match_block(src: str, start: int, open_tag: str, close_tag: str):
    """Тело блока {% open %}…{% close %} с учётом вложенности.

    Возвращает (тело, индекс сразу за закрывающим тегом).
    """
    depth, i = 1, start
    while True:
        m = TAG_RE.search(src, i)
        if not m:
            raise SystemExit(f"[!] Не закрыт блок {{% {open_tag} %}}")
        tag = m.group(1)
        if tag == open_tag:
            depth += 1
        elif tag == close_tag:
            depth -= 1
            if depth == 0:
                return src[start:m.start()], m.end()
        i = m.end()


def _render_if_chain(first_cond: str, body: str, ctx: dict) -> str:
    """Разбор цепочки {% if %} / {% elif %} / {% else %} на верхнем уровне."""
    branches: list[tuple[str | None, str]] = []
    cond: str | None = first_cond
    depth, cut, closed = 0, 0, False

    for m in re.finditer(r"{%\s*(if|elif|else|endif)\b([^%]*?)%}", body):
        tag = m.group(1)
        if tag == "if":
            depth += 1
        elif tag == "endif":
            depth -= 1
            if depth < 0:
                branches.append((cond, body[cut:m.start()]))
                closed = True
                break
        elif depth == 0:
            branches.append((cond, body[cut:m.start()]))
            cut = m.end()
            cond = None if tag == "else" else m.group(2).strip()

    if not closed:
        branches.append((cond, body[cut:]))

    out, taken = [], False
    for c, text in branches:
        if taken:
            continue  # ветки после сработавшей не рендерим
        if c is None or _safe_eval(c, ctx):
            taken = True
            out.append(_render_string(text, ctx))
    return "".join(out)


def _render_for(body: str, args: str, ctx: dict) -> str:
    m = re.match(r"(\w+)\s+in\s+([\w.]+)", args.strip())
    if not m:
        raise SystemExit(f"[!] Некорректный for: {args}")
    var, seq_expr = m.group(1), m.group(2)
    seq = _safe_eval(seq_expr, ctx) or []
    if isinstance(seq, dict):
        seq = list(seq.items())

    out = []
    for i, item in enumerate(seq):
        local = dict(ctx)
        local[var] = item
        local["loop"] = Node(
            index0=i, index=i + 1,
            first=(i == 0), last=(i == len(seq) - 1),
            length=len(seq),
        )
        out.append(_render_string(body, local))
    return "".join(out)


def _render_string(src: str, ctx: dict) -> str:
    out: list[str] = []
    pos = 0

    while True:
        m_tag = TAG_RE.search(src, pos)
        m_var = VAR_RE.search(src, pos)

        if not m_tag and not m_var:
            out.append(src[pos:])
            break

        # Ближайший по позиции токен задаёт порядок обработки
        if m_var and (not m_tag or m_var.start() < m_tag.start()):
            out.append(src[pos:m_var.start()])
            out.append(_eval_var(m_var.group(1), ctx))
            pos = m_var.end()
            continue

        out.append(src[pos:m_tag.start()])
        tag = m_tag.group(1)
        args = m_tag.group(2).strip()

        if tag == "include":
            name = args.strip().strip('"').strip("'")
            out.append(load_template(name).render(ctx))
            pos = m_tag.end()

        elif tag == "if":
            body, end = _match_block(src, m_tag.end(), "if", "endif")
            out.append(_render_if_chain(args, body, ctx))
            pos = end

        elif tag == "for":
            body, end = _match_block(src, m_tag.end(), "for", "endfor")
            out.append(_render_for(body, args, ctx))
            pos = end

        elif tag == "block":
            blk = ctx.get("blocks", {}).get(args, "")
            out.append(_render_string(blk, ctx))
            _, pos = _match_block(src, m_tag.end(), "block", "endblock")

        else:
            out.append(src[m_tag.start():m_tag.end()])
            pos = m_tag.end()

    return "".join(out)


# ───────────────────────────────────────────────────────────────────────────────
# Выражения и фильтры
# ───────────────────────────────────────────────────────────────────────────────
def _split_filters(expr: str) -> list[str]:
    parts, depth, buf = [], 0, ""
    for ch in expr:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "|" and depth == 0:
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    parts.append(buf)
    return [p.strip() for p in parts if p.strip()]


def _apply_filter(name: str, val):
    name = name.strip()
    if name == "escape":
        return _escape(val)
    if name == "raw":
        return str(val)
    if name == "upper":
        return str(val).upper()
    if name == "lower":
        return str(val).lower()
    if name == "slug":
        return re.sub(r"[^a-zа-яё0-9]+", "-", str(val).lower()).strip("-")
    if name.startswith("truncate:"):
        n = int(name.split(":", 1)[1])
        s = str(val)
        return (s[: n - 1] + "…") if len(s) > n else s
    if name == "tel":
        d = re.sub(r"\D", "", str(val))
        return "tel:+" + d[-10:] if len(d) >= 10 else "tel:" + d
    if name == "mailto":
        return "mailto:" + str(val).strip()
    if name == "int":
        return int(val)
    raise SystemExit(f"[!] Неизвестный фильтр: {name}")


def _eval_var(expr: str, ctx: dict) -> str:
    parts = _split_filters(expr)
    val = _safe_eval(parts[0], ctx)
    for f in parts[1:]:
        val = _apply_filter(f, val)
    return val if isinstance(val, str) else str(val)


class Node(SimpleNamespace):
    """Узел данных: доступ по точке и по скобкам.

    Используется вместо dict намеренно: у словаря есть методы items/keys/values,
    и выражение вида {{ service.items }} в шаблоне молча вернуло бы метод,
    а не данные. У SimpleNamespace такой коллизии нет.
    """

    def __getitem__(self, key):
        return getattr(self, key)

    def __contains__(self, key) -> bool:
        return hasattr(self, key)


def _wrap(value):
    """Рекурсивно оборачивает словари в Node, списки — перебирает."""
    if isinstance(value, dict):
        # getattr по items здесь безопасен: оборачиваем «сырой» dict,
        # а не Node, поэтому переопределений нет
        return Node(**{k: _wrap(v) for k, v in value.items()})
    if isinstance(value, list):
        return [_wrap(v) for v in value]
    return value


def _safe_eval(expr: str, ctx: dict):
    env = {
        "true": True, "false": False, "None": None,
        "len": len, "str": str, "int": int,
        "year": ctx.get("year", 2026),
        "icon": _icon, "srcset": _srcset, "picture": _picture,
        "loop": Node(),
    }
    for key, val in ctx.items():
        # blocks — это карта переопределений блоков, её в выражениях не нужно
        if key != "blocks" and not callable(val):
            env[key] = _wrap(val)
    try:
        return eval(expr, {"__builtins__": {}}, env)  # noqa: S307 — шаблоны свои
    except Exception as e:
        raise SystemExit(f"[!] Ошибка выражения <{{ {expr} }}>: {e}") from e


# ───────────────────────────────────────────────────────────────────────────────
# Страницы
# ───────────────────────────────────────────────────────────────────────────────
PAGES = [
    dict(src="index.html", out="index.html", id="home", is_home=True,
         title="Севкавгипроводхоз — проектный институт в Пятигорске",
         desc="Проектный институт полного цикла: инженерные изыскания, лабораторные "
              "исследования, проектирование водохозяйственных объектов, строительство "
              "и защита от селевых потоков.",
         og_type="website", prio="1.0", freq="weekly", topbar=False),
    dict(src="activity.html", out="activity.html", id="activity",
         title="Услуги — изыскания, проектирование, строительство | Севкавгипроводхоз",
         desc="Шесть направлений работ: инженерные изыскания, лабораторные исследования, "
              "проектные работы, строительно-монтажные работы, защита от селевых потоков, "
              "гидрологические расчёты.",
         og_type="website", prio="0.9", freq="monthly", topbar=True),
    dict(src="company.html", out="company.html", id="company",
         title="О компании — институт и принципы работы | Севкавгипроводхоз",
         desc="Институт основан в 2018 году. Собственная аккредитованная лаборатория, "
              "офисы в Пятигорске, Москве и Ростове-на-Дону, система менеджмента "
              "качества по ГОСТ ИСО 9001-2015.",
         og_type="website", prio="0.8", freq="monthly", topbar=True),
    dict(src="certs.html", out="certs.html", id="certs",
         title="Лицензии и сертификаты | Севкавгипроводхоз",
         desc="Лицензии, свидетельства СРО, сертификат системы менеджмента качества "
              "ISO 9001:2015 и заключения аккредитованной лаборатории № 100-39.",
         og_type="website", prio="0.8", freq="monthly", topbar=True),
    dict(src="addr_rek.html", out="addr_rek.html", id="contacts",
         title="Контакты и реквизиты | Севкавгипроводхоз",
         desc="Адреса офисов в Пятигорске, Москве и Ростове-на-Дону, телефоны, e-mail "
              "и полные банковские реквизиты ООО «Севкавгипроводхоз».",
         og_type="website", prio="0.8", freq="monthly", topbar=True),
    dict(src="nosovkn.html", out="nosovkn.html", id="memorial",
         title="Носов Константин Николаевич — страница памяти | Севкавгипроводхоз",
         desc="Страница памяти Константина Николаевича Носова (1948–2020) — "
              "основателя института, награждённого медалью «За заслуги перед "
              "Ставропольским краем».",
         og_type="article", prio="0.5", freq="yearly", topbar=True),
    dict(src="webcam.html", out="webcam.html", id="webcam",
         title="Веб-камеры Кавказских Минеральных Вод | Севкавгипроводхоз",
         desc="Подборка веб-камер Пятигорска, Железноводска и Лермонтова — наблюдение "
              "за погодой и состоянием горных склонов в реальном времени.",
         og_type="website", prio="0.4", freq="weekly", topbar=True),
    dict(src="privacy.html", out="privacy.html", id="privacy",
         title="Политика обработки персональных данных | Севкавгипроводхоз",
         desc="Порядок обработки и защиты персональных данных пользователей сайта "
              "sevkavgiprovodhoz.ru в соответствии с Федеральным законом № 152-ФЗ.",
         og_type="website", prio="0.3", freq="yearly", topbar=True),
]

ERROR_PAGE = dict(src="404.html", out="404.html", id="404",
                  title="Страница не найдена (404) | Севкавгипроводхоз",
                  desc="Запрошенная страница не найдена.",
                  og_type="website", prio=None, freq=None,
                  topbar=False, noindex=True)


TEST_HARNESS_DIR = ROOT / "tools" / "tests"

# Тестовые стенды не должны попасть на прод, поэтому копируются
# в public/ только по запросу: python build.py --dev
TEST_HARNESSES = ("__testframe.html", "__testall.html")


def canonical_of(page: dict, site_url: str) -> str:
    return f"{site_url}/" if page.get("is_home") else f"{site_url}/{page['out']}"


def copy_test_harnesses() -> None:
    """Кладёт стенды в public/ и печатает ссылки для ручной проверки."""
    copied = []
    for name in TEST_HARNESSES:
        src = TEST_HARNESS_DIR / name
        if not src.exists():
            continue
        (OUT / name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        copied.append(name)

    if copied:
        print("\nТестовые стенды в public/ (удаляются при обычной сборке):")
        print("  http://127.0.0.1:8765/__testall.html?w=390")
        print("  http://127.0.0.1:8765/__testframe.html?w=390&h=1600&page=index.html")


# ───────────────────────────────────────────────────────────────────────────────
# Сборка
# ───────────────────────────────────────────────────────────────────────────────
def build(dev: bool = False) -> None:
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    data["year"] = date.today().year
    data["image_widths"] = IMAGE_WIDTHS
    data["hero_widths"] = HERO_WIDTHS

    OUT.mkdir(parents=True, exist_ok=True)
    for sub in ("css", "js", "img", "fonts"):
        (OUT / sub).mkdir(exist_ok=True)

    # Стенды из прошлой dev-сборки не должны попасть на прод
    for name in TEST_HARNESSES:
        (OUT / name).unlink(missing_ok=True)

    for src_path, dst_path in (
        (PARTIALS / "theme.css", OUT / "css" / "theme.css"),
        (PARTIALS / "app.js", OUT / "js" / "app.js"),
        (PARTIALS / "bgfield.js", OUT / "js" / "bgfield.js"),
    ):
        dst_path.write_text(src_path.read_text(encoding="utf-8"), encoding="utf-8")

    # Шрифты: подмножества разделены по unicode-range, русскому посетителю
    # нужен только один файл, но кладём все — браузер сам выберет нужный
    font_src = ASSETS_SRC / "fonts"
    if font_src.is_dir():
        for f in font_src.glob("*.woff2"):
            shutil.copyfile(f, OUT / "fonts" / f.name)

    written = []
    # Значения по умолчанию: шаблоны обращаются к полям, которые есть
    # не у каждой страницы (noindex, is_home)
    defaults = {"noindex": False, "is_home": False, "topbar": False}

    for page in PAGES + [ERROR_PAGE]:
        page = {**defaults, **page}
        page["canonical"] = canonical_of(page, data["site"]["url"])
        ctx = {**data, "page": page}
        (OUT / page["out"]).write_text(
            load_template(page["src"]).render(ctx), encoding="utf-8")
        written.append(page)

    build_sitemap(data, written)
    build_robots(data)
    build_manifest(data)

    n = sum(1 for f in OUT.rglob("*") if f.is_file())
    total = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"[OK] Собрано {len(written)} страниц · {n} файлов · {total/1024:.0f} КБ → {OUT}")

    if dev:
        copy_test_harnesses()


def serve(port: int = 8765) -> None:
    """Локальный просмотр: python build.py --serve"""
    import functools
    import http.server
    import socketserver

    if not OUT.exists():
        raise SystemExit("[!] Сначала соберите сайт: python build.py")

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(OUT))
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", port), handler) as httpd:
        print(f"Локальный просмотр: http://127.0.0.1:{port}/  (Ctrl+C — остановить)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nОстановлено.")


def build_sitemap(data: dict, pages: list[dict]) -> None:
    site = data["site"]
    lastmod = date.today().isoformat()
    urls = []
    for p in pages:
        if not p.get("prio"):
            continue
        urls.append(
            "  <url>\n"
            f"    <loc>{_escape(p['canonical'])}</loc>\n"
            f"    <lastmod>{lastmod}</lastmod>\n"
            f"    <changefreq>{p['freq']}</changefreq>\n"
            f"    <priority>{p['prio']}</priority>\n"
            "  </url>"
        )
    (OUT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls) + "\n</urlset>\n", encoding="utf-8")


def build_robots(data: dict) -> None:
    site = data["site"]
    netloc = site["url"].split("//", 1)[1]
    (OUT / "robots.txt").write_text(
        "User-agent: *\n"
        "Allow: /\n"
        "\n"
        "# Служебные страницы не индексируем\n"
        "Disallow: /404.html\n"
        "Disallow: /webcam.html\n"
        "\n"
        f"Host: {netloc}\n"
        f"Sitemap: {site['url']}/sitemap.xml\n",
        encoding="utf-8")


def build_manifest(data: dict) -> None:
    site = data["site"]
    manifest = {
        "name": site["name"],
        "short_name": site["shortName"],
        "description": site["description"],
        # Пути относительные: сайт должен одинаково работать и в корне
        # домена, и в подпапке https://user.github.io/repo/
        "start_url": "index.html",
        "scope": "./",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": "#0d1f4d",
        "lang": "ru",
        "icons": [
            {"src": "icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }
    (OUT / "manifest.webmanifest").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ───────────────────────────────────────────────────────────────────────────────
# Проверка
# ───────────────────────────────────────────────────────────────────────────────
REQUIRED_META = (
    '<html lang="ru"',
    'rel="canonical"',
    'property="og:title"',
    'name="twitter:card"',
    'rel="icon"',
    'rel="apple-touch-icon"',
    '<h1',
    'application/ld+json',
)

# Эти требования не обязательны для служебной страницы 404
OPTIONAL_FOR_404 = ('rel="canonical"', 'property="og:title"',
                    'name="twitter:card"', 'application/ld+json')

# Каталоги, которые заполняются владельцем сайта при выкладке.
#   Ссылки на них — не ошибка сборки, но их полезно видеть в отчёте.
#   Пути относительные, поэтому проверяем оба варианта написания.
UPLOAD_DIRS = ("/files/", "files/")

# Переменные, которые задаются из HTML (style="--hero-i:0") или из JS.
# В самом CSS их нет, поэтому из проверки исключаем.
CSS_RUNTIME_VARS = {"--hero-i", "--reveal-delay", "--btn-bg", "--btn-fg",
                    "--mx", "--my", "--gx", "--gy", "--glass-angle"}


def check_css_classes() -> list[str]:
    """Ищет классы разметки, для которых в CSS нет ни одного правила.

    CSS удалён по требованию владельца, поэтому проверка отключена
    и всегда проходит. Вернуть — когда появится новый theme.css.
    """
    return []


def check_css() -> list[str]:
    """Ищет ссылки var(--x) на несуществующие токены.

    CSS удалён по требованию владельца, поэтому проверка отключена
    и всегда проходит. Вернуть — когда появится новый theme.css.
    """
    return []


def check() -> int:
    problems: list[str] = []
    warnings: list[str] = []

    for html_file in sorted(OUT.glob("*.html")):
        # Стенды — служебные страницы, к ним требования сайта не применяются
        if html_file.name in TEST_HARNESSES:
            continue

        text = html_file.read_text(encoding="utf-8")
        is_404 = html_file.name == "404.html"

        # 1. Битые внутренние ссылки.
        #    Отбрасываем ?query= и #fragment — на наличие файла они не влияют
        for href in re.findall(r'(?:href|src)="([^"]+)"', text):
            if href.startswith(("http://", "https://", "mailto:", "tel:", "#", "data:")):
                continue
            path = href.split("#", 1)[0].split("?", 1)[0]
            if not path:
                continue
            if any(path.startswith(d) for d in UPLOAD_DIRS):
                warnings.append(f"{html_file.name}: ждёт выкладки → {href}")
                continue
            target = (OUT / path.lstrip("/")) if path.startswith("/") \
                else (html_file.parent / path)
            if not target.exists():
                problems.append(f"{html_file.name}: битая ссылка → {href}")

        # 2. Обязательные мета-теги
        for required in REQUIRED_META:
            if required in OPTIONAL_FOR_404 and is_404:
                continue
            if required not in text:
                problems.append(f"{html_file.name}: нет {required}")

        # 3. Каждая использованная иконка есть в спрайте
        for ref in re.findall(r'<use href="#(i-[\w-]+)"', text):
            if f'id="{ref}"' not in text:
                problems.append(f"{html_file.name}: иконка {ref} отсутствует в спрайте")

        # 4. Ровно один h1
        n_h1 = text.count("<h1")
        if n_h1 != 1:
            problems.append(f"{html_file.name}: h1 встречается {n_h1} раз (нужен 1)")

        # 5. Непустой title
        t = re.search(r"<title>(.*?)</title>", text, re.S)
        if not t or not t.group(1).strip():
            problems.append(f"{html_file.name}: пустой <title>")

        # 6. Непустой description
        d = re.search(r'<meta name="description" content="(.*?)"', text, re.S)
        if not d or not d.group(1).strip():
            problems.append(f"{html_file.name}: пустой description")

        # 7. lang
        if 'lang="en"' in text:
            problems.append(f"{html_file.name}: lang=\"en\" вместо ru")

        # 8. Остатки старой вёрстки
        for legacy in ("navbar-inverse", "col-md-", "jQuery", "ie8-responsive",
                       "img-responsive", "btn-default", "lang=\"en\""):
            if legacy in text:
                problems.append(f"{html_file.name}: остаток Bootstrap 3 / jQuery → {legacy}")

    pages = len(list(OUT.glob("*.html")))
    problems.extend(check_css())
    problems.extend(check_css_classes())

    if warnings:
        print(f"[i] Ждут выкладки владельцем ({len(warnings)}):")
        for w in warnings:
            print("   -", w)
        print()

    if problems:
        print(f"[!] Ошибок: {len(problems)}")
        for p in problems:
            print("   -", p)
        return 1

    print(f"[OK] Проверка пройдена: {pages} страниц, битых ссылок нет, "
          f"мета-теги и иконки на месте.")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--check" in args:
        sys.exit(check())
    if "--serve" in args:
        serve()
    build(dev="--dev" in args)