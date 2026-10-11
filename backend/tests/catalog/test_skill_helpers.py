"""Чистые помощники `catalog.service` по навыкам специализации (сид и вклад навыков в силу профиля)."""

from __future__ import annotations

from app.modules.catalog import service


def _entry(code: str):  # type: ignore[no-untyped-def]
    return next(skill for skill in service.skill_entries() if skill.code == code)


def test_skills_for_specialization_tagged_non_soft_primary_first() -> None:
    for spec in service.specialization_codes():
        codes = service.skills_for_specialization(spec)
        assert codes, spec
        assert len(set(codes)) == len(codes)
        entries = [_entry(code) for code in codes]
        assert all(entry.kind != "soft" and spec in entry.specializations for entry in entries)
        # Сначала навыки, для которых специализация основная; после первого «неосновного» основных уже нет.
        primary_flags = [entry.specializations[0] == spec for entry in entries]
        assert primary_flags == sorted(primary_flags, reverse=True)
        # Ничего не потеряно.
        expected = {s.code for s in service.skill_entries() if s.kind != "soft" and spec in s.specializations}
        assert set(codes) == expected
    assert "pytest" in service.skills_for_specialization("qa")
    assert service.skills_for_specialization("no_such") == ()


def test_skills_for_specialization_is_stable() -> None:
    assert service.skills_for_specialization("frontend") == service.skills_for_specialization("frontend")


def test_generic_skills_have_no_specialization_and_no_soft() -> None:
    codes = service.generic_skills()
    assert codes
    order = [skill.code for skill in service.skill_entries()]
    assert list(codes) == sorted(codes, key=order.index)
    for code in codes:
        entry = _entry(code)
        assert entry.kind != "soft" and entry.specializations == ()


def test_is_skill_relevant() -> None:
    assert service.is_skill_relevant("pytest", "qa")
    assert not service.is_skill_relevant("pytest", "infosec")
    assert not service.is_skill_relevant("no_such_skill", "qa")
    assert not service.is_skill_relevant("pytest", "no_such")
    # Общие навыки и софт-скиллы к специализации не относятся.
    generic = service.generic_skills()[0]
    soft = next(skill.code for skill in service.skill_entries() if skill.kind == "soft")
    for spec in service.specialization_codes():
        assert not service.is_skill_relevant(generic, spec)
        assert not service.is_skill_relevant(soft, spec)
        assert all(service.is_skill_relevant(code, spec) for code in service.skills_for_specialization(spec))
