"""PDF-профиль: шаблон, экранирование ввода, запрет обращений к сети и чужим файлам (Арх. 6.14, 10.7).

Тесты, которым нужен настоящий рендер, пропускаются без системных библиотек WeasyPrint (Pango) и выполняются
в контейнере `api`. Проверки шаблона и загрузчика ресурсов от WeasyPrint не зависят.
"""

from __future__ import annotations

import io
import re
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pypdf import PdfReader

from app.modules.assessment.dto import LevelThreshold, LevelView
from app.modules.profile import service
from app.modules.profile.dto import PdfContacts, PdfDeclaredBlock, PdfFspBlock, ProfilePdfModel
from app.modules.profile.pdf import render
from app.shared.enums import EvidenceKind, TestOutcome
from app.shared.schemas import CategoryRef, EvidenceItem, Ref

GENERATED = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def weasyprint_available() -> bool:
    try:
        import weasyprint  # noqa: F401
    except Exception:
        return False
    return True


needs_weasyprint = pytest.mark.skipif(
    not weasyprint_available(), reason="нет системных библиотек Pango: рендер проверяется в контейнере api"
)


def model(**overrides: Any) -> ProfilePdfModel:
    level = LevelView(
        point=62,
        lower=55,
        upper=70,
        thresholds=[
            LevelThreshold(grade=Ref(code="junior", title="Junior"), pos=25),
            LevelThreshold(grade=Ref(code="middle", title="Middle"), pos=50),
            LevelThreshold(grade=Ref(code="senior", title="Senior"), pos=75),
        ],
        verdict=TestOutcome.CONFIRMED_WITH_MARGIN,
        verdict_label="Подтверждён с запасом",
        stale=False,
        tested_at=GENERATED - timedelta(days=40),
        last_evidence_at=GENERATED - timedelta(days=12),
    )
    values: dict[str, Any] = {
        "full_name": "Смирнова Анна Сергеевна",
        "public_code": "К-04217",
        "generated_at": GENERATED,
        "category": CategoryRef(
            code="backend:middle",
            title="Backend · Middle",
            specialization=Ref(code="backend", title="Backend"),
            grade=Ref(code="middle", title="Middle"),
        ),
        "level": level,
        "skills": [
            EvidenceItem(
                skill=Ref(code="python", title="Python"),
                kind=EvidenceKind.TEST,
                kind_label="Тест",
                detail="Семейство «Запросы и модели»",
                confirmed_at=GENERATED - timedelta(days=40),
            ),
            EvidenceItem(
                skill=Ref(code="docker", title="Docker"),
                kind=EvidenceKind.FSP,
                kind_label="Достижение ФСП",
                via_skill=Ref(code="python", title="Python"),
            ),
        ],
        "fsp": PdfFspBlock(headline="Призёр регионального этапа", lines=["Чемпионат 2025 — 2 место"]),
        "declared": PdfDeclaredBlock(
            city="Казань",
            experience_years=4.0,
            roles=["Backend-разработчик"],
            skills=["Redis"],
            custom_skills=["Tarantool"],
            about="Пишу серверный код.",
        ),
        "contacts": PdfContacts(email="anna@example.com", telegram="@anna_dev"),
    }
    values.update(overrides)
    return ProfilePdfModel(**values)


def pdf_text(data: bytes) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)


# --- шаблон и экранирование (без WeasyPrint) -----------------------------------------------------------------


def html_of(value: ProfilePdfModel, compact: bool = False) -> str:
    return render._environment().get_template("profile.html").render(**render._context(value, compact))


def test_template_escapes_everything_the_candidate_types() -> None:
    hostile = model(
        full_name="<b>Иван</b> {{ 7*7 }}",
        declared=PdfDeclaredBlock(
            about='<img src="http://mailpit:8025/x.png"> <link href="file:///etc/passwd"> <script>alert(1)</script>',
            custom_skills=["<i>тег</i>"],
        ),
        contacts=PdfContacts(link="https://example.com/?a=1&b=<2>"),
    )
    html = html_of(hostile)
    body = html.split("</style>", 1)[1]
    assert (
        "<img" not in body and "<link" not in body and "<script" not in body and "<b>" not in body and "<i>" not in body
    )
    assert "&lt;img src=&#34;http://mailpit:8025/x.png&#34;&gt;" in body and "49" not in body
    # Ссылка кандидата печатается текстом, а не гиперссылкой.
    assert "<a " not in html and "https://example.com/?a=1&amp;b=&lt;2&gt;" in html
    # Все адреса ресурсов в документе — только шрифты из каталога репозитория.
    urls = re.findall(r"url\(\"([^\"]+)\"\)", html)
    assert urls and all(url.startswith(render.FONTS_DIR.as_uri()) for url in urls)
    assert re.search(r"<[^>]*\b(?:src|href)=", body) is None  # в разметке документа нет ни одного внешнего адреса


def test_template_has_no_salary_and_all_blocks() -> None:
    html = html_of(model())
    assert "зарплат" not in html.lower() and "приглашен" not in html.lower() and "подборк" not in html.lower()
    for block in ("Категория", "Подтверждённые навыки", "Достижения ФСП", "Заявлено кандидатом", "Контакты"):
        assert block in html
    assert "Подтверждённых достижений ФСП в профиле нет" in html_of(model(fsp=None))
    assert "Категория пока не определена" in html_of(model(category=None, level=None))
    assert not any("salary" in name for name in ProfilePdfModel.model_fields)


def test_experience_is_printed_with_plural() -> None:
    assert render._years(4.0) == "4 года" and render._years(1.0) == "1 год" and render._years(11.0) == "11 лет"
    assert render._years(3.5) == "3,5 года"
    assert "4 года" in html_of(model())


def test_file_name() -> None:
    assert model().file_name == "profile_К-04217_20261006.pdf"


def test_fetcher_allows_only_bundled_fonts() -> None:
    fetcher = render.FontOnlyFetcher()
    font = (render.FONTS_DIR / "Inter-Regular.ttf").as_uri()
    assert fetcher._is_allowed_font(font)
    assert fetcher._is_allowed_font(font.replace("file://", "file://localhost"))
    for url in (
        "http://mailpit:8025/",
        "https://example.com/x.ttf",
        "file:///etc/passwd",
        "file://attacker/share/Inter-Regular.ttf",
        (render.FONTS_DIR / ".." / "render.py").as_uri(),
        (render.FONTS_DIR / ".." / "fonts" / ".." / "templates" / "profile.html").as_uri(),
        (render.FONTS_DIR / "Inter-OFL.txt").as_uri(),  # не шрифт
        (render.FONTS_DIR / "no-such.ttf").as_uri(),
        "data:font/ttf;base64,AAAA",
        "ftp://example.com/Inter-Regular.ttf",
        "",
    ):
        assert not fetcher._is_allowed_font(url), url
        with pytest.raises(ValueError):
            fetcher.fetch(url)
    assert len(fetcher.blocked) == fetcher.requested.__len__() > 0


def test_fonts_are_bundled_with_licences() -> None:
    names = {path.name for path in render.FONTS_DIR.iterdir()}
    assert {"Inter-Regular.ttf", "Inter-Bold.ttf", "JetBrainsMono-Regular.ttf"} <= names
    assert any("OFL" in name for name in names)


# --- настоящий рендер (в контейнере api) ---------------------------------------------------------------------


@needs_weasyprint
def test_pdf_has_cyrillic_and_embedded_fonts() -> None:
    data = service.render_profile_pdf(model())
    assert data.startswith(b"%PDF-")
    reader = PdfReader(io.BytesIO(data))
    assert 1 <= len(reader.pages) <= 2
    text = pdf_text(data)
    for expected in (
        "Смирнова Анна Сергеевна",
        "К-04217",
        "Backend · Middle",
        "Python",
        "Призёр регионального этапа",
        "anna@example.com",
        "@anna_dev",
        "Tarantool",
    ):
        assert expected in text, expected
    assert "зарплат" not in text.lower()
    fonts = {
        str(font.get_object().get("/BaseFont", ""))
        for page in reader.pages
        for font in page["/Resources"]["/Font"].values()  # type: ignore[union-attr]
    }
    assert any("Inter" in name for name in fonts), fonts  # шрифт из репозитория встроен в файл


@needs_weasyprint
def test_pdf_text_is_deterministic() -> None:
    assert pdf_text(service.render_profile_pdf(model())) == pdf_text(service.render_profile_pdf(model()))


@needs_weasyprint
def test_pdf_has_no_links_and_stays_within_two_pages() -> None:
    skills = [
        EvidenceItem(
            skill=Ref(code=f"s{i}", title=f"Навык номер {i}"),
            kind=EvidenceKind.TEST,
            kind_label="Тест",
            detail="Подробное пояснение, откуда взялось подтверждение",
            confirmed_at=GENERATED,
        )
        for i in range(120)
    ]
    big = model(
        skills=skills,
        fsp=PdfFspBlock(
            headline="Итоги", lines=[f"Достижение {i} в соревновании по программированию" for i in range(40)]
        ),
        declared=PdfDeclaredBlock(roles=["Роль"] * 5, skills=[f"Навык {i}" for i in range(30)], about="Текст. " * 140),
        contacts=PdfContacts(email="anna@example.com", link="https://github.com/anna-demo"),
    )
    data = service.render_profile_pdf(big)
    assert len(PdfReader(io.BytesIO(data)).pages) <= 2
    assert b"/URI" not in data and b"/Link" not in data  # ссылка кандидата — текст
    assert "https://github.com/anna-demo" in pdf_text(data)


@needs_weasyprint
def test_hostile_about_makes_no_network_or_file_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    fetchers: list[render.FontOnlyFetcher] = []

    def recording() -> render.FontOnlyFetcher:
        fetchers.append(render.FontOnlyFetcher())
        return fetchers[-1]

    def no_network(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("PDF-профиль обратился к сети")

    monkeypatch.setattr(render, "make_fetcher", recording)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    about = "<img src=http://mailpit:8025/> <link href=file:///etc/passwd> <style>@import url(http://mailpit:8025/x.css)</style>"
    data = service.render_profile_pdf(
        model(declared=PdfDeclaredBlock(about=about), contacts=PdfContacts(link="https://example.com/"))
    )
    requested = [url for fetcher in fetchers for url in fetcher.requested]
    assert requested  # шрифты запрошены
    assert all(Path(url.removeprefix("file://")).parent == render.FONTS_DIR for url in requested), requested
    assert all(not fetcher.blocked for fetcher in fetchers)
    assert "<img src=http://mailpit:8025/>" in pdf_text(data).replace("\n", " ")  # разметка осталась текстом


@needs_weasyprint
def test_pdf_without_category_and_fsp() -> None:
    text = pdf_text(service.render_profile_pdf(model(category=None, level=None, skills=[], fsp=None, declared=None)))
    assert "Категория пока не определена" in text and "Подтверждённых достижений ФСП в профиле нет" in text
