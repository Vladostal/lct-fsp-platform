"""T7. Приватность и фасад: блок работодателя побайтно одинаков во всех состояниях без истории, до раскрытия нет
подробностей, после отвязки блок нейтрален, сигнал и подтверждения навыков, `render_evidence`, пакетная загрузка."""

# ruff: noqa: C408  (dict(...) в таблицах параметров читается лучше литерала)

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from uuid import UUID

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.core import clock
from app.fsp_mock import reference as ref
from app.fsp_mock import registry_service
from app.modules.fsp import constants as c
from app.modules.fsp import service
from app.modules.fsp.dto import FspEmployerBlock, FspSubject
from app.modules.fsp.gateway import factory
from app.modules.fsp.gateway.base import FspError
from app.modules.fsp.models import ExternalIdentity
from tests.fsp import mockdata

AS_OF = mockdata.TODAY
TITLE = "Кубок России по продуктовому программированию 2026, финал"
TEAM = "Команда Секрет"


def link(db: Session, make_user: Callable[..., object], fsp_id: UUID | str) -> UUID:
    user = make_user("candidate")
    service.seed_link(db, user.id, str(fsp_id))  # type: ignore[attr-defined]
    return user.id  # type: ignore[attr-defined]


def strong_athlete(db: Session) -> UUID:
    """Призёр финала кубка в команде (капитан), с разрядом и ролью тренера в другом соревновании."""
    fsp_id = mockdata.add_athlete(db)
    result = mockdata.add_result(
        db,
        fsp_id,
        title=TITLE,
        place=2,
        entries_count=16,
        team=5,
        captain=True,
        discipline="product",
        kind="cup",
        stage="final",
        series_code="2026-ru-cup-product",
        days_ago=20,
    )
    assert result.title == TITLE
    mockdata.add_result(db, fsp_id, title="Чемпионат округа 2025", place=4, entries_count=10, level="interregional",
                        days_ago=300, role="coach", team=3)  # fmt: skip
    mockdata.add_rank(db, fsp_id, "kms", discipline="product")
    return fsp_id


def block(db: Session, user_id: UUID, **overrides: object) -> FspEmployerBlock:
    params: dict[str, object] = dict(
        specialization="backend", show_summary=True, reveal_details=True, disclosed=False, as_of=AS_OF
    )
    params.update(overrides)
    return service.employer_block(db, user_id, **params)  # type: ignore[arg-type]


def neutral_json() -> str:
    return FspEmployerBlock(mode="none", neutral_text=c.NEUTRAL_TEXT).model_dump_json()


def states_without_history(db: Session, make_user: Callable[..., object]) -> dict[str, UUID]:
    """Пользователи в состояниях 1–6, 8 и 9 приложения D, §7.1: у работодателя во всех блок `none`."""
    users: dict[str, UUID] = {}
    users["not_linked"] = make_user("candidate").id  # type: ignore[attr-defined]
    ghost = mockdata.add_athlete(db)
    db.delete(db.get(registry_athlete(), ghost))  # записи спортсмена в реестре нет
    db.flush()
    users["athlete_not_found"] = link(db, make_user, ghost)
    users["no_results"] = link(db, make_user, mockdata.add_athlete(db))
    users["no_counted"] = link(db, make_user, no_counted_athlete(db))
    users["hidden"] = link(db, make_user, strong_athlete(db))
    users["sync_failed"] = make_user("candidate").id  # type: ignore[attr-defined]
    db.add(
        ExternalIdentity(
            user_id=users["sync_failed"],
            provider="fsp",
            issuer="urn:fsp-mock",
            subject="x",
            fsp_id=str(mockdata.add_athlete(db)),
            provider_mode="mock",
            claims={},
            consent_version="fsp-data-1",
            linked_at=clock.real_now(),
        )
    )
    unlinked = link(db, make_user, strong_athlete(db))
    service.unlink(db, unlinked, reason="user")
    users["unlinked"] = unlinked
    db.commit()
    return users


def registry_athlete() -> type:
    from app.fsp_mock.models import Athlete

    return Athlete


def no_counted_athlete(db: Session) -> UUID:
    from app.fsp_mock.models import Entry

    fsp_id = mockdata.add_athlete(db)
    result = mockdata.add_result(db, fsp_id, place=1)
    entry = db.get(Entry, result.entry_id)
    assert entry is not None
    entry.result_status = "dsq"
    entry.place = None
    db.flush()
    return fsp_id


def test_neutral_block_is_byte_identical_in_all_states_without_history(
    db: Session, make_user: Callable[..., object]
) -> None:
    users = states_without_history(db, make_user)
    expected = neutral_json()
    for name, user_id in users.items():
        show_summary = name != "hidden"
        for disclosed in (False, True):
            # Подробности раскрытой паре открывает только явный выбор `fsp_details` (reveal_details); у скрывшего — нет.
            result = block(
                db, user_id, show_summary=show_summary, disclosed=disclosed, reveal_details=show_summary and disclosed
            )
            assert result.model_dump_json() == expected, (name, disclosed)
    assert block(db, users["hidden"], show_summary=True).mode == "summary"  # тот же кандидат с показом — не нейтрален
    explicit = block(db, users["hidden"], show_summary=False, disclosed=True, reveal_details=True)
    assert explicit.mode == "detailed"  # явный выбор кандидата в диалоге принятия приглашения (Арх. 7.7)


def test_signals_are_zero_and_hidden_in_all_states_without_history(
    db: Session, make_user: Callable[..., object]
) -> None:
    users = states_without_history(db, make_user)
    subjects = [
        FspSubject(user_id=uid, specialization="backend", show_summary=name != "hidden") for name, uid in users.items()
    ]
    signals = service.get_signals(db, subjects, as_of=AS_OF)
    for name, user_id in users.items():
        signal = signals[user_id]
        assert signal.value == 0 and signal.band == "none" and signal.verified is False, name
        assert signal.public is None and signal.contributions == [], name
        assert signal.visible is (name not in {"not_linked", "unlinked", "hidden"}), name
    assert service.verified_user_ids(db, subjects) == set()
    twin_values = {signals[users[name]].value for name in ("not_linked", "no_results", "athlete_not_found", "hidden")}
    assert twin_values == {0.0}


def test_before_disclosure_nothing_but_summary(db: Session, make_user: Callable[..., object]) -> None:
    fsp_id = strong_athlete(db)
    user = link(db, make_user, fsp_id)
    result = block(db, user, disclosed=False, reveal_details=True)
    assert result.mode == "summary" and result.summary is not None and result.note == c.NOTE_BEFORE_DISCLOSURE
    assert result.achievements == [] and result.credentials == [] and result.leadership is None
    dumped = result.model_dump_json()
    forbidden = [TITLE, TEAM, "Тестовая команда", "kms", "КМС", str(fsp_id), "protocol", "RU-", "2026-0", "2025-"]
    for text in forbidden:
        assert text not in dumped, text
    assert "место" not in (result.summary.short or "") or "призовое" in result.summary.short
    assert result.source is not None and result.source.label == c.SOURCE_LABEL["mock"]


def test_after_disclosure_detailed_and_reveal_off(db: Session, make_user: Callable[..., object]) -> None:
    fsp_id = strong_athlete(db)
    user = link(db, make_user, fsp_id)
    detailed = block(db, user, disclosed=True, reveal_details=True)
    assert detailed.mode == "detailed" and detailed.neutral_text is None
    titles = [item.competition_title for item in detailed.achievements]
    assert TITLE in titles and "Чемпионат округа 2025" in titles  # результат и роль тренера
    first = detailed.achievements[0]
    assert first.place_label == "2 место из 16" and first.is_captain and first.role_label == "капитан команды"
    assert first.protocol_url and first.team_size == 5 and first.uncounted_reason is None and first.norm is None
    assert [item.label for item in detailed.credentials] == ["КМС"] and detailed.credentials[0].active
    assert detailed.leadership is not None and "капитан в 1 соревновании" in detailed.leadership.label
    assert "тренер команды" in detailed.leadership.label
    dumped = detailed.model_dump_json()
    assert str(fsp_id) not in dumped and "RU-" not in dumped
    limited = block(db, user, disclosed=True, reveal_details=False)
    assert limited.mode == "summary" and limited.note == c.NOTE_SUMMARY_ONLY and limited.achievements == []
    hidden = block(db, user, show_summary=False, disclosed=False)
    assert hidden.model_dump_json() == neutral_json()


def test_detailed_hides_uncounted_records_from_employer(db: Session, make_user: Callable[..., object]) -> None:
    fsp_id = mockdata.add_athlete(db)
    mockdata.add_result(db, fsp_id, title="Хороший результат", place=1)
    from app.fsp_mock.models import Entry

    bad = mockdata.add_result(db, fsp_id, title="Дисквалификация", place=1)
    entry = db.get(Entry, bad.entry_id)
    assert entry is not None
    entry.result_status, entry.place = "dsq", None
    db.flush()
    user = link(db, make_user, fsp_id)
    titles = [item.competition_title for item in block(db, user, disclosed=True).achievements]
    assert titles == ["Хороший результат"]
    from app.modules.fsp.screen import build_link_view

    view, _ = build_link_view(db, user, now=clock.real_now(), as_of=AS_OF, specialization="backend")
    own = {item.competition_title: item for item in view.achievements}
    assert (
        own["Дисквалификация"].uncounted_reason == "dsq" and own["Дисквалификация"].uncounted_label == "дисквалификация"
    )


def test_unlink_makes_block_neutral_even_for_disclosed_pair(db: Session, make_user: Callable[..., object]) -> None:
    user = link(db, make_user, strong_athlete(db))
    assert block(db, user, disclosed=True).mode == "detailed"
    service.unlink(db, user, reason="user")
    after = block(db, user, disclosed=True, reveal_details=True)
    assert after.model_dump_json() == neutral_json()
    assert service.is_visible(db, user, show_summary=True) is False
    signal = service.get_signals(
        db, [FspSubject(user_id=user, specialization="backend", show_summary=True)], as_of=AS_OF
    )
    assert signal[user].value == 0 and signal[user].visible is False


def test_coach_only_candidate(db: Session, make_user: Callable[..., object]) -> None:
    """Только роль тренера: сигнал 0, режим `summary` уровня 1, подтверждение «наставничество», фильтр не проходит."""
    fsp_id = mockdata.add_athlete(db)
    mockdata.add_result(db, fsp_id, title="Региональный чемпионат", place=3, entries_count=10, level="regional",
                        role="coach", team=3, days_ago=100)  # fmt: skip
    user = link(db, make_user, fsp_id)
    subject = FspSubject(user_id=user, specialization="backend", show_summary=True)
    signal = service.get_signals(db, [subject], as_of=AS_OF)[user]
    assert signal.value == 0 and signal.leadership_level == "basic" and signal.public is not None
    assert signal.public.level == 1 and signal.verified is False  # R3-tz-compliance-8
    assert service.verified_user_ids(db, [subject]) == set()
    assert block(db, user).mode == "summary"
    brief = service.link_brief(db, user)
    assert brief.status == "linked" and brief.history_status == "has_history" and brief.counted == 0
    skills = service.get_skill_evidence(db, [subject], as_of=AS_OF)[user]
    assert [item.skill_code for item in skills] == ["mentoring"]
    assert skills[0].detail_public == c.EVIDENCE_ROLE_PUBLIC and "Тренер" in skills[0].detail_full


def test_rank_only_passes_filter(db: Session, make_user: Callable[..., object]) -> None:
    fsp_id = mockdata.add_athlete(db)
    mockdata.add_rank(db, fsp_id, "r1", discipline="algo")
    user = link(db, make_user, fsp_id)
    subject = FspSubject(user_id=user, specialization="backend", show_summary=True)
    signal = service.get_signals(db, [subject], as_of=AS_OF)[user]
    assert signal.value == pytest.approx(c.RANK_FLOOR["r1"]) and signal.floor_source == "rank" and signal.verified
    assert service.verified_user_ids(db, [subject]) == {user}


def test_signal_skills_and_leadership_for_strong_candidate(db: Session, make_user: Callable[..., object]) -> None:
    fsp_id = strong_athlete(db)
    user = link(db, make_user, fsp_id)
    subject = FspSubject(user_id=user, specialization="backend", show_summary=True)
    signal = service.get_signals(db, [subject], as_of=AS_OF)[user]
    assert signal.visible and signal.verified and signal.band in {"medium", "high"} and signal.counted == 1
    assert signal.version == c.FSP_SIGNAL_VERSION and 0 < signal.value < 1 and len(signal.contributions) == 1
    assert signal.leadership_level == "strong"  # тренер команды на соревновании окружного уровня
    skills = {item.skill_code: item for item in service.get_skill_evidence(db, [subject], as_of=AS_OF)[user]}
    assert {"teamwork", "mvp_delivery", "leadership", "mentoring"} <= set(skills)
    assert not set(skills) & {"python", "java", "react", "sql"}
    teamwork = skills["teamwork"]
    assert teamwork.detail_public == "достижение ФСП · продуктовое программирование"
    assert TITLE in teamwork.detail_full and "2 место из 16" in teamwork.detail_full
    hidden = FspSubject(user_id=user, specialization="backend", show_summary=False)
    assert service.get_skill_evidence(db, [hidden], as_of=AS_OF)[user] == []
    assert service.get_signals(db, [hidden], as_of=AS_OF)[user].value == 0


def test_render_evidence(db: Session, make_user: Callable[..., object]) -> None:
    user = link(db, make_user, strong_athlete(db))
    subject = FspSubject(user_id=user, specialization="backend", show_summary=True)
    signal = service.get_signals(db, [subject], as_of=AS_OF)[user]
    fact = signal.contributions[0].fact_id
    before = service.render_evidence(db, user, [fact], show_summary=True, reveal_details=True, disclosed=False)
    assert before[fact] is not None and before[fact].startswith("Достижение ФСП: ") and TITLE not in before[fact]
    after = service.render_evidence(db, user, [fact], show_summary=True, reveal_details=True, disclosed=True)
    assert after[fact] == f"Достижение ФСП: {TITLE}, 2 место из 16"
    off = service.render_evidence(db, user, [fact], show_summary=True, reveal_details=False, disclosed=True)
    assert TITLE not in (off[fact] or "")
    hidden = service.render_evidence(db, user, [fact], show_summary=False, reveal_details=True, disclosed=True)
    assert hidden[fact] is None
    unknown = service.render_evidence(db, user, [UUID(int=1)], show_summary=True, reveal_details=True, disclosed=True)
    assert unknown == {UUID(int=1): None}
    service.unlink(db, user, reason="user")
    gone = service.render_evidence(db, user, [fact], show_summary=True, reveal_details=True, disclosed=True)
    assert gone[fact] is None


def test_pdf_block(db: Session, make_user: Callable[..., object]) -> None:
    user = link(db, make_user, strong_athlete(db))
    own = service.pdf_block(db, user, audience="self", specialization="backend", show_summary=False,
                            reveal_details=False, as_of=AS_OF)  # fmt: skip
    assert own.mode == "detailed" and len(own.achievements) == 2
    for_employer = service.pdf_block(db, user, audience="employer", specialization="backend", show_summary=True,
                                     reveal_details=False, as_of=AS_OF)  # fmt: skip
    assert for_employer.mode == "summary"
    detailed = service.pdf_block(db, user, audience="employer", specialization="backend", show_summary=True,
                                 reveal_details=True, as_of=AS_OF)  # fmt: skip
    assert detailed.mode == "detailed"


def test_employer_side_never_calls_the_registry(
    db: Session, make_user: Callable[..., object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Запросы работодателя синхронизацию не запускают никогда: время ответа не зависит от реестра."""
    user = link(db, make_user, strong_athlete(db))

    def boom() -> object:
        raise AssertionError("фасад обратился к реестру")

    monkeypatch.setattr(factory, "get_fsp_gateway", boom)
    subject = FspSubject(user_id=user, specialization="backend", show_summary=True)
    service.get_signals(db, [subject], as_of=AS_OF)
    service.get_skill_evidence(db, [subject], as_of=AS_OF)
    service.verified_user_ids(db, [subject])
    block(db, user, disclosed=True)
    service.render_evidence(db, user, [], show_summary=True, reveal_details=True, disclosed=True)
    assert issubclass(FspError, Exception)


def test_batch_functions_use_at_most_three_queries(db: Session, make_user: Callable[..., object]) -> None:
    users = [link(db, make_user, strong_athlete(db)) for _ in range(12)]
    users += [make_user("candidate").id for _ in range(5)]  # type: ignore[attr-defined]
    subjects = [FspSubject(user_id=uid, specialization="backend", show_summary=True) for uid in users]
    db.commit()
    statements: list[str] = []
    engine = db.get_bind()

    @event.listens_for(engine, "before_cursor_execute")
    def count(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
        if not statement.startswith(("SAVEPOINT", "RELEASE")):
            statements.append(statement)

    try:
        service.get_signals(db, subjects, as_of=AS_OF)
        assert 0 < len(statements) <= 3, statements
        statements.clear()
        service.verified_user_ids(db, subjects)
        assert 0 < len(statements) <= 3
        statements.clear()
        service.get_skill_evidence(db, subjects, as_of=AS_OF)
        assert 0 < len(statements) <= 3
    finally:
        event.remove(engine, "before_cursor_execute", count)


def test_no_data_keeps_registry_isolated(db: Session) -> None:
    """Платформа не читает схему `fspmock`: модели `fsp` не ссылаются на её таблицы."""
    from app.modules.fsp import models

    schemas = {table.schema for table in (getattr(models, name).__table__ for name in dir(models)
                                          if hasattr(getattr(models, name), "__table__"))}  # fmt: skip
    assert schemas == {None}
    assert registry_service.get_failure_mode(db) == "none" and ref.CLIENT_ID and date(2026, 1, 1)
    assert db.scalar(select(ExternalIdentity.id)) is None
