"""Общие помощники модуля `matching`: ошибки с готовыми текстами и чтение справочника.

Справочник читается только через фасад `catalog.service` и всегда по имени атрибута модуля (а не через
`from … import`): так тесты подменяют фасад, пока модуль `catalog` пишется параллельно.
"""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.errors import ApiException, field_error
from app.modules.catalog import service as catalog
from app.modules.identity import service as identity
from app.shared.schemas import CategoryRef, Ref

#: Тексты ошибок модуля (Арх. 9.12); клиент берёт свой текст по `code`, это — запасной.
MESSAGES: dict[str, str] = {
    "company_profile_incomplete": "Сначала заполните профиль компании",
    "need_archived": "Потребность в архиве",
    "parent_mismatch": "Версия подборки не относится к этой потребности",
    "parent_required": "Укажите версию подборки, которую уточняете (parent_id)",
    "different_need": "Версии относятся к разным потребностям",
    "pin_limit": "Достигнут предел закреплённых кандидатов",
    "candidate_not_in_need": "Кандидата нет в подборках этой потребности",
    "text_too_short": "Текст слишком короткий для разбора",
    "text_too_long": "Текст слишком длинный",
    "skill_unknown": "Навыка нет в справочнике",
    "specialization_unavailable": "Тест для этой специализации и грейда пока недоступен",
    "filter_invalid": "Проверьте фильтры",
    "cursor_invalid": "Список изменился. Обновите страницу",
    "shortlist_rate_limited": "Слишком много версий подборки за час. Повторите позже",
    "card_open_limit": "Достигнут дневной предел открытых карточек",
    "bank_page_limit": "Достигнут дневной предел страниц банка кандидатов",
    "not_disclosed": "Кандидат не раскрыл контакты вашей компании",
    "no_category": "Сначала пройдите тест: категории ещё нет",
    "profile_incomplete": "Заполните профиль",
    "rate_limited": "Слишком часто. Повторите позже",
}


def api_error(
    status: int, code: str, *, params: Mapping[str, str | int | float] | None = None, field: str | None = None
) -> ApiException:
    """Ошибка модуля с готовым текстом; `field` добавляет запись в `fields[]` (имя поля формы)."""
    message = MESSAGES.get(code)
    exc = ApiException(status, code, message, params=params)
    if field is not None:
        exc.fields = [field_error(field, code, exc.message)]
    return exc


def is_demo_account(db: Session, user_id: UUID) -> bool:
    """Признак аккаунта `app_user.is_demo` (а не чип показа): по нему принимаются решения о доступе."""
    user = identity.users(db, [user_id]).get(user_id)
    return bool(user and user.is_demo)


# --- справочник -----------------------------------------------------------------------------------------------------


def skill_title(code: str) -> str:
    """Название навыка; код вне справочника (навык удалён из новой версии) отдаётся как есть."""
    try:
        return catalog.skill_ref(code).title
    except (KeyError, LookupError, ApiException):
        return code


def skill_refs(codes: list[str]) -> list[Ref]:
    return [Ref(code=code, title=skill_title(code)) for code in codes]


def grade_codes() -> list[str]:
    """Коды грейдов от младшего к старшему."""
    return [grade.code for grade in sorted(catalog.grades_ordered(), key=lambda item: item.order)]


def grade_title(code: str) -> str:
    for grade in catalog.grades_ordered():
        if grade.code == code:
            return grade.title
    return code


def specialization_codes() -> list[str]:
    """Коды специализаций в порядке каталога."""
    return [item.code for item in catalog.get_catalog().specializations]


def category_code(specialization_code: str, grade_code: str) -> str:
    return f"{specialization_code}:{grade_code}"


def category_ref(specialization_code: str, grade_code: str) -> CategoryRef:
    return catalog.category_ref(category_code(specialization_code, grade_code))


def closure(skill_code: str) -> frozenset[str]:
    """`implies_closure` каталога; для кода вне справочника — пусто."""
    try:
        return catalog.implies_closure(skill_code)
    except (KeyError, LookupError, ApiException):
        return frozenset()


def role_refs(codes: list[str]) -> list[Ref]:
    titles = {item.code: item.title for item in catalog.get_catalog().roles}
    return [Ref(code=code, title=titles.get(code, code)) for code in codes]
