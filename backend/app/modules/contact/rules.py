"""Чистые правила механики контакта «Приглашение с возвратом» (Арх. 4).

Файл не импортирует SQLAlchemy и ничего не читает из базы: рабочий сервис, проекции и симуляция
`app/eval/contact` вызывают один и тот же код (Арх. 2.4, п. 6). Функции принимают «факты» о приглашении — любой
объект с нужными полями (`InvitationFacts`): строку ORM, запись симуляции или снимок из запроса.

Чего здесь нет намеренно: порядка блокировок и записи в базу (это `settle.py` и `service.py`).

Единственное место платформы, где вилка сравнивается со скрытым минимумом кандидата, — `salary_ok`.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID

from app.modules.contact import constants as c
from app.shared.enums import (
    ConditionKind,
    DeclineReason,
    DemoPersona,
    DiscloseField,
    FitBand,
    InvitationStatus,
    TrustLevel,
    WorkFormat,
)
from app.shared.salary import SALARY_MAX

#: Статусы, в которых приглашение ждёт ответа кандидата; все остальные — терминальные (Арх. 4.2).
ACTIVE_STATUSES: frozenset[str] = frozenset({InvitationStatus.SENT.value, InvitationStatus.VIEWED.value})
#: Каналы связи: в наборе раскрытия должен быть хотя бы один из них (Арх. 4.8).
CHANNEL_FIELDS: tuple[DiscloseField, ...] = (
    DiscloseField.EMAIL,
    DiscloseField.PHONE,
    DiscloseField.TELEGRAM,
    DiscloseField.LINK,
)

PairBlockCode = Literal["conditions_mismatch", "pair_cooldown"]
FunnelStage = Literal["hidden", "ok", "blocked_by_min", "not_shown", "not_opened", "not_invited"]


class InvitationFacts(Protocol):
    """Поля приглашения, которые читают правила. Подходит и строка `Invitation`, и запись симуляции."""

    @property
    def status(self) -> str: ...  # noqa: D102
    @property
    def created_at(self) -> datetime: ...  # noqa: D102
    @property
    def expires_at(self) -> datetime: ...  # noqa: D102
    @property
    def resolved_at(self) -> datetime | None: ...  # noqa: D102
    @property
    def slot_release_at(self) -> datetime | None: ...  # noqa: D102
    @property
    def pair_block_until(self) -> datetime | None: ...  # noqa: D102


class RevisableFacts(InvitationFacts, Protocol):
    """Поля исходного приглашения, нужные правилам пересмотра (Арх. 4.8)."""

    @property
    def employer_id(self) -> UUID: ...  # noqa: D102
    @property
    def candidate_id(self) -> UUID: ...  # noqa: D102
    @property
    def revises_id(self) -> UUID | None: ...  # noqa: D102
    @property
    def decline_condition_kind(self) -> str | None: ...  # noqa: D102
    @property
    def decline_condition_salary_from(self) -> int | None: ...  # noqa: D102
    @property
    def decline_condition_work_format(self) -> str | None: ...  # noqa: D102


@dataclass(frozen=True, slots=True)
class PairBlock:
    """Блокировка пары: код для работодателя и момент, с которого возможна новая попытка."""

    code: PairBlockCode
    until: datetime


@dataclass(frozen=True, slots=True)
class DemoDecision:
    """Решение демо-ответчика по приглашению: принять либо отклонить с причиной и, возможно, условием."""

    action: Literal["accept", "decline"]
    reason: DeclineReason | None = None
    condition_salary_from: int | None = None


# --------------------------------------------------------------------------------------------------------------------
# Сверка вилки (Арх. 4.6)
# --------------------------------------------------------------------------------------------------------------------


def salary_ok(salary_from: int, min_salary: int | None) -> bool:
    """Сверка вилки со скрытым минимумом кандидата — единственное место сравнения (Арх. 4.6).

    Правило: `min_salary is None or salary_from >= min_salary`. Сравнивается нижняя граница вилки, и сверка
    действует всегда: счётчика, после которого она отключалась бы, нет. Вызывается один раз — последним шагом
    транзакции отправки (Арх. 4.5, шаг 6) — и при чтении приглашения самим кандидатом для метки «ниже вашего
    минимума». Ни подборка, ни банк, ни предпроверка эту функцию не вызывают (инвариант I8).
    """
    return min_salary is None or salary_from >= min_salary


def skips_salary_check(*, demo_call: bool, employer_is_demo: bool, candidate_is_demo: bool) -> bool:
    """Сверка не выполняется только для демо-приглашения (Арх. 4.5, шаг 6; 4.14).

    Демо-приглашение — отправка модулем `demo` (`is_demo=True`) пары «демо-компания → не демо-аккаунт»: оно
    доставляется всегда, а кандидат видит метку «ниже вашего минимума». Приглашения сида между демо-аккаунтами
    сверку проходят (так получается `bounced` у `dmitry`), как и любые приглашения настоящих работодателей.
    """
    return demo_call and employer_is_demo and not candidate_is_demo


def demo_sender_restricted(*, demo_call: bool, employer_is_demo: bool, candidate_is_demo: bool) -> bool:
    """Проверка 5.11 (Арх. 4.5): демо-компания не приглашает настоящих пользователей вручную.

    Истинно, когда отправитель — демо-аккаунт, адресат — нет, а вызов пришёл из роутера (`demo_call = False`).
    Параметр `is_demo=True` передают только сид и модуль `demo`. Решает признак аккаунта `app_user.is_demo`,
    а не чип показа профиля.
    """
    return employer_is_demo and not candidate_is_demo and not demo_call


def is_masked_pair(*, employer_is_demo: bool, candidate_is_demo: bool) -> bool:
    """Маскируемая пара (Арх. 4.14, 10.4): работодатель — демо-аккаунт, кандидат — нет.

    Такой паре не передаются данные живого человека: ни ФИО и каналы (это делает `profile`), ни условие
    и комментарий отказа (проекция работодателя и сводка причин, поправка R3-mechanics-recheck-1).
    """
    return employer_is_demo and not candidate_is_demo


def counts_for_candidate(*, invitation_is_demo: bool, candidate_is_demo: bool) -> bool:
    """Учитывается ли приглашение в воронке и счётчике молчания кандидата (Арх. 4.10, 4.12).

    Демо-приглашение живому кандидату (`is_demo` у приглашения, аккаунт кандидата не демо) не считается:
    оно не даёт «страйк» автопаузы при истечении и не превращает воронку в стадию `ok` — человек его не просил
    (поправки R3-mechanics-recheck-4 и R3-data-api-security-11). У демо-аккаунтов сценария учитывается всё.
    """
    return not (invitation_is_demo and not candidate_is_demo)


# --------------------------------------------------------------------------------------------------------------------
# Статус, слоты, пара (Арх. 4.4, 4.7)
# --------------------------------------------------------------------------------------------------------------------


def is_active(status: str) -> bool:
    """Ждёт ли приглашение ответа по записанному статусу: `sent` или `viewed` (Арх. 4.2)."""
    return status in ACTIVE_STATUSES


def effective_status(inv: InvitationFacts, now: datetime) -> InvitationStatus:
    """Статус для чтения (Арх. 4.4): `expired` для `sent` и `viewed` с `expires_at <= now`, иначе записанный.

    Читающие эндпоинты не вызывают `settle` и ничего не материализуют; истёкшее, но ещё не закрытое приглашение
    они показывают как `expired`. Запись статуса выполняет только `settle()`.
    """
    if inv.status in ACTIVE_STATUSES and inv.expires_at <= now:
        return InvitationStatus.EXPIRED
    return InvitationStatus(inv.status)


def effective_resolved_at(inv: InvitationFacts, now: datetime) -> datetime | None:
    """Момент закрытия для чтения: у истёкшего, но не материализованного приглашения — `expires_at` (переход T6)."""
    if inv.status in ACTIVE_STATUSES:
        return inv.expires_at if inv.expires_at <= now else None
    return inv.resolved_at


def effective_pair_block_until(inv: InvitationFacts, now: datetime) -> datetime | None:
    """Конец блокировки пары для чтения: у истёкшего, но не материализованного — `expires_at + PAIR_RETRY_DAYS`."""
    if inv.status in ACTIVE_STATUSES:
        return inv.expires_at + c.PAIR_RETRY if inv.expires_at <= now else None
    return inv.pair_block_until


def slot_occupied(inv: InvitationFacts, now: datetime) -> bool:
    """Занимает ли приглашение слот работодателя (Арх. 4.7).

    `sent` и `viewed` держат слот до `expires_at` — истёкшее, но ещё не материализованное слот не держит;
    остальные статусы — пока `now < slot_release_at`: принятое и отклонённое освобождают слот сразу, истёкшее —
    в момент срока, отозванное — в исходный срок (отзыв не ускоряет оборот слотов), недоставленное — через
    `BOUNCE_SLOT_HOLD_HOURS` после попытки.
    """
    if inv.status in ACTIVE_STATUSES:
        return now < inv.expires_at
    return inv.slot_release_at is not None and now < inv.slot_release_at


def slot_release_at(inv: InvitationFacts, now: datetime) -> datetime | None:
    """Когда приглашение освободит (или освободило) слот: `expires_at` для ждущих ответа, иначе `slot_release_at`."""
    if inv.status in ACTIVE_STATUSES:
        return inv.expires_at
    return inv.slot_release_at


def slot_limit(override: int | None, trust_level: TrustLevel | str | None) -> int:
    """Лимит слотов работодателя (Арх. 4.7): `slot_limit_override or SLOT_LIMIT[company.trust_level]`.

    Без профиля компании действует базовый уровень доверия.
    """
    if override:
        return override
    level = TrustLevel(trust_level) if trust_level is not None else TrustLevel.BASIC
    return c.SLOT_LIMIT[level]


def slots_used(invitations: Iterable[InvitationFacts], now: datetime) -> tuple[int, datetime | None]:
    """Занятые слоты и ближайшее освобождение (Арх. 4.7).

    `used` — число приглашений работодателя, для которых `slot_occupied`; `next_release_at` — минимум
    `expires_at` у ждущих ответа и `slot_release_at` у остальных занятых; `None`, если занятых нет.
    """
    used = 0
    next_release: datetime | None = None
    for inv in invitations:
        if not slot_occupied(inv, now):
            continue
        used += 1
        release = slot_release_at(inv, now)
        if release is not None and (next_release is None or release < next_release):
            next_release = release
    return used, next_release


def pair_block(invitations_of_pair: Sequence[InvitationFacts], now: datetime) -> PairBlock | None:
    """Блокировка пары «работодатель — кандидат» (Арх. 4.7).

    `until = max(pair_block_until)` по приглашениям пары; если `until > now`, пара закрыта: код
    `conditions_mismatch`, когда последнее по `created_at` приглашение — `bounced`, иначе `pair_cooldown`.
    Активное приглашение блокировку не даёт — его ловит отдельная проверка 5.6 (`active_invitation_exists`).
    Истёкшее, но не материализованное приглашение блокирует пару так же, как закрытое (`effective_*`).
    """
    until: datetime | None = None
    last: InvitationFacts | None = None
    for inv in invitations_of_pair:
        block = effective_pair_block_until(inv, now)
        if block is not None and (until is None or block > until):
            until = block
        if last is None or inv.created_at > last.created_at:
            last = inv
    if until is None or until <= now or last is None:
        return None
    bounced = effective_status(last, now) is InvitationStatus.BOUNCED
    return PairBlock(code="conditions_mismatch" if bounced else "pair_cooldown", until=until)


def daily_retry_after(created_in_window: Sequence[datetime], now: datetime, limit: int | None = None) -> int | None:
    """Суточный лимит отправок (Арх. 4.5, проверка 5.8; 4.7).

    `created_in_window` — моменты попыток работодателя за последние 24 часа, включая `bounced`. Если их не меньше
    `DAILY_SEND_LIMIT`, возвращается число секунд до момента, когда самая старая из последних `limit` попыток
    выйдет из окна (`params.retry_after`); иначе `None`. К демо-аккаунтам проверка не применяется — это решает
    вызывающий код (Арх. 4.14).
    """
    limit = c.DAILY_SEND_LIMIT if limit is None else limit
    recent = sorted(at for at in created_in_window if at > now - c.DAILY_WINDOW)
    if len(recent) < limit:
        return None
    # Новая попытка станет возможна, когда в окне останется limit - 1 попыток: выйти должна recent[-limit].
    oldest_blocking = recent[len(recent) - limit]
    return max(1, int((oldest_blocking + c.DAILY_WINDOW - now).total_seconds()) + 1)


# --------------------------------------------------------------------------------------------------------------------
# Пересмотренное приглашение (Арх. 4.8)
# --------------------------------------------------------------------------------------------------------------------


def same_pair(original: RevisableFacts, employer_id: UUID, candidate_id: UUID) -> bool:
    """Пересмотр относится к той же паре, что и исходное приглашение (Арх. 4.5, проверка 5.5).

    Исходное приглашение обязано принадлежать этому же работодателю и быть адресовано этому же кандидату. Без
    этой проверки отказ или недоставка по одному кандидату давали бы «пропуск» мимо блокировки пары к любому
    другому, а чужой `revises_id` раскрывал бы чужое условие (поправка R3-data-api-security-1; инвариант I9).
    """
    return original.employer_id == employer_id and original.candidate_id == candidate_id


def can_revise(original: RevisableFacts, now: datetime, *, has_revision: bool) -> bool:
    """Доступно ли работодателю одно пересмотренное приглашение (Арх. 4.8, переход T8).

    Истинно, когда исходное — `declined` с условием кандидата либо `bounced`, само не является пересмотренным
    (`revises_id is None`), пересмотр по нему ещё не отправлялся (`has_revision = False`) и не прошло
    `REVISION_WINDOW_DAYS` с момента закрытия. Отсюда инвариант I7: у приглашения не больше одного
    пересмотренного, а пересмотренное пересмотреть нельзя.
    """
    if original.revises_id is not None or has_revision or original.resolved_at is None:
        return False
    if original.status == InvitationStatus.DECLINED.value:
        if original.decline_condition_kind is None:
            return False
    elif original.status != InvitationStatus.BOUNCED.value:
        return False
    return now < original.resolved_at + c.REVISION_WINDOW


def revise_until(original: RevisableFacts) -> datetime | None:
    """До какого момента возможен пересмотр: `resolved_at + REVISION_WINDOW_DAYS` (Арх. 4.8)."""
    return None if original.resolved_at is None else original.resolved_at + c.REVISION_WINDOW


def revision_terms_ok(
    original: RevisableFacts, original_salary_from: int, *, salary_from: int, work_format: WorkFormat | str
) -> bool:
    """Условия пересмотренного приглашения не хуже требуемых (Арх. 4.8; иначе 422 `revision_below_condition`).

    После отказа с условием: `salary_from >= исходного`; при условии `salary_from` — `salary_from >= value`;
    при условии `work_format` — формат равен `value`. После `bounced`: `salary_from` строго больше исходной —
    работодатель исправляет вилку, не зная минимума.
    """
    if original.status == InvitationStatus.BOUNCED.value:
        return salary_from > original_salary_from
    if salary_from < original_salary_from:
        return False
    if original.decline_condition_kind == ConditionKind.SALARY_FROM.value:
        required = original.decline_condition_salary_from
        return required is not None and salary_from >= required
    if original.decline_condition_kind == ConditionKind.WORK_FORMAT.value:
        return str(work_format) == original.decline_condition_work_format
    return True


# --------------------------------------------------------------------------------------------------------------------
# Ответ кандидата (Арх. 4.8)
# --------------------------------------------------------------------------------------------------------------------


def decline_condition_ok(
    reason: DeclineReason | str,
    kind: ConditionKind | str,
    value: int | str,
    *,
    offer_salary_from: int,
    offer_work_format: WorkFormat | str,
    candidate_formats: Collection[str],
) -> bool:
    """Допустимо ли условие отказа (Арх. 4.8; иначе 422 `condition_invalid`).

    `{kind: salary_from, value}` — только при причине `salary`: `value` кратно `DECLINE_SALARY_STEP`, больше
    `salary_from` приглашения и не больше `SALARY_MAX`. `{kind: work_format, value}` — только при причине
    `format`: `value` входит в форматы кандидата и не равен предложенному. Названная сумма скрытый минимум
    не раскрывает: кандидат называет её сам.
    """
    reason, kind = str(reason), str(kind)
    if kind == ConditionKind.SALARY_FROM.value:
        if reason != DeclineReason.SALARY.value or isinstance(value, bool) or not isinstance(value, int):
            return False
        return value % c.DECLINE_SALARY_STEP == 0 and offer_salary_from < value <= SALARY_MAX
    if kind == ConditionKind.WORK_FORMAT.value:
        if reason != DeclineReason.FORMAT.value or not isinstance(value, str):
            return False
        return value in {str(item) for item in candidate_formats} and value != str(offer_work_format)
    return False


def default_disclose(
    *, reveal_phone: bool, reveal_telegram: bool, reveal_link: bool, reveal_fsp_details: bool, filled: Collection[str]
) -> list[DiscloseField]:
    """Набор раскрытия по умолчанию — когда кандидат не выбрал его явно (Арх. 4.8).

    E-mail включён всегда; телефон, Telegram и ссылка — по настройкам приватности `reveal_*` и только если канал
    заполнен в профиле; `fsp_details` — по `reveal_fsp_details`. Те же значения отдаются как `default`
    в `disclose_options` диалога принятия.
    """
    fields = [DiscloseField.EMAIL]
    for field, enabled in (
        (DiscloseField.PHONE, reveal_phone),
        (DiscloseField.TELEGRAM, reveal_telegram),
        (DiscloseField.LINK, reveal_link),
    ):
        if enabled and field.value in filled:
            fields.append(field)
    if reveal_fsp_details:
        fields.append(DiscloseField.FSP_DETAILS)
    return fields


def disclose_ok(fields: Collection[DiscloseField | str], filled: Collection[str]) -> bool:
    """Допустим ли набор раскрытия при принятии (Арх. 4.8; иначе 422 `disclose_invalid`).

    В наборе должен быть хотя бы один канал из `email`, `phone`, `telegram`, `link`, и каждый выбранный канал
    заполнен в профиле (`profile.filled_channels`). Имя и фамилия раскрываются всегда и в набор не входят.
    """
    chosen = {str(field) for field in fields}
    channels = chosen & {field.value for field in CHANNEL_FIELDS}
    return bool(channels) and channels <= {str(item) for item in filled}


# --------------------------------------------------------------------------------------------------------------------
# Молчание, воронка, показатели (Арх. 4.10, 4.12, 4.13)
# --------------------------------------------------------------------------------------------------------------------


def strike_triggers_pause(consecutive_expired: int) -> bool:
    """Пора ли ставить автопаузу: истечений подряд не меньше `SILENCE_STRIKES` (Арх. 4.10, переход T6)."""
    return consecutive_expired >= c.SILENCE_STRIKES


def strikes_after_auto_resume() -> int:
    """Счётчик молчания после автоматического снятия автопаузы: `SILENCE_STRIKES - 1` (Арх. 4.4, 4.10).

    Пауза закончилась по сроку, а кандидат так и не ответил: остаётся один «страйк», и следующее истечение без
    ответа ставит паузу снова. Кнопка «Я на связи» обнуляет счётчик полностью.
    """
    return max(0, c.SILENCE_STRIKES - 1)


def funnel_stage(*, visible: bool, shown: int, opened: int, delivered: int, not_delivered: int) -> FunnelStage:
    """Стадия воронки кандидата — она определяет текст и одно действие (Арх. 4.12).

    Порядок проверок: профиль не виден → `hidden`; есть доставленные → `ok`; есть недоставленные →
    `blocked_by_min`; не показывался → `not_shown`; карточку не открывали → `not_opened`; иначе `not_invited`.
    """
    if not visible:
        return "hidden"
    if delivered >= 1:
        return "ok"
    if not_delivered >= 1:
        return "blocked_by_min"
    if shown == 0:
        return "not_shown"
    if opened == 0:
        return "not_opened"
    return "not_invited"


def is_new_for_employer(employer_seen_at: datetime | None, last_foreign_event_at: datetime | None) -> bool:
    """Признак «новое» в списке работодателя (приложение C, §5.3).

    Истинно, если после последнего открытия работодателем (`employer_seen_at`) случилось событие, автор которого
    не он: просмотр, ответ кандидата, истечение срока. Собственные действия работодателя и результат отправки
    (`sent`, `bounced` — он видит его сразу в ответе) новыми не считаются.
    """
    if last_foreign_event_at is None:
        return False
    return employer_seen_at is None or employer_seen_at < last_foreign_event_at


def outcome_prompt(status: str, resolved_at: datetime | None, answered: bool, now: datetime) -> bool:
    """Подсветить ли стороне вопрос об исходе контакта (P1, Арх. 4.13).

    Истинно для принятого приглашения, когда срок выхода на связь `resolved_at + CONTACT_SLA_HOURS` прошёл,
    а сторона ещё не ответила. Признак только подсвечивает карточку: ответить можно и раньше.
    """
    if status != InvitationStatus.ACCEPTED.value or resolved_at is None or answered:
        return False
    return now >= resolved_at + c.CONTACT_SLA


def freeze_due(distinct_candidates: int) -> bool:
    """Достигнут ли порог заморозки отправки (P1, Арх. 4.13).

    `distinct_candidates` — число разных кандидатов, которые за `COMPLAINT_WINDOW_DAYS` пожаловались на
    работодателя (кроме жалоб со статусом `dismissed`) либо ответили «условия не совпали» — этот ответ приравнен
    к жалобе `terms_mismatch`. Порог — `COMPLAINT_FREEZE_THRESHOLD`.
    """
    return distinct_candidates >= c.COMPLAINT_FREEZE_THRESHOLD


def median_int(values: Sequence[int]) -> int | None:
    """Медиана целых сумм, округлённая до целого рубля; пустой набор — `None` (Арх. 4.11, медиана вилок)."""
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle] + 1) // 2


def salary_hint(offers: Sequence[tuple[UUID, int, int]]) -> tuple[int, int] | None:
    """Медиана вилок категории — «ориентир рынка» (Арх. 4.11).

    `offers` — принятые приглашения категории за `SALARY_HINT_WINDOW_DAYS`: (работодатель, `salary_from`,
    `salary_to`). Возвращаются медианы «от» и «до», если приглашений не меньше `SALARY_HINT_MIN_N` и они от не
    менее чем `SALARY_HINT_MIN_EMPLOYERS` работодателей; иначе `None`. Это сведения о предложениях, а не
    о минимумах кандидатов: минимум в расчёте не участвует.
    """
    if len(offers) < c.SALARY_HINT_MIN_N or len({employer for employer, _, _ in offers}) < c.SALARY_HINT_MIN_EMPLOYERS:
        return None
    low = median_int([salary_from for _, salary_from, _ in offers])
    high = median_int([salary_to for _, _, salary_to in offers])
    if low is None or high is None:
        return None
    return low, max(low, high)


def share(part: int, whole: int) -> float | None:
    """Доля `part / whole`, округлённая до четырёх знаков; при пустом знаменателе — `None` (показатели 4.12)."""
    return None if whole <= 0 else round(part / whole, 4)


def gini(values: Sequence[int | float]) -> float | None:
    """Коэффициент Джини — концентрация доставленных приглашений по кандидатам (Арх. 4.12).

    `G = Σ_i (2i − n − 1) · x_i / (n · Σ x)` по значениям, упорядоченным по возрастанию (`i` с единицы).
    0 — приглашения распределены поровну, значение у единицы — всё досталось одному. Пустой набор либо
    нулевая сумма — `None`.
    """
    ordered = sorted(float(value) for value in values)
    n = len(ordered)
    total = sum(ordered)
    if n == 0 or total <= 0:
        return None
    weighted = sum((2 * index - n - 1) * value for index, value in enumerate(ordered, start=1))
    return round(weighted / (n * total), 4)


# --------------------------------------------------------------------------------------------------------------------
# Демо-ответчик (Арх. 4.14)
# --------------------------------------------------------------------------------------------------------------------


def demo_timing(persona: DemoPersona | str | None) -> tuple[timedelta, timedelta] | None:
    """Через сколько после `created_at` персона просматривает приглашение и отвечает на него (Арх. 4.14).

    `responsive` — 20 с и 60 с; `selective` — 40 с и 90 с; `expensive` — 30 с и 75 с; `silent` и кандидат без
    персоны не отвечают (`None`). Время идёт по часам сервиса; ответчик работает только в фоновом цикле.
    """
    if persona is None:
        return None
    try:
        key = DemoPersona(persona)
    except ValueError:
        return None
    timing = c.DEMO_TIMING_S.get(key)
    if timing is None:
        return None
    return timedelta(seconds=timing[0]), timedelta(seconds=timing[1])


def expensive_condition(salary_from: int) -> int | None:
    """Условие персоны `expensive`: `ceil(salary_from × 1,15)` с округлением вверх до 20 000 (Арх. 4.14).

    Считается в целых числах. `None`, если сумма вышла бы за `SALARY_MAX`: тогда персона отклоняет без условия.
    """
    raised = -(-salary_from * c.DEMO_EXPENSIVE_FACTOR_PCT // 100)
    value = -(-raised // c.DEMO_EXPENSIVE_ROUND_TO) * c.DEMO_EXPENSIVE_ROUND_TO
    if value <= salary_from:
        value += c.DEMO_EXPENSIVE_ROUND_TO
    return value if value <= SALARY_MAX else None


def demo_decision(
    persona: DemoPersona | str,
    *,
    salary_from: int,
    fit_band: FitBand | str | None,
    revision_meets_condition: bool = False,
) -> DemoDecision | None:
    """Что отвечает демо-персона (Арх. 4.14); та же модель персон используется в `make eval-contact`.

    `responsive` принимает. `selective` принимает при `fit_band_at_send = strong` или без объяснения, иначе
    отклоняет с причиной `stack`. `expensive` отклоняет с причиной `salary` и условием `expensive_condition`,
    а пересмотренное приглашение, выполняющее названное условие, принимает. `silent` не отвечает (`None`).
    """
    try:
        key = DemoPersona(persona)
    except ValueError:
        return None
    if key is DemoPersona.RESPONSIVE:
        return DemoDecision(action="accept")
    if key is DemoPersona.SELECTIVE:
        if fit_band is None or str(fit_band) == FitBand.STRONG.value:
            return DemoDecision(action="accept")
        return DemoDecision(action="decline", reason=DeclineReason.STACK)
    if key is DemoPersona.EXPENSIVE:
        if revision_meets_condition:
            return DemoDecision(action="accept")
        return DemoDecision(
            action="decline", reason=DeclineReason.SALARY, condition_salary_from=expensive_condition(salary_from)
        )
    return None
