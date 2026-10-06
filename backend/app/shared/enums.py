"""Все перечисления Арх. 8.2.

Значения хранятся в базе как `text` с ограничением `CHECK` (Арх. 8.1); ограничение строит
`app.core.db.enum_check`. Перечисления, помеченные «вычисляется», в базе не хранятся.
"""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    CANDIDATE = "candidate"
    EMPLOYER = "employer"


class ConsentKind(StrEnum):
    PROCESSING = "processing"
    PUBLICATION = "publication"
    FSP_DATA = "fsp_data"


class WorkFormat(StrEnum):
    OFFICE = "office"
    HYBRID = "hybrid"
    REMOTE = "remote"


class ContactKind(StrEnum):
    EMAIL = "email"
    PHONE = "phone"
    TELEGRAM = "telegram"
    OTHER = "other"


class TrustLevel(StrEnum):
    BASIC = "basic"
    VERIFIED = "verified"


class VisibilityState(StrEnum):
    """Вычисляется (Арх. 6.1)."""

    NOT_READY = "not_ready"
    UNPUBLISHED = "unpublished"
    PAUSED = "paused"
    VISIBLE = "visible"


class PauseReason(StrEnum):
    """Вычисляется."""

    MANUAL = "manual"
    AUTO_SILENCE = "auto_silence"


class DiscloseField(StrEnum):
    EMAIL = "email"
    PHONE = "phone"
    TELEGRAM = "telegram"
    LINK = "link"
    FSP_DETAILS = "fsp_details"


class DisclosureSource(StrEnum):
    INVITATION = "invitation"
    APPLICATION = "application"


class AccessKind(StrEnum):
    CONTACTS_DISCLOSED = "contacts_disclosed"
    CONTACTS_VIEWED = "contacts_viewed"
    PDF_DOWNLOADED = "pdf_downloaded"
    EXPORT_DOWNLOADED = "export_downloaded"


class EvidenceKind(StrEnum):
    """Вид доказательства факта о кандидате (Арх. 1.2, п. 2); вычисляется."""

    TEST = "test"
    PULSE = "pulse"
    FSP = "fsp"
    DECLARED = "declared"
    NONE = "none"


class SessionStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"
    EXPIRED = "expired"


class SessionKind(StrEnum):
    INITIAL = "initial"
    LOWER = "lower"
    HIGHER = "higher"
    RETAKE = "retake"


class TestOutcome(StrEnum):
    __test__ = False  # не тестовый класс для pytest

    NOT_CONFIRMED = "not_confirmed"
    BORDERLINE = "borderline"
    CONFIRMED = "confirmed"
    CONFIRMED_WITH_MARGIN = "confirmed_with_margin"


class ItemKind(StrEnum):
    NUMERIC_INPUT = "numeric_input"
    TEXT_INPUT = "text_input"
    SINGLE_CHOICE = "single_choice"
    MULTI_CHOICE = "multi_choice"
    PICK_LINE = "pick_line"
    ORDER_BLOCKS = "order_blocks"


class ItemStatus(StrEnum):
    PENDING = "pending"
    SHOWN = "shown"
    ANSWERED = "answered"
    SKIPPED = "skipped"
    UNREACHED = "unreached"
    NOT_SHOWN = "not_shown"


class SlotRole(StrEnum):
    MAIN = "main"
    STRETCH = "stretch"
    EXT = "ext"


class FamilyStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    SUSPECT = "suspect"
    QUARANTINED = "quarantined"
    RETIRED = "retired"


class VariantStatus(StrEnum):
    ACTIVE = "active"
    DEMO = "demo"
    RETIRED = "retired"


class SkillVerdict(StrEnum):
    CONFIRMED = "confirmed"
    PARTIAL = "partial"
    NOT_CONFIRMED = "not_confirmed"


class EvidenceSource(StrEnum):
    TEST = "test"
    PULSE = "pulse"


class GradeChangeKind(StrEnum):
    INITIAL = "initial"
    UP = "up"
    DOWN = "down"
    SPECIALIZATION_CHANGE = "specialization_change"


class ClaimSource(StrEnum):
    SURVEY = "survey"
    RESUME = "resume"
    MANUAL = "manual"


class PulseTaskStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class PulseAssignmentStatus(StrEnum):
    OFFERED = "offered"
    STARTED = "started"
    SUBMITTED = "submitted"
    SKIPPED = "skipped"
    EXPIRED = "expired"


class PulseSource(StrEnum):
    SHORTLIST = "shortlist"
    REFRESH = "refresh"


class NeedStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class Relation(StrEnum):
    EXACT = "exact"
    LOWER_WITH_MARGIN = "lower_with_margin"
    HIGHER = "higher"


class FitBand(StrEnum):
    STRONG = "strong"
    GOOD = "good"
    PARTIAL = "partial"


class DiffMark(StrEnum):
    NEW = "new"
    UP = "up"
    DOWN = "down"
    SAME = "same"


class ExposureSource(StrEnum):
    SHORTLIST = "shortlist"
    BANK = "bank"


class InvitationStatus(StrEnum):
    SENT = "sent"
    VIEWED = "viewed"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"
    WITHDRAWN = "withdrawn"
    BOUNCED = "bounced"


class DeclineReason(StrEnum):
    SALARY = "salary"
    STACK = "stack"
    FORMAT = "format"
    COMPANY = "company"
    NOT_LOOKING = "not_looking"
    OTHER = "other"


class ConditionKind(StrEnum):
    SALARY_FROM = "salary_from"
    WORK_FORMAT = "work_format"


class EventCode(StrEnum):
    SENT = "sent"
    BOUNCED = "bounced"
    VIEWED = "viewed"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"
    WITHDRAWN = "withdrawn"
    REVISED = "revised"
    CONTACT_MARKED = "contact_marked"
    CONTACT_CONFIRMED = "contact_confirmed"
    CONTACT_DENIED = "contact_denied"
    COMPLAINT_FILED = "complaint_filed"


class EventActor(StrEnum):
    EMPLOYER = "employer"
    CANDIDATE = "candidate"
    SYSTEM = "system"


class ComplaintReason(StrEnum):
    FAKE_OFFER = "fake_offer"
    TERMS_MISMATCH = "terms_mismatch"
    SPAM = "spam"
    RUDE = "rude"
    OTHER = "other"


class ComplaintStatus(StrEnum):
    OPEN = "open"
    UPHELD = "upheld"
    DISMISSED = "dismissed"


class VacancyStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    CLOSED = "closed"


class ApplicationStatus(StrEnum):
    SENT = "sent"
    VIEWED = "viewed"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"
    WITHDRAWN = "withdrawn"


class ApplicationDeclineReason(StrEnum):
    STACK = "stack"
    GRADE = "grade"
    CLOSED = "closed"
    OTHER = "other"


class LinkAttemptOutcome(StrEnum):
    LINKED = "linked"
    CANCELLED = "cancelled"
    CONFLICT = "conflict"
    MINOR = "minor"
    AUTH_ERROR = "auth_error"
    UNAVAILABLE = "unavailable"
    EXPIRED = "expired"
    USER_MISMATCH = "user_mismatch"
    SUPERSEDED = "superseded"


class SyncTrigger(StrEnum):
    LINK = "link"
    MANUAL = "manual"
    STALE = "stale"
    CLI = "cli"
    SEED = "seed"


class SyncOutcome(StrEnum):
    OK_CHANGED = "ok_changed"
    OK_UNCHANGED = "ok_unchanged"
    IN_PROGRESS = "in_progress"
    FAILED_UNAVAILABLE = "failed_unavailable"
    FAILED_CONTRACT = "failed_contract"
    FAILED_AUTH = "failed_auth"
    FAILED_TIMEOUT = "failed_timeout"
    UNLINKED_REVOKED = "unlinked_revoked"
    UNLINKED_MINOR = "unlinked_minor"


class CredentialKind(StrEnum):
    """В MVP — только разряд; остальные виды — вторая фаза."""

    RANK = "rank"


class DemoPersona(StrEnum):
    RESPONSIVE = "responsive"
    SELECTIVE = "selective"
    EXPENSIVE = "expensive"
    SILENT = "silent"
