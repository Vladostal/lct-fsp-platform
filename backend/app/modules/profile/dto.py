"""Типы фасада `profile.service` (Арх. 2.5, 6.1, 6.14, 9.11, 10.4).

Всё, что стоит в сигнатурах фасада, объявлено здесь; другие модули импортируют только этот файл и `service.py`.
Входные типы функций записи (`ProfileData`, `ConditionsData`, `PrivacyData`) сами проверяют формат полей: роутер
строит их из запроса, сид — напрямую, правила одни.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_core import PydanticCustomError

from app.modules.assessment.dto import LevelView
from app.modules.profile import validation
from app.modules.profile.constants import (
    ABOUT_MAX,
    DECLARED_SKILLS_MAX,
    DECLARED_SOFT_SKILLS_MAX,
    HIDDEN_DOMAINS_MAX,
    ROLES_MAX,
)
from app.shared.enums import DiscloseField, PauseReason, VisibilityState, WorkFormat
from app.shared.schemas import CategoryRef, EvidenceItem
from app.shared.text import fmt_date

# --- состояние показа и приватность ----------------------------------------------------------------------------------


class VisibilityDTO(BaseModel):
    """Состояние показа кандидата работодателям (вычисляется, Арх. 6.1).

    `pause_reason` заполнен только в состоянии `paused`; `auto_paused_until` — только пока автопауза действует
    (после срока она перестаёт действовать без записи в базу).
    """

    state: VisibilityState
    pause_reason: PauseReason | None = None
    auto_paused_until: datetime | None = None


class PrivacySettingsDTO(BaseModel):
    """Настройки приватности кандидата (Арх. 8.4, 10.4; приложение E, §10.2).

    `reveal_*` по умолчанию выключены (поправка рецензии R3-data-api-security-6): без явного выбора кандидата
    раскрывается только e-mail.
    """

    show_city: bool = True
    show_experience: bool = True
    show_declared_stack: bool = True
    #: «О себе» показывается только раскрытой паре; настройка может скрыть его и от неё.
    show_about: bool = True
    show_fsp_summary: bool = True
    reveal_phone: bool = False
    reveal_telegram: bool = False
    reveal_link: bool = False
    reveal_fsp_details: bool = False
    #: P1: домены почты компаний, которым профиль не показывается.
    hidden_domains: Annotated[list[str], Field(max_length=HIDDEN_DOMAINS_MAX)] = []

    @field_validator("hidden_domains")
    @classmethod
    def _domains(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(validation.mail_domain(item) for item in value))


class PrivacyData(PrivacySettingsDTO):
    """Входные данные `save_privacy`: полная замена настроек.

    Если `hidden_domains` не передан (поля нет в `model_fields_set`), сохранённый список не меняется: экран P0
    этого поля не знает.
    """


# --- профиль ---------------------------------------------------------------------------------------------------------


class DeclaredSkill(BaseModel):
    """Заявленный навык: код справочника либо свой тег (`custom_label`) — ровно одно из двух."""

    code: Annotated[str | None, Field(max_length=64)] = None
    custom_label: str | None = None

    @model_validator(mode="after")
    def _one_of(self) -> DeclaredSkill:
        if (self.code is None) == (self.custom_label is None):
            raise PydanticCustomError("skill_one_of", "Укажите либо код навыка, либо свой тег")
        if self.custom_label is not None:
            self.custom_label = validation.custom_label(self.custom_label)
        return self


class ProfileData(BaseModel):
    """Входные данные `save_profile` — полная замена редактируемых полей, включая заявленные навыки
    (приложение B, §8.2, `CandidateProfileUpdate`).

    Формат полей проверяется здесь; существование кодов ролей и навыков и пределы 30 и 10 — в сервисе (нужен
    справочник). `resume_upload_id` связывает сохранение с загрузкой резюме: её результат после сохранения
    обнуляется, а подсказки грейда и специализации переносятся в профиль.
    """

    last_name: str
    first_name: str
    middle_name: str | None = None
    city: str | None = None
    phone: str | None = None
    telegram: str | None = None
    link: str | None = None
    experience_years: float | None = None
    roles: Annotated[list[Annotated[str, Field(max_length=64)]], Field(max_length=ROLES_MAX)] = []
    about: Annotated[str | None, Field(max_length=ABOUT_MAX * 2)] = None
    declared_skills: Annotated[
        list[DeclaredSkill], Field(max_length=DECLARED_SKILLS_MAX + DECLARED_SOFT_SKILLS_MAX)
    ] = []
    resume_upload_id: UUID | None = None
    resume_accepted_fields: Annotated[list[Annotated[str, Field(max_length=40)]], Field(max_length=32)] = []

    @field_validator("last_name", "first_name")
    @classmethod
    def _required_name(cls, value: str) -> str:
        result = validation.person_name(value, required=True)
        assert result is not None
        return result

    @field_validator("middle_name")
    @classmethod
    def _middle_name(cls, value: str | None) -> str | None:
        return None if value is None else validation.person_name(value, required=False)

    @field_validator("city")
    @classmethod
    def _city(cls, value: str | None) -> str | None:
        return validation.city(value)

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str | None) -> str | None:
        return validation.phone(value)

    @field_validator("telegram")
    @classmethod
    def _telegram(cls, value: str | None) -> str | None:
        return validation.telegram(value)

    @field_validator("link")
    @classmethod
    def _link(cls, value: str | None) -> str | None:
        return validation.link(value)

    @field_validator("experience_years")
    @classmethod
    def _experience(cls, value: float | None) -> float | None:
        return validation.experience_years(value)

    @field_validator("about")
    @classmethod
    def _about(cls, value: str | None) -> str | None:
        return validation.about(value)

    @field_validator("roles")
    @classmethod
    def _roles(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))

    @field_validator("declared_skills")
    @classmethod
    def _skills(cls, value: list[DeclaredSkill]) -> list[DeclaredSkill]:
        """Повторы (код либо тег без учёта регистра) отбрасываются: остаётся первое вхождение."""
        seen: set[tuple[str, str]] = set()
        unique: list[DeclaredSkill] = []
        for item in value:
            key = ("code", item.code) if item.code is not None else ("label", (item.custom_label or "").lower())
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return unique


class ConditionsData(BaseModel):
    """Входные данные `save_conditions`. `min_salary` — ступень лестницы либо `None` («не задан»).

    Принадлежность лестнице проверяет сервис (422 `min_salary_not_on_ladder`).
    """

    min_salary: int | None = None
    work_formats: Annotated[list[WorkFormat], Field(min_length=1)]
    relocation_ready: bool = False

    @field_validator("work_formats")
    @classmethod
    def _formats(cls, value: list[WorkFormat]) -> list[WorkFormat]:
        chosen = set(value)
        return [item for item in WorkFormat if item in chosen]


class PoolProfile(BaseModel):
    """Профиль кандидата для подбора (Арх. 6.1): только то, что можно показывать до раскрытия.

    Город, стаж, роли и заявленные навыки уже отфильтрованы настройками приватности: скрытое настройкой не только
    не показывается, но и не используется в подборе (Арх. 10.4). `custom_skills` — свободный текст кандидата:
    в ответы работодателю он попадает только у раскрытой пары (`is_disclosed`), до раскрытия — никогда.

    `is_demo` — ТОЛЬКО чип показа (аккаунт демо либо категория получена быстрым демо-тестом); решения
    о маскировании и отправке читают признак аккаунта `identity.users(...).is_demo`.
    """

    public_code: str
    visible: bool
    visibility: VisibilityDTO
    privacy: PrivacySettingsDTO
    work_formats: list[WorkFormat] = []
    relocation_ready: bool = False
    declared_skills: list[str] = []
    custom_skills: list[str] = []
    city: str | None = None
    experience_years: float | None = None
    roles: list[str] = []
    is_demo: bool = False


class ContactsDTO(BaseModel):
    """Сведения раскрытой пары: ФИО, «О себе», свои теги и только каналы, выбранные кандидатом (Арх. 10.4).

    `masked = True` — пара «демо-компания — живой кандидат»: в ФИО и каналах заглушки, свободного текста нет,
    `disclosed_fields` пуст (Арх. 4.14). У `own_contacts` (PDF самого кандидата) `disclosed_at = None`.
    """

    candidate_id: UUID
    public_code: str
    first_name: str
    last_name: str
    middle_name: str | None = None
    about: str | None = None
    email: str | None = None
    phone: str | None = None
    telegram: str | None = None
    link: str | None = None
    custom_skills: list[str] = []
    disclosed_fields: list[DiscloseField] = []
    disclosed_at: datetime | None = None
    masked: bool = False


# --- PDF-профиль -----------------------------------------------------------------------------------------------------


class PdfFspBlock(BaseModel):
    """Блок ФСП в PDF-профиле: простая структура, которую заполняет `matching` (модули одного слоя типами
    не обмениваются, Арх. 2.4, п. 1). Блока нет (`None`) — печатается строка об отсутствии достижений.
    """

    headline: str
    lines: list[str] = []


class PdfDeclaredBlock(BaseModel):
    """Блок «Заявлено кандидатом · не проверено платформой»: готовые подписи, а не коды."""

    city: str | None = None
    experience_years: float | None = None
    roles: list[str] = []
    industry_domains: list[str] = []
    #: Заявленные навыки справочника, не подтверждённые тестом, заданием или ФСП.
    skills: list[str] = []
    soft_skills: list[str] = []
    custom_skills: list[str] = []
    about: str | None = None


class PdfContacts(BaseModel):
    """Каналы связи в PDF: работодателю — только из `contacts_for_pair`, кандидату — из `own_contacts`."""

    email: str | None = None
    phone: str | None = None
    telegram: str | None = None
    link: str | None = None

    @classmethod
    def from_contacts(cls, contacts: ContactsDTO) -> PdfContacts:
        return cls(email=contacts.email, phone=contacts.phone, telegram=contacts.telegram, link=contacts.link)


class ProfilePdfModel(BaseModel):
    """Данные для рендера PDF-профиля (`render_profile_pdf`; Арх. 6.14, приложение B, §1.7).

    Модель собирает `matching`. В ней нет и не должно быть минимума зарплаты, приглашений и позиций в подборках.
    Все строки — данные: шаблон экранирует их, разметка из них не исполняется.
    """

    #: Шапка: «Фамилия Имя Отчество», код кандидата, момент формирования (печатается дата по `APP_TZ`).
    full_name: str
    public_code: str
    generated_at: datetime
    #: Категория и уровень на шкале 0–100; `None` — категории нет (PDF самого кандидата до теста).
    category: CategoryRef | None = None
    level: LevelView | None = None
    #: Подтверждённые навыки с источником (вид доказательства, дата, пояснение).
    skills: list[EvidenceItem] = []
    fsp: PdfFspBlock | None = None
    declared: PdfDeclaredBlock | None = None
    contacts: PdfContacts = PdfContacts()

    @property
    def file_name(self) -> str:
        """Имя файла: `profile_{public_code}_{YYYYMMDD}.pdf`."""
        day = fmt_date(self.generated_at)  # ДД.ММ.ГГГГ по APP_TZ
        return f"profile_{self.public_code}_{day[6:]}{day[3:5]}{day[:2]}.pdf"

    def template_context(self) -> dict[str, Any]:
        """Данные шаблона как обычный словарь (моменты времени остаются `datetime`)."""
        return self.model_dump(mode="python")
