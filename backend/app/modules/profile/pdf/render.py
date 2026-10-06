"""Рендер PDF-профиля (Арх. 6.14, 10.7).

Вход — `ProfilePdfModel`, собранная `matching`; выход — байты PDF. Два защитных правила, потому что в документ попадает
свободный текст кандидата («О себе», свои теги, ссылка):

1. Jinja2 работает с `autoescape`, а поля выводятся как данные: разметка из них не исполняется, ссылка кандидата
   печатается текстом, а не `<a>`.
2. Загрузчик ресурсов WeasyPrint (`FontOnlyFetcher`) пропускает только файлы шрифтов из каталога `fonts/` рядом
   с шаблоном; сеть и любые другие `file://` отклоняются — даже если разметка каким-то образом дошла до рендера.

WeasyPrint подгружается при первом вызове: на машине без системных библиотек Pango (macOS без `brew install pango`)
его импорт падает, и обычное приложение стартовать это не должно мешать.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import jinja2

from app.modules.profile.constants import PDF_MAX_PAGES
from app.modules.profile.dto import ProfilePdfModel
from app.shared.text import fmt_date, plural

PDF_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = PDF_DIR / "templates"
FONTS_DIR = PDF_DIR / "fonts"
FONT_SUFFIXES = frozenset({".ttf", ".otf", ".woff", ".woff2"})

#: Предел строк таблицы навыков: документ должен уместиться в две страницы A4.
SKILL_ROWS_MAX = 24
SKILL_ROWS_MAX_COMPACT = 14

_VERDICT_NOTES = {
    "confirmed": "подтверждён",
    "confirmed_with_margin": "подтверждён с запасом",
}


def _environment() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATES_DIR),
        autoescape=jinja2.select_autoescape(["html", "xml"], default_for_string=True, default=True),
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["date"] = fmt_date
    env.filters["years"] = _years
    return env


def _years(value: float) -> str:
    """«4 года», «3,5 года», «1 год»: дробное число — всегда «года»."""
    if float(value).is_integer():
        return f"{int(value)} {plural(int(value), 'год', 'года', 'лет')}"
    return f"{value:g}".replace(".", ",") + " года"


def _days_ago(generated_at: datetime, moment: datetime) -> str:
    days = max(0, (generated_at.date() - moment.date()).days)
    if days == 0:
        return "сегодня"
    return f"{days} {plural(days, 'день', 'дня', 'дней')} назад"


def _context(model: ProfilePdfModel, compact: bool) -> dict[str, Any]:
    context = model.template_context()
    skills_all = model.skills
    limit = SKILL_ROWS_MAX_COMPACT if compact else SKILL_ROWS_MAX
    level = model.level
    context.update(
        compact=compact,
        fonts_uri=FONTS_DIR.as_uri(),
        generated_iso=model.generated_at.isoformat(),
        generated_date=fmt_date(model.generated_at),
        skills=[item.model_dump(mode="python") for item in skills_all[:limit]],
        skills_hidden=max(0, len(skills_all) - limit),
        verdict_note=_VERDICT_NOTES.get(level.verdict.value, "") if level else "",
        tested_date=fmt_date(level.tested_at) if level else "",
        evidence_age=_days_ago(model.generated_at, level.last_evidence_at) if level else "",
        scale=(
            {
                "lower": max(0.0, min(100.0, level.lower)),
                "upper": max(0.0, min(100.0, level.upper)),
                "point": max(0.0, min(100.0, level.point)),
                "thresholds": [{"title": t.grade.title, "pos": max(0.0, min(100.0, t.pos))} for t in level.thresholds],
            }
            if level
            else None
        ),
    )
    return context


class FontOnlyFetcher:
    """Загрузчик ресурсов WeasyPrint: только шрифты из `FONTS_DIR`.

    Любой другой адрес — сеть, `data:`, чужой `file://`, выход из каталога через `..` или ссылку — отклоняется
    исключением: WeasyPrint его перехватывает, пишет предупреждение и рисует без ресурса. Все обращения записываются
    в `requested`, отклонённые — ещё и в `blocked` (на этом строится тест «ни одного обращения вовне»).
    """

    #: Читается самим WeasyPrint (`weasyprint.urls.fetch`): ошибка ресурса — предупреждение, а не отказ рендера.
    _fail_on_errors = False

    def __init__(self) -> None:
        self.requested: list[str] = []
        self.blocked: list[str] = []
        self._inner: Any = None

    def _is_allowed_font(self, url: str) -> bool:
        parts = urlsplit(url)
        if parts.scheme.lower() != "file" or parts.netloc not in ("", "localhost"):
            return False
        try:
            path = Path(unquote(parts.path)).resolve(strict=True)
        except (OSError, ValueError):
            return False
        return path.parent == FONTS_DIR.resolve() and path.suffix.lower() in FONT_SUFFIXES

    def fetch(self, url: str, headers: Any = None) -> Any:
        self.requested.append(url)
        if not self._is_allowed_font(url):
            self.blocked.append(url)
            raise ValueError(f"PDF-профиль: ресурс не из каталога шрифтов отклонён: {url[:80]}")
        if self._inner is None:
            from weasyprint.urls import URLFetcher

            self._inner = URLFetcher(allowed_protocols={"file"}, allow_redirects=False)
        return self._inner.fetch(url, headers)

    def __call__(self, url: str) -> Any:
        return self.fetch(url)


def make_fetcher() -> FontOnlyFetcher:
    """Новый загрузчик на один рендер (тесты подменяют эту функцию, чтобы наблюдать обращения)."""
    return FontOnlyFetcher()


def render_profile_pdf(model: ProfilePdfModel) -> bytes:
    """Собрать PDF-профиль: A4, не больше двух страниц, одни данные — один текст.

    Если документ не уместился в `PDF_MAX_PAGES`, строится сжатый вариант (мельче шрифт, короче таблица навыков),
    и, наконец, лишние страницы отбрасываются — таблица навыков при этом сворачивается в «и ещё N».
    """
    from weasyprint import HTML

    template = _environment().get_template("profile.html")
    document = None
    for compact in (False, True):
        html = template.render(**_context(model, compact))
        document = HTML(string=html, base_url=FONTS_DIR.as_uri() + "/", url_fetcher=make_fetcher()).render()
        if len(document.pages) <= PDF_MAX_PAGES:
            break
    assert document is not None
    if len(document.pages) > PDF_MAX_PAGES:
        document = document.copy(document.pages[:PDF_MAX_PAGES])
    return bytes(document.write_pdf() or b"")
