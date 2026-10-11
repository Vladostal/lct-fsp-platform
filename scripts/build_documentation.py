#!/usr/bin/env python3
"""Сборка PDF (A4) из Markdown: markdown-it-py -> HTML -> WeasyPrint.

    python3 scripts/build_documentation.py fsp-integration.md fsp-integration.pdf [--html out.html] [--no-docker]

Новых зависимостей нет: WeasyPrint 70.0, markdown-it-py и Pygments уже стоят в образе `fsp-podbor-api`
(зависимости backend). На macOS без Pango импорт WeasyPrint падает, поэтому скрипт, запущенный на хосте,
перезапускает сам себя в одноразовом контейнере этого образа (`docker run --rm --network none`): работающие
сервисы compose не затрагиваются, сеть в контейнере отключена. Внутри контейнера (в том числе через
`make docs-pdf DOCS_PDF_SCRIPT=scripts/build_documentation.py ARGS="in.md out.pdf"`) он работает напрямую.

Что умеет:
- таблицы, блоки кода с подсветкой (Pygments), заголовки с id в стиле GitHub, оглавление с номерами страниц;
- титульный лист из «шапки» файла (`---` / `ключ: значение` / `---`) либо из первого заголовка `#`;
- встроенный `<svg>` и `<figure>` передаются в PDF как есть (вне блоков кода), с подписью `<figcaption>`;
- шрифты только из локальных файлов: Inter (обычный, полужирный) и JetBrains Mono из
  backend/app/modules/profile/pdf/fonts — они же лежат в образе. Вариативные woff2 из @fontsource-variable
  (Geologica, Inter) не используются: WeasyPrint 70.0 на проверке выводил ими искажённые глифы;
- нумерация страниц и название документа в колонтитулах.

Ключи шапки: title, subtitle, eyebrow (строка над названием), header (текст верхнего колонтитула),
toc (true/false), toc_depth (2 или 3), toc_title, lang, table_break (avoid/auto), compact (true/false). Любые другие ключи печатаются на титульном листе
строками «ключ — значение» в порядке записи.

Не поддерживается: mermaid и прочие диаграммы-из-кода (нужен готовый inline SVG), сноски, формулы,
списки задач, автонумерация разделов. Курсивного начертания в наборе шрифтов нет: *курсив* печатается синтетическим наклоном,
почти неотличимым от прямого.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import subprocess
import sys
from pathlib import Path

SELF = Path(__file__).resolve()
DOCKER_IMAGE = os.environ.get("DOCS_IMAGE", "fsp-podbor-api")
FONTS_REL = "backend/app/modules/profile/pdf/fonts"


def repo_root() -> Path | None:
    """Корень репозитория: FSP_REPO, каталоги над скриптом, текущий каталог, /srv/repo (в контейнере)."""
    candidates = [os.environ.get("FSP_REPO"), *map(str, SELF.parents), os.getcwd(), "/srv/repo"]
    for item in candidates:
        if item and (Path(item) / FONTS_REL).is_dir():
            return Path(item)
    return None


# --- запуск в контейнере ---------------------------------------------------------------------------------------------


def run_in_docker(args: argparse.Namespace) -> int:
    src, out = Path(args.input).resolve(), Path(args.output).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    mounts: dict[str, str] = {str(SELF.parent): "ro", str(src.parent): "ro", str(out.parent): "rw"}
    inner = ["python", str(SELF), str(src), str(out), "--no-docker"]
    if args.html:
        html_path = Path(args.html).resolve()
        html_path.parent.mkdir(parents=True, exist_ok=True)
        mounts[str(html_path.parent)] = "rw"
        inner += ["--html", str(html_path)]
    cmd = ["docker", "run", "--rm", "--network", "none", "--user", f"{os.getuid()}:{os.getgid()}",
           "-e", "HOME=/tmp", "-e", "PYTHONDONTWRITEBYTECODE=1", "-w", "/tmp", "--entrypoint", ""]
    root = repo_root()
    if root and DOCKER_IMAGE != "fsp-podbor-api":  # в чужом образе шрифтов профиля нет
        cmd += ["-v", f"{root / FONTS_REL}:/docfonts/base:ro"]
    for path, mode in mounts.items():
        cmd += ["-v", f"{path}:{path}:{mode}"]
    return subprocess.call([*cmd, DOCKER_IMAGE, *inner])


# --- Markdown -> HTML ------------------------------------------------------------------------------------------------

FENCE_RE = re.compile(r"^(\s{0,3})(`{3,}|~{3,})")
RAW_OPEN_RE = re.compile(r"^\s{0,3}<(svg|figure)\b", re.I)
PLACEHOLDER = "RAWBLOCKPLACEHOLDER{}END"


def split_front_matter(text: str) -> tuple[dict[str, str], str]:
    """Шапка `--- … ---` в начале файла: простые пары «ключ: значение» (не полный YAML)."""
    meta: dict[str, str] = {}
    if not text.startswith("---"):
        return meta, text
    lines = text.splitlines()
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            for line in lines[1:i]:
                if ":" in line and not line.lstrip().startswith("#"):
                    key, value = line.split(":", 1)
                    meta[key.strip()] = value.strip().strip("\"'")
            return meta, "\n".join(lines[i + 1:])
    return meta, text


def extract_raw_blocks(text: str) -> tuple[str, list[str]]:
    """Вынимает <svg>…</svg> и <figure>…</figure> вне блоков кода.

    По CommonMark HTML-блок с <svg> обрывается на первой пустой строке, и остаток диаграммы превращается в абзацы.
    Поэтому такие блоки заменяются метками до разбора и возвращаются в готовый HTML без изменений.
    """
    out: list[str] = []
    blocks: list[str] = []
    fence: str | None = None
    raw_tag: str | None = None
    buf: list[str] = []
    for line in text.splitlines():
        if raw_tag is None:
            m = FENCE_RE.match(line)
            if m:
                marker = m.group(2)
                if fence is None:
                    fence = marker
                elif marker[0] == fence[0] and len(marker) >= len(fence) and line.strip() == marker:
                    fence = None
                out.append(line)
                continue
            if fence is None:
                m2 = RAW_OPEN_RE.match(line)
                if m2:
                    raw_tag, buf = m2.group(1).lower(), []
        if raw_tag is not None:
            buf.append(line)
            if re.search(rf"</{raw_tag}\s*>", line, re.I):
                blocks.append("\n".join(buf))
                out += ["", PLACEHOLDER.format(len(blocks) - 1), ""]
                raw_tag = None
            continue
        out.append(line)
    if raw_tag is not None:
        sys.exit(f"ошибка: блок <{raw_tag}> не закрыт")
    return "\n".join(out), blocks


def prepare_raw(block: str) -> str:
    """Голый <svg> оборачивается в <figure>; корню svg задаётся шрифт документа, если он не указан."""
    def fix_svg(m: re.Match[str]) -> str:
        tag = m.group(0)
        if "font-family" not in tag:
            tag = tag[:-1] + ' font-family="Inter, DejaVu Sans, sans-serif">'
        return tag

    block = re.sub(r"<svg\b[^>]*>", fix_svg, block, count=0, flags=re.I)
    if block.lstrip().lower().startswith("<svg"):
        return f'<figure class="diagram">{block}</figure>'
    return re.sub(r"<figure\b(?![^>]*class=)", '<figure class="diagram"', block, count=1, flags=re.I)


def slugify(title: str, used: dict[str, int]) -> str:
    """Якорь как на GitHub: нижний регистр, без знаков препинания, пробелы -> дефисы, повторы с суффиксом."""
    slug = re.sub(r"[^\w\- ]", "", title.strip().lower(), flags=re.UNICODE).replace(" ", "-") or "section"
    n = used.get(slug, 0)
    used[slug] = n + 1
    return slug if n == 0 else f"{slug}-{n}"


def render_markdown(text: str) -> tuple[str, list[tuple[int, str, str]], list[str]]:
    from markdown_it import MarkdownIt
    from pygments import highlight
    from pygments.formatters import HtmlFormatter
    from pygments.lexers import get_lexer_by_name
    from pygments.util import ClassNotFound

    warnings: list[str] = []

    def highlighter(code: str, lang: str, _attrs: str) -> str:
        if lang in ("mermaid", "plantuml", "dot"):
            warnings.append(f"блок ```{lang} не рисуется: останется текстом, диаграмму нужно дать как inline SVG")
        try:
            lexer = get_lexer_by_name(lang) if lang else None
        except ClassNotFound:
            lexer = None
        if lexer is None:
            return ""  # markdown-it сам экранирует текст
        return highlight(code, lexer, HtmlFormatter(nowrap=True))

    md = MarkdownIt("commonmark", {"html": True, "highlight": highlighter}).enable(["table", "strikethrough"])
    text, raw_blocks = extract_raw_blocks(text)
    tokens = md.parse(text)
    used: dict[str, int] = {}
    headings: list[tuple[int, str, str]] = []
    for i, tok in enumerate(tokens):
        if tok.type == "heading_open":
            inline = tokens[i + 1]
            plain = "".join(c.content for c in (inline.children or []) if c.type in ("text", "code_inline"))
            anchor = slugify(plain, used)
            tok.attrSet("id", anchor)
            headings.append((int(tok.tag[1]), plain, anchor))
    body = md.renderer.render(tokens, md.options, {})
    for i, block in enumerate(raw_blocks):
        body = body.replace(f"<p>{PLACEHOLDER.format(i)}</p>", prepare_raw(block))
    # таблицу оборачиваем, чтобы управлять разрывом страницы вместе с рамкой
    # Короткая таблица (до 8 строк) получает класс keep: она не разрывается и при table_break: auto.
    def wrap_table(m: re.Match[str]) -> str:
        short = m.group(0).count("<tr>") <= 9  # шапка и восемь строк
        return f'<div class="table{" keep" if short else ""}">{m.group(0)}</div>'

    body = re.sub(r"<table>.*?</table>", wrap_table, body, flags=re.S)
    return body, headings, warnings


# --- шрифты и стили ----------------------------------------------------------------------------------------------------


def find_dir(*candidates: Path | None) -> Path | None:
    return next((c for c in candidates if c and c.is_dir()), None)


def font_css() -> tuple[str, str]:
    """@font-face из локальных статических TTF; возвращает (css, семейство заголовков)."""
    root = repo_root()
    base = find_dir(Path("/docfonts/base"), Path("/srv") / FONTS_REL, root / FONTS_REL if root else None)
    if base is None:
        print("предупреждение: шрифты Inter не найдены, будет DejaVu Sans", file=sys.stderr)
        return "", "DejaVu Sans"
    faces = [
        ("Inter", "400", base / "Inter-Regular.ttf", ""),
        ("Inter", "700", base / "Inter-Bold.ttf", ""),
        ("JetBrains Mono", "400", base / "JetBrainsMono-Regular.ttf", ""),
    ]
    css = "\n".join(
        f'@font-face {{ font-family: "{fam}"; font-weight: {w}; font-style: normal; src: url("{p.as_uri()}"); {extra} }}'
        for fam, w, p, extra in faces if p.is_file()
    )
    return css, "Inter"


CSS = r"""
@page {
  size: A4;
  margin: 20mm 18mm 20mm 20mm;
  @top-right { content: string(doctitle); font: 8pt "Inter", sans-serif; color: #8a93a0; }
  @bottom-center { content: counter(page) " / " counter(pages); font: 8.5pt "Inter", sans-serif; color: #5b6573; }
}
@page cover { margin: 0; @top-right { content: none; } @bottom-center { content: none; } }

html { font-family: "Inter", "DejaVu Sans", sans-serif; font-size: 10pt; line-height: 1.5; color: #1b2430; }
body { margin: 0; hyphens: manual; }
p, li { orphans: 2; widows: 2; }
p { margin: 0 0 7pt; }
a { color: #1d4ed8; text-decoration: none; }
strong { font-weight: 700; }
hr { border: 0; border-top: 0.5pt solid #cfd6df; margin: 14pt 0; }

h1, h2, h3, h4 { font-family: "HEADING", "Inter", sans-serif; color: #0f1b2d; line-height: 1.25;
  break-after: avoid; break-inside: avoid; }
h1 { font-size: 19pt; font-weight: 700; margin: 0 0 12pt; break-before: page; }
h2 { font-size: 14.5pt; font-weight: 700; margin: 20pt 0 8pt; padding-bottom: 3pt; border-bottom: 0.6pt solid #cfd6df; }
h3 { font-size: 11.5pt; font-weight: 700; margin: 14pt 0 5pt; }
h4 { font-size: 10pt; font-weight: 700; font-family: "Inter", sans-serif; margin: 10pt 0 4pt; }
main > h1:first-child, main > h2:first-child { margin-top: 0; break-before: auto; }

ul, ol { margin: 0 0 7pt; padding-left: 16pt; }
li { margin: 1.5pt 0; }
li > p { margin: 0 0 3pt; }

code, pre { font-family: "JetBrains Mono", "DejaVu Sans Mono", monospace; }
code { font-size: 8.6pt; background: #f1f3f6; border-radius: 2pt; padding: 0.5pt 2.5pt; overflow-wrap: anywhere; }
pre { font-size: 8pt; line-height: 1.42; background: #f6f7f9; border: 0.5pt solid #dde2e8; border-radius: 3pt;
  padding: 7pt 9pt; margin: 0 0 9pt; white-space: pre-wrap; overflow-wrap: anywhere; break-inside: avoid; }
pre code { font-size: inherit; background: none; padding: 0; }

blockquote { margin: 0 0 9pt; padding: 6pt 10pt; border-left: 2.5pt solid #1d4ed8; background: #f3f6fc;
  break-inside: avoid; }
blockquote > :last-child { margin-bottom: 0; }

.table { margin: 0 0 10pt; break-inside: avoid; }
table { border-collapse: collapse; width: 100%; font-size: 8.8pt; line-height: 1.38; }
thead { display: table-header-group; }
th, td { border: 0.5pt solid #cfd6df; padding: 3.5pt 6pt; text-align: left; vertical-align: top; }
th { background: #eef1f5; font-weight: 700; color: #0f1b2d; }
tr { break-inside: avoid; }
td code, th code { font-size: 7.8pt; }
/* в первой колонке стоят короткие идентификаторы: не рвём их посреди слова */
td:first-child code { overflow-wrap: normal; white-space: nowrap; }

figure { margin: 4pt 0 11pt; text-align: center; break-inside: avoid; }
figure svg, figure img, p > img { max-width: 100%; height: auto; }
figcaption { font-size: 8.5pt; color: #5b6573; margin-top: 4pt; }

/* титульный лист */
.cover { page: cover; height: 297mm; box-sizing: border-box; padding: 34mm 24mm 24mm 26mm; position: relative;
  border-left: 7mm solid #1d4ed8; break-after: page; }
.cover .eyebrow { font-size: 10.5pt; letter-spacing: 0.06em; text-transform: uppercase; color: #5b6573; }
.cover .title { font-family: "HEADING", "Inter", sans-serif; font-weight: 700; font-size: 30pt; line-height: 1.15;
  color: #0f1b2d; margin: 58mm 0 0; string-set: doctitle attr(data-header); }
.cover .subtitle { font-size: 13pt; line-height: 1.4; color: #3a4656; margin-top: 9mm; max-width: 135mm; }
.cover dl { position: absolute; left: 26mm; right: 24mm; bottom: 26mm; margin: 0; font-size: 9.5pt;
  border-top: 0.6pt solid #cfd6df; padding-top: 5mm; }
.cover dl div { display: flex; margin: 1.5pt 0; }
.cover dt { width: 38mm; color: #5b6573; }
.cover dd { margin: 0; flex: 1; }

/* оглавление */
nav.toc { break-after: page; }
nav.toc .toc-title { font-family: "HEADING", "Inter", sans-serif; font-weight: 700; font-size: 19pt;
  color: #0f1b2d; margin: 0 0 12pt; }
nav.toc ul { list-style: none; margin: 0; padding: 0; }
nav.toc li { margin: 0; }
nav.toc a { display: block; color: #1b2430; padding: 1.8pt 0; }
nav.toc a::after { content: leader(".") target-counter(attr(href), page); color: #5b6573; }
nav.toc .l1 a { font-weight: 700; margin-top: 5pt; }
nav.toc .l2 a { padding-left: 0; }
nav.toc .l3 a { padding-left: 12pt; font-size: 9.2pt; color: #3a4656; }
nav.toc.has-l1 .l2 a { padding-left: 12pt; }
nav.toc.has-l1 .l3 a { padding-left: 24pt; }

/* подсветка кода (Pygments, сдержанная палитра) */
pre .k, pre .kn, pre .kd, pre .kc, pre .kr, pre .ow { color: #7c3aed; }
pre .s, pre .s1, pre .s2, pre .sd, pre .sa, pre .se, pre .si { color: #0f766e; }
pre .c, pre .c1, pre .cm, pre .ch { color: #7b8794; }
pre .mi, pre .mf, pre .m, pre .mh { color: #b45309; }
pre .nf, pre .nc, pre .nd, pre .fm { color: #1d4ed8; }
pre .nt, pre .na, pre .nb, pre .bp { color: #1e40af; }
"""


def build_html(src: Path) -> tuple[str, list[str]]:
    meta, text = split_front_matter(src.read_text(encoding="utf-8"))
    body, headings, warnings = render_markdown(text)

    title = meta.pop("title", "")
    if not title:  # первый «# Заголовок» становится названием документа и уходит на титульный лист
        first = next((h for h in headings if h[0] == 1), None)
        if first:
            title = first[1]
            body = re.sub(r"<h1 id=\"[^\"]*\">.*?</h1>\s*", "", body, count=1, flags=re.S)
            headings.remove(first)
    title = title or src.stem
    subtitle, eyebrow = meta.pop("subtitle", ""), meta.pop("eyebrow", "")
    header = meta.pop("header", title)
    toc_on = meta.pop("toc", "true").lower() not in ("false", "no", "0", "нет")
    toc_depth = int(meta.pop("toc_depth", "3"))
    toc_title = meta.pop("toc_title", "Содержание")
    lang = meta.pop("lang", "ru")
    # table_break: auto — длинные таблицы переносятся между страницами (шапка повторяется, строки не рвутся);
    # по умолчанию таблица, которая помещается на страницу, не разрывается.
    table_break = meta.pop("table_break", "avoid").lower()
    compact = meta.pop("compact", "false").lower() in ("true", "yes", "1", "да")
    esc = html.escape

    cover = ['<section class="cover">']
    if eyebrow:
        cover.append(f'<div class="eyebrow">{esc(eyebrow)}</div>')
    cover.append(f'<div class="title" data-header="{esc(header)}">{esc(title)}</div>')
    if subtitle:
        cover.append(f'<div class="subtitle">{esc(subtitle)}</div>')
    if meta:
        rows = "".join(f"<div><dt>{esc(k)}</dt><dd>{esc(v)}</dd></div>" for k, v in meta.items())
        cover.append(f"<dl>{rows}</dl>")
    cover.append("</section>")

    toc = ""
    entries = [h for h in headings if h[0] <= toc_depth]
    if toc_on and entries:
        has_l1 = any(level == 1 for level, _, _ in entries)
        items = "".join(f'<li class="l{lv}"><a href="#{esc(a)}">{esc(t)}</a></li>' for lv, t, a in entries)
        toc = (f'<nav class="toc{" has-l1" if has_l1 else ""}"><div class="toc-title">{esc(toc_title)}</div>'
               f"<ul>{items}</ul></nav>")

    fonts, heading_family = font_css()
    css = fonts + CSS.replace("HEADING", heading_family)
    # compact: true — плотный набор для длинных документов: поля страницы, кегль и поля ячеек немного меньше.
    if compact:
        css += ("@page { margin: 17mm 16mm 17mm 17mm; } "
                "html { font-size: 9.5pt; line-height: 1.42; } table { font-size: 8.4pt; line-height: 1.33; } "
                "th, td { padding: 2.4pt 5pt; } p { margin-bottom: 6pt; } .table { margin-bottom: 9pt; } "
                "h2 { margin-top: 16pt; } h3 { margin-top: 11pt; }\n")
    if table_break == "auto":
        css += ".table { break-inside: auto; } .table.keep { break-inside: avoid; }\n"
    doc = (f'<!doctype html><html lang="{esc(lang)}"><head><meta charset="utf-8"><title>{esc(title)}</title>'
           f"<style>{css}</style></head><body>{''.join(cover)}{toc}<main>{body}</main></body></html>")
    return doc, warnings


def build(args: argparse.Namespace) -> int:
    from weasyprint import HTML

    src, out = Path(args.input).resolve(), Path(args.output).resolve()
    doc, warnings = build_html(src)
    if args.html:
        Path(args.html).write_text(doc, encoding="utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    rendered = HTML(string=doc, base_url=src.parent.as_uri() + "/").render()
    rendered.write_pdf(str(out))
    for w in dict.fromkeys(warnings):
        print(f"предупреждение: {w}", file=sys.stderr)
    print(f"{out}: {len(rendered.pages)} стр., {out.stat().st_size // 1024} КБ")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Markdown -> PDF (A4) через WeasyPrint")
    parser.add_argument("input", help="исходный .md")
    parser.add_argument("output", help="итоговый .pdf")
    parser.add_argument("--html", help="сохранить промежуточный HTML (для отладки вёрстки)")
    parser.add_argument("--no-docker", action="store_true", help="не перезапускаться в контейнере")
    args = parser.parse_args()
    if not Path(args.input).is_file():
        parser.error(f"нет файла {args.input}")
    try:
        import markdown_it  # noqa: F401
        import weasyprint  # noqa: F401
    except Exception as exc:  # на macOS без Pango импорт WeasyPrint падает с OSError
        if args.no_docker:
            print(f"ошибка: WeasyPrint или markdown-it-py недоступны ({exc.__class__.__name__})", file=sys.stderr)
            return 2
        return run_in_docker(args)
    return build(args)


if __name__ == "__main__":
    sys.exit(main())
