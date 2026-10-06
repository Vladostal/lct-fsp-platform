"""Общие правила слоя shared: вилка, способ связи, тексты, перечисления (Арх. 4.6, 8.2, 6.10)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.core.errors import ApiException
from app.shared import enums, salary, text
from app.shared.contact_method import (
    contact_method_label,
    normalize_contact_value,
    validate_contact_method,
)
from app.shared.enums import ContactKind
from app.shared.schemas import ApiError, CategoryRef, EvidenceItem, Page, Ref

# --- вилка ----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("salary_from", "salary_to"), [(180_000, 240_000), (10_000, 15_000), (100_000, 100_000), (2_000_000, 3_000_000)]
)
def test_valid_ranges(salary_from, salary_to):
    salary.validate_range(salary_from, salary_to)
    assert salary.range_error(salary_from, salary_to) is None


@pytest.mark.parametrize(
    ("salary_from", "salary_to", "code", "field"),
    [
        (9_999, 12_000, "salary_out_of_bounds", "salary_from"),
        (100_000, 3_000_001, "salary_out_of_bounds", "salary_to"),
        (200_000, 150_000, "salary_order", "salary_to"),
        (100_000, 150_001, "salary_range_too_wide", "salary_to"),
    ],
)
def test_invalid_ranges(salary_from, salary_to, code, field):
    with pytest.raises(ApiException) as error:
        salary.validate_range(salary_from, salary_to)
    assert (error.value.status, error.value.code) == (422, code)
    assert [item.name for item in error.value.fields] == [field]


def test_too_wide_range_names_allowed_upper_bound():
    """Арх. 4.6: ошибка ширины несёт params.max_to — допустимый верх для текста ошибки."""
    with pytest.raises(ApiException) as error:
        salary.validate_range(180_000, 300_000)
    assert error.value.params == {"max_to": 270_000}
    assert salary.max_salary_to(100_001) == 150_001  # floor(100001 * 1.5)
    assert salary.max_salary_to(2_500_000) == salary.SALARY_MAX


def test_out_of_bounds_error_carries_bounds():
    with pytest.raises(ApiException) as error:
        salary.validate_range(5, 7)
    assert error.value.params == {"salary_min": 10_000, "salary_max": 3_000_000}


def test_min_salary_ladder():
    ladder = salary.min_salary_ladder()
    assert (ladder[0], ladder[-1], len(ladder)) == (40_000, 600_000, 29)
    assert all(salary.is_on_ladder(step) for step in ladder) and salary.is_on_ladder(None)
    assert not any(salary.is_on_ladder(value) for value in (0, 20_000, 50_000, 620_000, 40_001))


def test_public_salary_limits_match_constants():
    assert salary.PUBLIC_SALARY_LIMITS["salary_max_ratio"] == 1.5
    assert salary.PUBLIC_SALARY_LIMITS["min_salary_step"] == salary.MIN_SALARY_STEP == 20_000


# --- способ связи ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "value", "expected"),
    [
        ("email", " HR@Example.com ", "hr@example.com"),
        ("phone", "8 (999) 123-45-67", "+79991234567"),
        ("phone", "+7 999 123 45 67", "+79991234567"),
        ("phone", "+44 20 7946 0958", "+442079460958"),
        ("telegram", "@hr_orbita", "@hr_orbita"),
        ("telegram", "https://t.me/hr_orbita", "@hr_orbita"),
        ("other", "  Напишите   в форму на сайте ", "Напишите в форму на сайте"),
    ],
)
def test_contact_value_is_normalized(kind, value, expected):
    method = validate_contact_method(kind, value)
    assert method.kind == ContactKind(kind) and method.value == expected


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        ("email", "не адрес"),
        ("email", "a@b"),
        ("phone", "12345"),
        ("phone", "+7 999 abc"),
        ("phone", "1" * 16),
        ("telegram", "hr_orbita"),
        ("telegram", "@abc"),
        ("telegram", "@имя_кириллицей"),
        ("other", "ab"),
        ("other", "x" * 201),
    ],
)
def test_contact_value_must_match_kind(kind, value):
    assert normalize_contact_value(ContactKind(kind), value) is None
    with pytest.raises(ApiException) as error:
        validate_contact_method(kind, value, field="contact_value")
    assert (error.value.status, error.value.code) == (422, "validation_error")
    assert [(item.name, item.code) for item in error.value.fields] == [("contact_value", "contact_value_invalid")]


def test_contact_method_label():
    assert contact_method_label(validate_contact_method("telegram", "@hr_orbita")) == "Telegram: @hr_orbita"


# --- тексты ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("n", "expected"),
    [(0, "дней"), (1, "день"), (2, "дня"), (4, "дня"), (5, "дней"), (11, "дней"), (12, "дней"), (14, "дней"),
     (21, "день"), (22, "дня"), (25, "дней"), (101, "день"), (111, "дней"), (112, "дней"), (1002, "дня")],
)  # fmt: skip
def test_plural(n, expected):
    assert text.plural(n, "день", "дня", "дней") == expected


def test_count_phrase_uses_non_breaking_space():
    assert text.count_phrase(3, "кандидат", "кандидата", "кандидатов") == "3 кандидата"


@pytest.mark.parametrize(
    ("titles", "expected"),
    [
        ([], ""),
        (["Python"], "Python"),
        (["Python", "PostgreSQL"], "Python и PostgreSQL"),
        (["Python", "PostgreSQL", "Kafka"], "Python, PostgreSQL и Kafka"),
        (["Python", "PostgreSQL", "Kafka", "Docker"], "Python, PostgreSQL, Kafka и ещё 1"),
        (["A", "B", "C", "D", "E", "F"], "A, B, C и ещё 3"),
    ],
)
def test_join_titles(titles, expected):
    assert text.join_titles(titles) == expected


def test_join_titles_limit():
    assert text.join_titles(["A", "B", "C"], limit=2) == "A, B и ещё 1"


def test_fmt_date_uses_app_timezone():
    assert text.fmt_date(date(2026, 10, 5)) == "05.10.2026"
    assert text.fmt_date(datetime(2026, 10, 5, 22, 30, tzinfo=UTC)) == "06.10.2026"  # в Москве уже 6-е


def test_fmt_money():
    assert text.fmt_money(180_000) == "180 000 ₽"
    assert text.fmt_salary_range(180_000, 240_000) == "180 000 – 240 000 ₽"


# --- перечисления и схемы -------------------------------------------------------------------------------------------

EXPECTED_ENUMS: dict[str, list[str]] = {
    "Role": ["candidate", "employer"],
    "ConsentKind": ["processing", "publication", "fsp_data"],
    "WorkFormat": ["office", "hybrid", "remote"],
    "ContactKind": ["email", "phone", "telegram", "other"],
    "TrustLevel": ["basic", "verified"],
    "VisibilityState": ["not_ready", "unpublished", "paused", "visible"],
    "PauseReason": ["manual", "auto_silence"],
    "DiscloseField": ["email", "phone", "telegram", "link", "fsp_details"],
    "DisclosureSource": ["invitation", "application"],
    "AccessKind": ["contacts_disclosed", "contacts_viewed", "pdf_downloaded", "export_downloaded"],
    "EvidenceKind": ["test", "pulse", "fsp", "declared", "none"],
    "SessionStatus": ["in_progress", "finished", "expired"],
    "SessionKind": ["initial", "lower", "higher", "retake"],
    "TestOutcome": ["not_confirmed", "borderline", "confirmed", "confirmed_with_margin"],
    "ItemKind": ["numeric_input", "text_input", "single_choice", "multi_choice", "pick_line", "order_blocks"],
    "ItemStatus": ["pending", "shown", "answered", "skipped", "unreached", "not_shown"],
    "SlotRole": ["main", "stretch", "ext"],
    "FamilyStatus": ["draft", "active", "suspect", "quarantined", "retired"],
    "VariantStatus": ["active", "demo", "retired"],
    "SkillVerdict": ["confirmed", "partial", "not_confirmed"],
    "EvidenceSource": ["test", "pulse"],
    "GradeChangeKind": ["initial", "up", "down", "specialization_change"],
    "ClaimSource": ["survey", "resume", "manual"],
    "PulseTaskStatus": ["draft", "active", "archived"],
    "PulseAssignmentStatus": ["offered", "started", "submitted", "skipped", "expired"],
    "PulseSource": ["shortlist", "refresh"],
    "NeedStatus": ["active", "archived"],
    "Relation": ["exact", "lower_with_margin", "higher"],
    "FitBand": ["strong", "good", "partial"],
    "DiffMark": ["new", "up", "down", "same"],
    "ExposureSource": ["shortlist", "bank"],
    "InvitationStatus": ["sent", "viewed", "accepted", "declined", "expired", "withdrawn", "bounced"],
    "DeclineReason": ["salary", "stack", "format", "company", "not_looking", "other"],
    "ConditionKind": ["salary_from", "work_format"],
    "EventCode": ["sent", "bounced", "viewed", "accepted", "declined", "expired", "withdrawn", "revised",
                  "contact_marked", "contact_confirmed", "contact_denied", "complaint_filed"],
    "EventActor": ["employer", "candidate", "system"],
    "ComplaintReason": ["fake_offer", "terms_mismatch", "spam", "rude", "other"],
    "ComplaintStatus": ["open", "upheld", "dismissed"],
    "VacancyStatus": ["draft", "published", "closed"],
    "ApplicationStatus": ["sent", "viewed", "accepted", "declined", "expired", "withdrawn"],
    "ApplicationDeclineReason": ["stack", "grade", "closed", "other"],
    "LinkAttemptOutcome": ["linked", "cancelled", "conflict", "minor", "auth_error", "unavailable", "expired",
                           "user_mismatch", "superseded"],
    "SyncTrigger": ["link", "manual", "stale", "cli", "seed"],
    "SyncOutcome": ["ok_changed", "ok_unchanged", "in_progress", "failed_unavailable", "failed_contract",
                    "failed_auth", "failed_timeout", "unlinked_revoked", "unlinked_minor"],
    "CredentialKind": ["rank"],
    "DemoPersona": ["responsive", "selective", "expensive", "silent"],
}  # fmt: skip


def test_enums_match_architecture_table_8_2():
    from enum import StrEnum

    declared = {
        name: [member.value for member in obj]
        for name, obj in vars(enums).items()
        if isinstance(obj, type) and issubclass(obj, StrEnum) and obj is not StrEnum
    }
    assert declared == EXPECTED_ENUMS


def test_enum_check_builds_named_constraint():
    from app.core.db import NAMING_CONVENTION, enum_check

    constraint = enum_check("role", enums.Role)
    assert constraint.name == "role"
    assert str(constraint.sqltext) == "role IN ('candidate', 'employer')"
    assert NAMING_CONVENTION["ck"] == "ck_%(table_name)s_%(constraint_name)s"


def test_shared_schemas_shape():
    backend, middle = Ref(code="backend", title="Backend"), Ref(code="middle", title="Middle")
    category = CategoryRef(code="backend:middle", title="Backend · Middle", specialization=backend, grade=middle)
    item = EvidenceItem(skill=Ref(code="python", title="Python"), priority="must", kind="test", kind_label="тест")
    assert item.model_dump(mode="json")["kind"] == "test" and item.via_skill is None
    page = Page[CategoryRef](items=[category], next_cursor=None)
    assert page.model_dump()["items"][0]["grade"] == {"code": "middle", "title": "Middle"}
    assert set(Page[Ref].model_json_schema()["properties"]) == {"items", "next_cursor"}
    assert ApiError(code="x", message="y").model_dump(exclude_none=True) == {"code": "x", "message": "y"}
