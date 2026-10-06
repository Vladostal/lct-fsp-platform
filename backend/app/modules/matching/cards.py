"""Карточка кандидата, предпросмотр, собственные доказательства, PDF-профиль, объяснение для приглашения
(Арх. 6.9, 6.10, 6.14, 4.9).

Доступ к карточке: кандидат сейчас видим либо пара раскрыта; иначе 404 — в том числе для кандидата из
сохранённой версии, который поставил паузу или отозвал публикацию. Контактов и минимума зарплаты в карточке нет.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiException, not_found
from app.modules.assessment import service as assessment
from app.modules.fsp import service as fsp
from app.modules.fsp.dto import FspEmployerBlock
from app.modules.identity import service as identity
from app.modules.matching import constants as C
from app.modules.matching import exposure, needs, snapshots, support
from app.modules.matching.dto import InvitationExplain, ShortlistItemView, ShortlistQuery
from app.modules.matching.evidence import Pool, load_pool
from app.modules.matching.explain import (
    MatchExplanation,
    ReadRules,
    apply_read_rules,
    project_employer,
    project_why,
    project_why_bank,
    skill_item,
    sorted_skills,
    strength_contributions,
    top_evidence,
)
from app.modules.matching.features import CONFIRMED_KINDS, CandidateFeatures
from app.modules.matching.live import Live, fsp_texts, load_live, read_explanation
from app.modules.matching.models import Need, NeedPin, ShortlistItem, ShortlistSnapshot
from app.modules.matching.ranking import rank_need, score_candidate
from app.modules.matching.schemas import (
    CandidateCardEmployerView,
    CandidateEvidenceView,
    DeclaredView,
    MatchExplanationEmployerView,
    StrengthView,
)
from app.modules.matching.scoring import first_failed_filter, sections_for, shortlist_seed, strength
from app.modules.profile import service as profile
from app.modules.profile.dto import (
    ContactsDTO,
    PdfContacts,
    PdfDeclaredBlock,
    PdfFspBlock,
    PoolProfile,
    ProfilePdfModel,
)
from app.shared.enums import AccessKind, DiffMark, EvidenceKind, ExposureSource, TestOutcome, WorkFormat
from app.shared.schemas import EvidenceItem, Ref

_HOUR_SECONDS = 3600
PDF_THROTTLE_KIND = "profile_pdf"


@dataclass(slots=True)
class _Subject:
    """Кандидат карточки: признаки, профиль и живое состояние пары."""

    features: CandidateFeatures
    person: PoolProfile
    pool: Pool
    live: Live

    @property
    def candidate_id(self) -> UUID:
        return self.features.candidate_id


def _load_subject(db: Session, employer_id: UUID, candidate_id: UUID, now: datetime) -> _Subject:
    """Кандидат, которого этому работодателю можно показать; иначе 404."""
    pool = load_pool(db, employer_id, now, candidate_ids=[candidate_id], include_hidden=True)
    features = pool.features.get(candidate_id)
    if features is None:
        raise not_found()
    live = load_live(db, employer_id, {candidate_id: features.specialization_code}, now)
    if not live.shown(candidate_id):
        raise not_found()
    return _Subject(features=features, person=pool.profiles[candidate_id], pool=pool, live=live)


def _strength_view(features: CandidateFeatures) -> StrengthView:
    value = strength(features)
    return StrengthView(label=value.label, contributions=strength_contributions(value, features.fsp_signal))


def _skills(
    features: CandidateFeatures, *, own: bool = False, texts: dict[str, str | None] | None = None
) -> list[EvidenceItem]:
    """Все навыки кандидата с источниками; раскрытой паре с `fsp_details` — подробный текст факта ФСП."""
    rows: list[EvidenceItem] = []
    for item in sorted_skills(features.evidence, support.skill_title):
        override = None
        if texts and item.kind == EvidenceKind.FSP and item.ref_id:
            override = texts.get(item.ref_id)
        rows.append(skill_item(item, support.skill_title(item.skill_code), own=own, detail_override=override))
    return rows


def _fact_ids(features: CandidateFeatures) -> list[UUID]:
    found: list[UUID] = []
    for item in features.evidence.values():
        if item.kind == EvidenceKind.FSP and item.ref_id:
            try:
                found.append(UUID(item.ref_id))
            except ValueError:
                continue
    return found


def _declared(db: Session, person: PoolProfile, candidate_id: UUID, about: str | None) -> DeclaredView | None:
    """Заявленное кандидатом — по настройкам приватности; всё скрыто — `None`."""
    privacy = person.privacy
    domains: list[Ref] = []
    if privacy.show_experience:
        survey = assessment.survey_declared(db, [candidate_id]).get(candidate_id)
        domains = [Ref(code=code, title=code) for code in (survey.industry_domains if survey else [])]
    view = DeclaredView(
        city=person.city if privacy.show_city else None,
        experience_years=person.experience_years if privacy.show_experience else None,
        roles=support.role_refs(list(person.roles)) if privacy.show_experience else [],
        about=about if privacy.show_about else None,
        industry_domains=domains,
    )
    empty = view.city is None and view.experience_years is None and not view.roles and not view.about and not domains
    return None if empty else view


def _on_the_fly(subject: _Subject, query: ShortlistQuery) -> MatchExplanation | None:
    """Объяснение по запросу для кандидата, которого нет в версии; вне разделов запроса — `None`."""
    relation = sections_for(query, support.grade_codes()).get(subject.features.grade_code)
    if relation is None or subject.features.specialization_code != query.specialization_code:
        return None
    scored = score_candidate(subject.features, query, relation, support.closure)
    return snapshots.explain(subject.pool, query, scored)


def _rules(db: Session, subject: _Subject, expl: MatchExplanation) -> MatchExplanation:
    cid = subject.candidate_id
    return apply_read_rules(
        expl,
        ReadRules(
            declared_hidden=not subject.person.privacy.show_declared_stack,
            fsp_visible=subject.live.fsp_visible(cid),
            fsp_texts=fsp_texts(db, subject.live, cid, _fact_ids(subject.features)),
        ),
    )


def _stored_item(db: Session, snapshot_id: UUID, candidate_id: UUID) -> ShortlistItem | None:
    return db.get(ShortlistItem, (snapshot_id, candidate_id))


def _match(
    db: Session, subject: _Subject, need: Need, snapshot: ShortlistSnapshot | None
) -> MatchExplanationEmployerView | None:
    """Совпадение с потребностью: из версии (названной или последней), иначе — расчёт на лету."""
    cid = subject.candidate_id
    if snapshot is None and need.latest_snapshot_id:
        snapshot = db.get(ShortlistSnapshot, need.latest_snapshot_id)
    if snapshot is not None:
        item = _stored_item(db, snapshot.id, cid)
        if item is not None:
            expl = read_explanation(db, subject.live, cid, item.explanation)
            return project_employer(expl, position=item.position, in_snapshot=True)
        query = ShortlistQuery.model_validate(snapshot.query)
    else:
        query = needs.query_from_need(need)
    expl_now = _on_the_fly(subject, query)
    if expl_now is None:
        return None
    return project_employer(_rules(db, subject, expl_now), position=None, in_snapshot=False)


def _card(
    db: Session,
    subject: _Subject,
    now: datetime,
    *,
    disclosed: bool,
    display_name: str | None,
    contacts: ContactsDTO | None,
    reveal_fsp: bool,
    match: MatchExplanationEmployerView | None,
    pinned: bool | None,
    texts: dict[str, str | None] | None,
) -> CandidateCardEmployerView:
    features, person, cid = subject.features, subject.person, subject.candidate_id
    level = assessment.level_views(db, [cid], now).get(cid)
    if level is None:
        raise not_found()
    block: FspEmployerBlock = fsp.employer_block(
        db,
        cid,
        specialization=features.specialization_code,
        show_summary=person.privacy.show_fsp_summary,
        reveal_details=reveal_fsp,
        disclosed=disclosed,
        as_of=subject.pool.today,
    )
    return CandidateCardEmployerView(
        candidate_id=cid,
        public_code=person.public_code,
        display_name=display_name,
        disclosed=disclosed,
        available=person.visible,
        is_demo=person.is_demo,
        pinned=pinned,
        category=support.category_ref(features.specialization_code, features.grade_code),
        level=level,
        fsp=block,
        work_formats=[WorkFormat(value) for value in person.work_formats],
        relocation_ready=person.relocation_ready,
        # «О себе» и свои теги — свободный текст кандидата: до раскрытия не отдаются никогда.
        declared=_declared(db, person, cid, contacts.about if contacts and disclosed else None),
        custom_skills=list(contacts.custom_skills) if contacts and disclosed else [],
        match=match,
        strength=_strength_view(features),
        skills=_skills(features, texts=texts),
    )


def employer_card(
    db: Session,
    employer_id: UUID,
    candidate_id: UUID,
    now: datetime,
    *,
    need_id: UUID | None = None,
    snapshot_id: UUID | None = None,
    record: bool = True,
) -> CandidateCardEmployerView:
    """Карточка кандидата для работодателя; открытие отмечает `exposure_event.opened` (Арх. 6.9)."""
    need: Need | None = None
    snapshot: ShortlistSnapshot | None = None
    if snapshot_id is not None:
        snapshot = snapshots.get_owned_snapshot(db, employer_id, snapshot_id)
        need = needs.get_owned(db, employer_id, snapshot.need_id)
        if need_id is not None and need_id != need.id:
            raise not_found()
    elif need_id is not None:
        need = needs.get_owned(db, employer_id, need_id)
    subject = _load_subject(db, employer_id, candidate_id, now)
    today = subject.pool.today

    if record:
        # Повторное открытие той же карточки за день лимит не расходует. Демо-аккаунты общие для всех посетителей
        # стенда, лимит к ним не применяется (R3-tz-compliance-1).
        if (
            not exposure.is_opened(db, employer_id, candidate_id, today)
            and not support.is_demo_account(db, employer_id)
            and exposure.opened_count(db, employer_id, today) >= C.CARD_OPEN_LIMIT_PER_DAY
        ):
            raise support.api_error(429, "card_open_limit", params={"limit": C.CARD_OPEN_LIMIT_PER_DAY})
        source = ExposureSource.SHORTLIST if need is not None else ExposureSource.BANK
        exposure.record_opened(db, employer_id, candidate_id, today, source)

    disclosed = subject.live.is_disclosed(candidate_id)
    contacts = profile.contacts_for_pair(db, employer_id, candidate_id) if disclosed else None
    if contacts is not None and contacts.masked:
        contacts = None
    pinned: bool | None = None
    match: MatchExplanationEmployerView | None = None
    if need is not None:
        pinned = db.get(NeedPin, (need.id, candidate_id)) is not None
        match = _match(db, subject, need, snapshot)
    return _card(
        db,
        subject,
        now,
        disclosed=disclosed,
        display_name=subject.live.display_name(candidate_id),
        contacts=contacts,
        reveal_fsp=subject.live.reveal_fsp_details(candidate_id),
        match=match,
        pinned=pinned,
        texts=fsp_texts(db, subject.live, candidate_id, _fact_ids(subject.features)),
    )


# --------------------------------------------------------------------------------------------------------------------
# Кабинет кандидата
# --------------------------------------------------------------------------------------------------------------------


def _own_subject(db: Session, candidate_id: UUID, now: datetime) -> _Subject | None:
    pool = load_pool(db, None, now, candidate_ids=[candidate_id], include_hidden=True)
    features = pool.features.get(candidate_id)
    if features is None:
        return None
    live = Live(profiles={candidate_id: pool.profiles[candidate_id]}, signals=dict(pool.signals))
    return _Subject(features=features, person=pool.profiles[candidate_id], pool=pool, live=live)


def _full_name(contacts: ContactsDTO, *, with_middle: bool = False) -> str:
    parts = [contacts.last_name, contacts.first_name] if with_middle else [contacts.first_name, contacts.last_name]
    if with_middle and contacts.middle_name:
        parts.append(contacts.middle_name)
    return " ".join(part for part in parts if part)


def preview(
    db: Session, candidate_id: UUID, state: Literal["before", "after"], now: datetime
) -> CandidateCardEmployerView:
    """Карточка глазами работодателя — для самого кандидата: до и после раскрытия контактов."""
    subject = _own_subject(db, candidate_id, now)
    if subject is None:
        raise support.api_error(409, "no_category")
    after = state == "after"
    contacts = profile.own_contacts(db, candidate_id) if after else None
    reveal = after and subject.person.privacy.reveal_fsp_details
    texts: dict[str, str | None] | None = None
    facts = _fact_ids(subject.features)
    if reveal and facts:
        rendered = fsp.render_evidence(
            db,
            candidate_id,
            facts,
            show_summary=subject.person.privacy.show_fsp_summary,
            reveal_details=True,
            disclosed=True,
        )
        texts = {str(fact_id): rendered.get(fact_id) for fact_id in facts}
    return _card(
        db,
        subject,
        now,
        disclosed=after,
        display_name=_full_name(contacts) if contacts else None,
        contacts=contacts,
        reveal_fsp=reveal,
        match=None,
        pinned=None,
        texts=texts,
    )


def own_evidence(db: Session, candidate_id: UUID, now: datetime) -> CandidateEvidenceView:
    """Собственные навыки с источниками и вклады в силу (Арх. 6.10): абсолютные пороги, сравнений нет."""
    subject = _own_subject(db, candidate_id, now)
    if subject is None:
        return CandidateEvidenceView(skills=[], strength=None)
    return CandidateEvidenceView(skills=_skills(subject.features, own=True), strength=_strength_view(subject.features))


# --------------------------------------------------------------------------------------------------------------------
# PDF-профиль
# --------------------------------------------------------------------------------------------------------------------


def _throttle_pdf(db: Session, user_id: UUID) -> None:
    """PDF (WeasyPrint) — тяжёлый вызов: лимит на пользователя в час (R3-data-api-security-9)."""
    identity.throttle(db, PDF_THROTTLE_KIND, user_id=user_id, limit=C.PDF_RATE_PER_HOUR, window_s=_HOUR_SECONDS)


def _pdf_fsp(block: FspEmployerBlock) -> PdfFspBlock | None:
    if block.mode == "none" or block.summary is None:
        return None
    lines = [f"{item.competition_title} — {item.place_label}" for item in block.achievements]
    lines += [item.label for item in block.credentials]
    if block.leadership:
        lines.append(block.leadership.label)
    return PdfFspBlock(headline=block.summary.headline, lines=lines)


def _pdf_model(
    db: Session,
    subject: _Subject | None,
    contacts: ContactsDTO,
    now: datetime,
    *,
    audience: Literal["self", "employer"],
    reveal_fsp: bool,
) -> ProfilePdfModel:
    """Модель документа (Арх. 6.14). Минимума зарплаты, приглашений и позиций в подборках в ней нет."""
    model = ProfilePdfModel(
        full_name=_full_name(contacts, with_middle=True),
        public_code=contacts.public_code,
        generated_at=now,
        contacts=PdfContacts.from_contacts(contacts),
    )
    if subject is None:
        return model
    features, person, cid = subject.features, subject.person, subject.candidate_id
    model.category = support.category_ref(features.specialization_code, features.grade_code)
    model.level = assessment.level_views(db, [cid], now).get(cid)
    skills = _skills(features, own=audience == "self")
    model.skills = [item for item in skills if item.kind in CONFIRMED_KINDS]
    model.fsp = _pdf_fsp(
        fsp.pdf_block(
            db,
            cid,
            audience=audience,
            specialization=features.specialization_code,
            show_summary=person.privacy.show_fsp_summary,
            reveal_details=reveal_fsp,
            as_of=subject.pool.today,
        )
    )
    declared = _declared(db, person, cid, contacts.about)
    model.declared = PdfDeclaredBlock(
        city=declared.city if declared else None,
        experience_years=declared.experience_years if declared else None,
        roles=[item.title for item in declared.roles] if declared else [],
        industry_domains=[item.title for item in declared.industry_domains] if declared else [],
        skills=[item.skill.title for item in skills if item.kind == EvidenceKind.DECLARED],
        custom_skills=list(contacts.custom_skills),
        about=declared.about if declared else None,
    )
    return model


def employer_pdf(db: Session, employer_id: UUID, candidate_id: UUID, now: datetime) -> tuple[bytes, str]:
    """PDF-профиль раскрытой пары; пишет `pdf_downloaded` в журнал доступа. Не раскрыта — 403 `not_disclosed`.

    Маскируемая пара (демо-компания — живой кандидат) PDF не получает и записи в журнале не оставляет:
    ничего не передано (R3-mechanics-recheck-5).
    """
    contacts = profile.contacts_for_pair(db, employer_id, candidate_id)
    if contacts is None or contacts.masked:
        raise support.api_error(403, "not_disclosed")
    _throttle_pdf(db, employer_id)
    try:
        subject: _Subject | None = _load_subject(db, employer_id, candidate_id, now)
    except ApiException:
        raise support.api_error(403, "not_disclosed") from None
    assert subject is not None
    model = _pdf_model(
        db, subject, contacts, now, audience="employer", reveal_fsp=subject.live.reveal_fsp_details(candidate_id)
    )
    content = profile.render_profile_pdf(model)
    profile.log_access(db, candidate_id, employer_id, AccessKind.PDF_DOWNLOADED, None, now)
    return content, model.file_name


def own_pdf(db: Session, candidate_id: UUID, now: datetime) -> tuple[bytes, str]:
    """PDF-профиль самого кандидата: все его заполненные каналы. Профиль не заполнен — 409 `profile_incomplete`."""
    try:
        contacts = profile.own_contacts(db, candidate_id)
    except ApiException as exc:
        if exc.status == 404:
            raise support.api_error(409, "profile_incomplete") from None
        raise
    if not contacts.first_name or not contacts.last_name:
        raise support.api_error(409, "profile_incomplete")
    _throttle_pdf(db, candidate_id)
    subject = _own_subject(db, candidate_id, now)
    reveal = bool(subject and subject.person.privacy.reveal_fsp_details)
    model = _pdf_model(db, subject, contacts, now, audience="self", reveal_fsp=reveal)
    return profile.render_profile_pdf(model), model.file_name


def candidate_export(db: Session, employer_id: UUID, candidate_id: UUID, now: datetime) -> dict[str, Any]:
    """Данные кандидата для выгрузки раскрытой пары: карточка и раскрытые контакты; иначе 403 `not_disclosed`."""
    contacts = profile.contacts_for_pair(db, employer_id, candidate_id)
    if contacts is None or contacts.masked:
        raise support.api_error(403, "not_disclosed")
    card = employer_card(db, employer_id, candidate_id, now, record=False)
    return {
        "card": card.model_dump(mode="json"),
        "contacts": contacts.model_dump(mode="json", exclude={"masked", "candidate_id"}),
    }


# --------------------------------------------------------------------------------------------------------------------
# Объяснение для приглашения и оценка по запросу
# --------------------------------------------------------------------------------------------------------------------


def _employer_saw(subject: _Subject) -> list[str]:
    """Что было видно работодателю до согласия — готовые подписи для кандидата (Арх. 4.9)."""
    privacy, person = subject.person.privacy, subject.person
    seen = ["категория и уровень по тесту", "подтверждённые навыки", "формат работы"]
    if privacy.show_declared_stack and person.declared_skills:
        seen.append("заявленные навыки")
    if privacy.show_city and person.city:
        seen.append("город")
    if privacy.show_experience and (person.experience_years is not None or person.roles):
        seen.append("стаж и роли")
    if subject.live.fsp_visible(subject.candidate_id):
        seen.append("достижения ФСП (обобщённо)")
    return seen


def explain_for_invitation(
    db: Session, employer_id: UUID, candidate_id: UUID, need_id: UUID | None, snapshot_id: UUID | None, now: datetime
) -> InvitationExplain:
    """Проекция «Почему вас пригласили» и полоса совпадения на момент отправки (Арх. 4.9).

    По потребности — из сохранённой версии (названной или самой поздней с этим кандидатом), иначе расчёт на
    лету; без потребности (приглашение из банка) — до шести сильнейших подтверждённых навыков.
    """
    subject = _load_subject(db, employer_id, candidate_id, now)
    features = subject.features
    saw = _employer_saw(subject)
    scorer_version = subject.pool.scorer_version()
    own_category = support.category_ref(features.specialization_code, features.grade_code)
    if need_id is None:
        why = project_why_bank(features.evidence, own_category, saw, support.skill_title)
        return InvitationExplain(why=why, fit_band=None, scorer_version=scorer_version)

    need = needs.get_owned(db, employer_id, need_id)
    item: ShortlistItem | None = None
    if snapshot_id is not None:
        snapshot = snapshots.get_owned_snapshot(db, employer_id, snapshot_id)
        if snapshot.need_id != need.id:
            raise not_found()
        item = _stored_item(db, snapshot.id, candidate_id)
    if item is None:
        item = db.scalar(
            select(ShortlistItem)
            .join(ShortlistSnapshot, ShortlistSnapshot.id == ShortlistItem.snapshot_id)
            .where(ShortlistSnapshot.need_id == need.id, ShortlistItem.candidate_id == candidate_id)
            .order_by(ShortlistSnapshot.version_no.desc())
            .limit(1)
        )
    target = support.category_ref(need.specialization_code, need.grade_code)
    if item is not None:
        expl: MatchExplanation | None = read_explanation(db, subject.live, candidate_id, item.explanation)
    else:
        raw = _on_the_fly(subject, snapshots.current_query(db, need))
        expl = _rules(db, subject, raw) if raw is not None else None
    if expl is None:
        # Категория кандидата вне разделов потребности: объяснение — как из банка, но с целью потребности.
        why = project_why_bank(features.evidence, target, saw, support.skill_title)
        why = why.model_copy(update={"source": "need"})
        return InvitationExplain(why=why, fit_band=None, scorer_version=scorer_version)
    return InvitationExplain(
        why=project_why(expl, target, saw), fit_band=expl.fit_band, scorer_version=expl.scorer_version
    )


def score_for_query(
    db: Session, employer_id: UUID, query: ShortlistQuery, candidate_ids: Collection[UUID], now: datetime
) -> dict[UUID, ShortlistItemView]:
    """Оценить названных кандидатов по запросу без создания версии (отклики на вакансию).

    В ответе только видимые кандидаты, прошедшие фильтры-условия запроса; позиция — место среди названных.
    """
    ids = list(dict.fromkeys(candidate_ids))
    if not ids:
        return {}
    query = needs.canonical(query)
    grades = support.grade_codes()
    pool = load_pool(db, employer_id, now, candidate_ids=ids)
    sections = sections_for(query, grades)
    ranked = rank_need(
        query,
        [item for item in pool.visible() if first_failed_filter(item, query, sections) is None],
        shortlist_seed(employer_id, employer_id),
        grades=grades,
        closure=support.closure,
        section_limits={},
    )
    if not ranked.items:
        return {}
    shown = [row.candidate_id for row in ranked.items]
    disclosed = profile.disclosed_map(db, employer_id, shown)
    opened = [cid for cid in shown if disclosed.get(cid)]
    names = dict(profile.display_names(db, employer_id, opened)) if opened else {}
    result: dict[UUID, ShortlistItemView] = {}
    for row in ranked.items:
        scored, cid = row.scored, row.candidate_id
        features, person = scored.features, pool.profiles[row.candidate_id]
        expl = snapshots.explain(pool, query, scored)
        evidence, more = top_evidence(expl.requirements)
        result[cid] = ShortlistItemView(
            candidate_id=cid,
            public_code=person.public_code,
            display_name=names.get(cid),
            is_demo=person.is_demo,
            category=support.category_ref(features.specialization_code, features.grade_code),
            relation=scored.relation,
            grade_margin=features.verdict == TestOutcome.CONFIRMED_WITH_MARGIN,
            position=row.position,
            fit_band=scored.fit_band,
            strength_label=scored.strength.label,
            must_covered=scored.coverage.must_covered,
            must_total=scored.coverage.must_total,
            top_evidence=evidence,
            evidence_more=more,
            fsp_summary=pool.fsp_short(cid),
            formats_common=[WorkFormat(value) for value in expl.formats_common],
            freshness_days=features.age_days,
            stale=features.stale,
            risk=expl.risk.text if expl.risk else None,
            diff_mark=DiffMark.SAME,
            diff_delta=None,
            pinned=False,
            available=True,
            unavailable_reason=None,
        )
    return result
