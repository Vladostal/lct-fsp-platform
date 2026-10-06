"""Минимальный писатель PDF для тестов: текстовые страницы со встроенным шрифтом (кириллица), пустые страницы,
«скан» без текста и защищённый файл. Нужен, потому что WeasyPrint на машине разработки может не импортироваться
(нет Pango), а тестам резюме нужны настоящие PDF с извлекаемым текстом.
"""

from __future__ import annotations

import io
import zlib
from pathlib import Path

from fontTools.ttLib import TTFont
from pypdf import PdfReader, PdfWriter

FONT_PATH = Path(__file__).resolve().parents[2] / "app/modules/profile/pdf/fonts/Inter-Regular.ttf"
_FONT = TTFont(FONT_PATH)
_CMAP = _FONT.getBestCmap()
_GLYPHS = {name: index for index, name in enumerate(_FONT.getGlyphOrder())}
_FONT_BYTES = FONT_PATH.read_bytes()


def _glyph(ch: str) -> int:
    return _GLYPHS[_CMAP.get(ord(ch), ".notdef")]


def _stream(data: bytes, extra: str = "") -> bytes:
    packed = zlib.compress(data)
    return f"<< /Length {len(packed)} /Filter /FlateDecode {extra}>>\nstream\n".encode() + packed + b"\nendstream"


def text_pdf(
    pages: list[list[str]],
    *,
    size: float = 10.0,
    repeat_last_line: int = 0,
    form_ops: int = 0,
    form_calls: int = 0,
) -> bytes:
    """PDF: страница — список строк; `repeat_last_line` повторяет последнюю строку N раз (тяжёлая страница).

    `form_ops` и `form_calls` строят «тяжёлую, но не прожорливую» страницу: форма из `form_ops` операторов вызывается
    `form_calls` раз, а `pypdf` разбирает её заново при каждом вызове — долго по времени, мало по памяти."""
    used: dict[int, str] = {}
    contents: list[bytes] = []
    for lines in pages:
        ops = ["BT", f"/F1 {size} Tf", f"{size * 1.4} TL", "40 800 Td"]
        for line in lines:
            hexed = ""
            for ch in line:
                gid = _glyph(ch)
                used[gid] = ch
                hexed += f"{gid:04X}"
            ops.append(f"<{hexed}> Tj T*")
        ops.append("ET")
        contents.append("\n".join(ops).encode())
    if repeat_last_line:
        contents[-1] = contents[-1].replace(b"ET", (b"<0041> Tj T*\n" * repeat_last_line) + b"ET")
        used[0x41] = "A"

    cmap_lines = [
        "/CIDInit /ProcSet findresource begin 12 dict begin begincmap",
        "/CMapName /Adobe-Identity-UCS def",
        "/CMapType 2 def 1 begincodespacerange <0000> <FFFF> endcodespacerange",
    ]
    items = sorted(used.items())
    for start in range(0, len(items), 100):
        chunk = items[start : start + 100]
        cmap_lines.append(f"{len(chunk)} beginbfchar")
        cmap_lines.extend(f"<{gid:04X}> <{ord(ch):04X}>" for gid, ch in chunk)
        cmap_lines.append("endbfchar")
    cmap_lines.append("endcmap CMapName currentdict /CMap defineresource pop end end")

    objects: list[bytes] = []

    def add(body: bytes | str) -> int:
        objects.append(body.encode() if isinstance(body, str) else body)
        return len(objects)

    catalog = add("")  # 1 — заполняется ниже
    pages_id = add("")  # 2
    font_file = add(_stream(_FONT_BYTES, f"/Length1 {len(_FONT_BYTES)} "))
    descriptor = add(
        f"<< /Type /FontDescriptor /FontName /Inter /Flags 4 /FontBBox [-200 -300 1200 1000] /ItalicAngle 0 "
        f"/Ascent 900 /Descent -250 /CapHeight 700 /StemV 80 /FontFile2 {font_file} 0 R >>"
    )
    cid_font = add(
        f"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /Inter "
        f"/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
        f"/FontDescriptor {descriptor} 0 R /CIDToGIDMap /Identity /DW 600 >>"
    )
    to_unicode = add(_stream("\n".join(cmap_lines).encode()))
    font = add(
        f"<< /Type /Font /Subtype /Type0 /BaseFont /Inter /Encoding /Identity-H /DescendantFonts [{cid_font} 0 R] "
        f"/ToUnicode {to_unicode} 0 R >>"
    )
    xobject = ""
    if form_ops:
        form_body = b"BT /F1 8 Tf\n" + b"1 0 0 1 0 0 Tm\n" * form_ops + b"ET"
        form = add(
            _stream(
                form_body,
                f"/Type /XObject /Subtype /Form /BBox [0 0 595 842] /Resources << /Font << /F1 {font} 0 R >> >> ",
            )
        )
        xobject = f"/XObject << /X1 {form} 0 R >> "
        contents[-1] += b"\n" + b"q /X1 Do Q\n" * form_calls
    kids = []
    for content in contents:
        content_id = add(_stream(content))
        kids.append(
            add(
                f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 595 842] /Contents {content_id} 0 R "
                f"/Resources << /Font << /F1 {font} 0 R >> {xobject}>> >>"
            )
        )
    objects[catalog - 1] = f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode()
    objects[pages_id - 1] = (
        f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>".encode()
    )

    out = io.BytesIO()
    out.write(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def blank_pdf(pages: int = 1) -> bytes:
    """PDF без текста — «скан»: пустые страницы (картинок в тесте не нужно: текста нет, и этого достаточно)."""
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def encrypted_pdf(password: str = "secret") -> bytes:
    reader = PdfReader(io.BytesIO(text_pdf([["Резюме " * 5]])))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.encrypt(password)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
