"""Рисунки отчёта валидации: статичные SVG без сторонних библиотек.

Цвета — категориальная палитра из четырёх фиксированных слотов (проверена на различимость при нарушениях
цветового зрения); два слота светлее порога контраста 3:1, поэтому у каждого ряда есть прямая подпись, а все числа
продублированы таблицами отчёта. Подсказка при наведении — элемент `<title>` у каждой отметки.
"""

# ruff: noqa: E501 — подписи отчёта и длинные проверки читаются лучше в одну строку

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from xml.sax.saxutils import escape

SERIES = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100")
SURFACE, INK, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#898781", "#e6e5e0"
SEQUENTIAL = ("#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#104281")
W, H = 720, 400
LEFT, RIGHT, TOP, BOTTOM = 64, 150, 56, 56


def _svg(title: str, subtitle: str, body: list[str]) -> str:
    head = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" '
        f'font-family="system-ui, sans-serif" font-size="12">',
        f"<title>{escape(title)}</title>",
        f'<rect width="{W}" height="{H}" fill="{SURFACE}"/>',
        f'<text x="{LEFT}" y="24" font-size="15" font-weight="600" fill="{INK}">{escape(title)}</text>',
        f'<text x="{LEFT}" y="42" fill="{MUTED}">{escape(subtitle)}</text>',
    ]
    return "\n".join([*head, *body, "</svg>"]) + "\n"


def _y(value: float, top: float = 1.0) -> float:
    return TOP + (H - TOP - BOTTOM) * (1 - value / top)


def _axis(top: float = 1.0, steps: int = 5) -> list[str]:
    out = []
    for i in range(steps + 1):
        value = top * i / steps
        y = _y(value, top)
        out.append(f'<line x1="{LEFT}" x2="{W - RIGHT}" y1="{y:.1f}" y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>')
        out.append(f'<text x="{LEFT - 8}" y="{y + 4:.1f}" text-anchor="end" fill="{MUTED}">{value * 100:.0f}%</text>')
    return out


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def leak_curve(curves: Sequence[dict[str, Any]]) -> str:
    """Кривая утечки (V8): ложное подтверждение по числу утёкших сессий; ось X — порядковая."""
    names = {
        ("pools", 0.5): "пулы, сдвиг 0.5",
        ("pools", 1.0): "пулы, сдвиг 1.0",
        ("single_family", 0.5): "одно семейство, 0.5",
        ("single_family", 1.0): "одно семейство, 1.0",
    }
    body = _axis()
    ms = [p["m"] for p in curves[0]["points"]]
    step = (W - LEFT - RIGHT) / max(len(ms) - 1, 1)
    for i, m in enumerate(ms):
        body.append(f'<text x="{LEFT + i * step:.1f}" y="{H - BOTTOM + 18}" text-anchor="middle" fill="{MUTED}">{m}</text>')
    body.append(f'<text x="{(LEFT + W - RIGHT) / 2:.0f}" y="{H - 12}" text-anchor="middle" fill="{MUTED}">утёкших сессий, m</text>')
    ordered = sorted(curves, key=lambda c: (c["design"] != "pools", c["shift"]))
    ends: list[float] = []
    for index, curve in enumerate(ordered):
        color = SERIES[index % len(SERIES)]
        name = names.get((curve["design"], curve["shift"]), f"{curve['design']}, {curve['shift']}")
        points = [(LEFT + i * step, _y(p["value"] or 0.0)) for i, p in enumerate(curve["points"])]
        path = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(points))
        body.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"/>')
        for (x, y), p in zip(points, curve["points"], strict=True):
            body.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{color}" stroke="{SURFACE}" stroke-width="2">'
                f"<title>{escape(name)}: m = {p['m']}, {_pct(p['value'])}</title></circle>"
            )
        label_y = points[-1][1] + 4
        while any(abs(label_y - used) < 14 for used in ends):
            label_y += 14
        ends.append(label_y)
        body.append(f'<rect x="{W - RIGHT + 10}" y="{label_y - 9:.1f}" width="10" height="10" rx="2" fill="{color}"/>')
        body.append(f'<text x="{W - RIGHT + 26}" y="{label_y:.1f}" fill="{INK}">{escape(name)}</text>')
    return _svg("Утечка: ложное подтверждение слабого кандидата", "доля подтверждённых при уровне ниже порога на 0.4–0.8", body)


def _bars(title: str, subtitle: str, items: Sequence[tuple[str, float | None, str]], reference: float | None = None) -> str:
    body = _axis()
    width = (W - LEFT - RIGHT) / max(len(items), 1)
    bar = min(48.0, width - 8)
    for i, (label, value, hint) in enumerate(items):
        x = LEFT + i * width + (width - bar) / 2
        y = _y(value or 0.0)
        height = max(H - BOTTOM - y, 0.0)
        body.append(
            f'<path d="M{x:.1f},{H - BOTTOM} v{-max(height - 4, 0):.1f} q0,-4 4,-4 h{bar - 8:.1f} q4,0 4,4 v{max(height - 4, 0):.1f} z" '
            f'fill="{SERIES[0]}"><title>{escape(hint)}</title></path>'
        )
        body.append(f'<text x="{x + bar / 2:.1f}" y="{y - 6:.1f}" text-anchor="middle" fill="{INK}">{_pct(value)}</text>')
        body.append(
            f'<text x="{x + bar / 2:.1f}" y="{H - BOTTOM + 18}" text-anchor="middle" fill="{MUTED}" font-size="11">{escape(label)}</text>'
        )
    if reference is not None:
        y = _y(reference)
        body.append(f'<line x1="{LEFT}" x2="{W - RIGHT}" y1="{y:.1f}" y2="{y:.1f}" stroke="{INK}" stroke-width="1" stroke-dasharray="4 4"/>')
        body.append(f'<text x="{W - RIGHT + 8}" y="{y + 4:.1f}" fill="{INK}">планка {_pct(reference)}</text>')
    return _svg(title, subtitle, body)


def stability_by_distance(bins: Sequence[dict[str, Any]]) -> str:
    """Согласие двух независимых сессий по расстоянию истинного уровня до порога (V2)."""
    items = [(b["distance"], b["agreement"], f"расстояние {b['distance']}: {_pct(b['agreement'])}, n = {b['n']}") for b in bins]
    return _bars("Стабильность решения по расстоянию до порога", "согласие «подтверждён или нет» в двух независимых сессиях", items)


def exposure(pairs: Sequence[dict[str, Any]], sessions: int) -> str:
    """Наибольшая экспозиция семейства по категориям (V7) и планка 0.60."""
    items = []
    for pair in pairs:
        value = pair["exposure"][str(sessions)]["max"]
        spec, grade = pair["pair"].split(":")
        items.append((f"{spec[:4]}·{grade[0].upper()}", value, f"{pair['pair']}: {_pct(value)} при {sessions} сессиях"))
    return _bars("Экспозиция: самое частое семейство категории", f"доля сессий с этим семейством, {sessions} сессий на категорию", items, 0.60)


def confusion_flow(cells: Sequence[dict[str, Any]]) -> str:
    """Истинный грейд против итоговой категории (V3): доли от всей популяции."""
    names = list(dict.fromkeys(cell["true"] for cell in cells))
    titles = {"none": "ниже Junior", "junior": "Junior", "middle": "Middle", "senior": "Senior"}
    size_x = (W - LEFT - RIGHT - 60) / len(names)
    size_y = (H - TOP - BOTTOM) / len(names)
    left = LEFT + 60
    peak = max((cell["share"] or 0.0) for cell in cells) or 1.0
    body = []
    for cell in cells:
        col, line = names.index(cell["final"]), names.index(cell["true"])
        value = cell["share"] or 0.0
        step = min(len(SEQUENTIAL) - 1, int(value / peak * (len(SEQUENTIAL) - 1) + 0.999)) if value > 0 else 0
        x, y = left + col * size_x, TOP + line * size_y
        fill = SEQUENTIAL[step] if value > 0 else "#f0efec"
        body.append(
            f'<rect x="{x + 1:.1f}" y="{y + 1:.1f}" width="{size_x - 2:.1f}" height="{size_y - 2:.1f}" rx="4" fill="{fill}">'
            f"<title>истинный: {titles[cell['true']]}, итог: {titles[cell['final']]} — {_pct(value)}</title></rect>"
        )
        ink = "#ffffff" if step >= 3 else INK
        body.append(f'<text x="{x + size_x / 2:.1f}" y="{y + size_y / 2 + 4:.1f}" text-anchor="middle" fill="{ink}">{_pct(value)}</text>')
    for index, name in enumerate(names):
        body.append(f'<text x="{left - 8}" y="{TOP + index * size_y + size_y / 2 + 4:.1f}" text-anchor="end" fill="{MUTED}">{titles[name]}</text>')
        body.append(f'<text x="{left + index * size_x + size_x / 2:.1f}" y="{H - BOTTOM + 18}" text-anchor="middle" fill="{MUTED}">{titles[name]}</text>')
    body.append(f'<text x="{left + size_x * len(names) / 2:.0f}" y="{H - 12}" text-anchor="middle" fill="{MUTED}">итоговая категория</text>')
    body.append(f'<text x="{W - RIGHT + 8}" y="{TOP + 12}" fill="{MUTED}">строки —</text>')
    body.append(f'<text x="{W - RIGHT + 8}" y="{TOP + 28}" fill="{MUTED}">истинный грейд</text>')
    return _svg("Истинный грейд и итоговая категория", "доля кандидатов популяции; диагональ — совпадение", body)
