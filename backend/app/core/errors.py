"""Единый формат ошибок API (Арх. 9.2).

Любая ошибка — своя (`ApiException`), ошибка разбора запроса, ошибка маршрутизации Starlette или необработанное
исключение — уходит клиенту как `ApiError {code, message, params?, fields?}`. Клиент ветвится по HTTP-статусу
для 401, 403, 404 и по `code` — для остального; текст берёт из своего словаря, `message` — запасной.

Модули поднимают ошибки так::

    raise ApiException(409, "company_profile_incomplete")
    raise ApiException(429, "rate_limited", params={"retry_after": 37})
    raise ApiException(422, "validation_error", fields=[field_error("city", "required", "Укажите город")])

а в роутере описывают их для OpenAPI: `responses=error_responses(404, 409, 422)`.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.background import BackgroundTask
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.shared.schemas import ApiError, ApiErrorField

log = logging.getLogger("app.errors")

ParamValue = str | int | float

#: Тексты общих кодов (Арх. 9.2). Тексты кодов модулей передаёт сам модуль либо хранит клиент.
DEFAULT_MESSAGES: dict[str, str] = {
    "bad_request": "Некорректный запрос",
    "not_authenticated": "Сессия истекла. Войдите снова",
    "forbidden": "Нет доступа к этому разделу",
    "not_found": "Здесь ничего нет: ссылка устарела или объект удалён",
    "feature_disabled": "Раздел выключен на этом стенде",
    "method_not_allowed": "Метод не поддерживается",
    "validation_error": "Проверьте заполнение полей",
    "cursor_invalid": "Список изменился. Обновите страницу",
    "rate_limited": "Слишком часто. Повторите позже",
    "internal_error": "Не получилось выполнить действие. Повторите попытку",
    "service_unavailable": "Сервис временно недоступен. Повторите попытку позже",
    "salary_order": "Нижняя граница вилки больше верхней",
    "salary_out_of_bounds": "Вилка вне допустимых пределов",
    "salary_range_too_wide": "Вилка слишком широкая",
}

#: Код по умолчанию для ошибок Starlette и FastAPI (`HTTPException` без собственного кода).
STATUS_CODES: dict[int, str] = {
    400: "bad_request",
    401: "not_authenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    503: "service_unavailable",
}

_STATUS_DESCRIPTIONS: dict[int, str] = {
    400: "Некорректный запрос",
    401: "Нет действующей сессии",
    403: "Чужая роль или действие запрещено",
    404: "Объекта нет или он чужой",
    409: "Действие противоречит текущему состоянию",
    410: "Срок действия истёк",
    413: "Слишком большой запрос",
    415: "Неподдерживаемый тип содержимого",
    422: "Ошибки полей или правил",
    429: "Превышен лимит; params.retry_after — секунды",
    500: "Необработанная ошибка",
    503: "Сервис временно недоступен",
}

#: Подписи частых ошибок разбора полей (тип ошибки Pydantic → русский текст).
_FIELD_MESSAGES: dict[str, str] = {
    "missing": "Обязательное поле",
    "string_too_short": "Слишком короткое значение",
    "string_too_long": "Слишком длинное значение",
    "string_type": "Ожидается строка",
    "string_pattern_mismatch": "Неверный формат",
    "int_type": "Ожидается целое число",
    "int_parsing": "Ожидается целое число",
    "int_from_float": "Ожидается целое число",
    "float_type": "Ожидается число",
    "float_parsing": "Ожидается число",
    "bool_type": "Ожидается «да» или «нет»",
    "bool_parsing": "Ожидается «да» или «нет»",
    "greater_than": "Значение слишком мало",
    "greater_than_equal": "Значение слишком мало",
    "less_than": "Значение слишком велико",
    "less_than_equal": "Значение слишком велико",
    "enum": "Недопустимое значение",
    "literal_error": "Недопустимое значение",
    "uuid_parsing": "Неверный идентификатор",
    "uuid_type": "Неверный идентификатор",
    "datetime_parsing": "Неверная дата",
    "datetime_from_date_parsing": "Неверная дата",
    "date_parsing": "Неверная дата",
    "date_from_datetime_parsing": "Неверная дата",
    "too_short": "Слишком мало значений",
    "too_long": "Слишком много значений",
    "list_type": "Ожидается список",
    "dict_type": "Ожидается объект",
    "model_attributes_type": "Ожидается объект",
    "json_invalid": "Тело запроса — не JSON",
    "extra_forbidden": "Лишнее поле",
    "url_parsing": "Неверный адрес",
    "value_error": "Недопустимое значение",
}


class ApiException(Exception):
    """Ошибка API с HTTP-статусом и кодом (Арх. 9.2).

    `commit=True` просит зафиксировать транзакцию запроса, а не откатить её: нужно там, где сама неудача должна
    остаться в базе (строка `login_attempt` при неверном пароле). По умолчанию ошибка откатывает всё, что успел
    записать обработчик, и сбрасывает очередь писем (Арх. 2.4, п. 4).
    """

    def __init__(
        self,
        status: int,
        code: str,
        message: str | None = None,
        params: Mapping[str, ParamValue] | None = None,
        fields: Sequence[ApiErrorField | Mapping[str, str]] | None = None,
        *,
        headers: Mapping[str, str] | None = None,
        commit: bool = False,
    ) -> None:
        self.status = status
        self.code = code
        self.message = message if message is not None else DEFAULT_MESSAGES.get(code, code)
        self.params = dict(params) if params else None
        self.fields = [ApiErrorField.model_validate(item) for item in fields] if fields else None
        self.headers = dict(headers) if headers else None
        self.commit = commit
        super().__init__(f"{status} {code}")

    def to_model(self) -> ApiError:
        return ApiError(code=self.code, message=self.message, params=self.params, fields=self.fields)


def field_error(name: str, code: str, message: str) -> ApiErrorField:
    """Ошибка одного поля для `ApiException(422, "validation_error", fields=[...])`."""
    return ApiErrorField(name=name, code=code, message=message)


def validation_error(*fields: ApiErrorField, code: str = "validation_error") -> ApiException:
    """422 с ошибками полей — короткая запись для сервисов."""
    return ApiException(422, code, fields=list(fields))


def not_found() -> ApiException:
    """404 `not_found`: объекта нет или он чужой — стороны эти случаи не различают (Арх. 10.3)."""
    return ApiException(404, "not_found")


def error_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """Описание ответов-ошибок роута для OpenAPI: `responses=error_responses(401, 403, 409)` (Арх. 9.1)."""
    return {
        status: {"model": ApiError, "description": _STATUS_DESCRIPTIONS.get(status, "Ошибка")} for status in statuses
    }


def error_response(
    status: int,
    code: str,
    message: str | None = None,
    params: Mapping[str, ParamValue] | None = None,
    fields: Sequence[ApiErrorField] | None = None,
    headers: Mapping[str, str] | None = None,
    background: BackgroundTask | None = None,
) -> JSONResponse:
    """Готовый ответ с телом `ApiError` (для промежуточных слоёв, где исключение поднять нельзя)."""
    body = ApiError(
        code=code,
        message=message if message is not None else DEFAULT_MESSAGES.get(code, code),
        params=dict(params) if params else None,
        fields=list(fields) if fields else None,
    )
    return JSONResponse(
        status_code=status,
        content=body.model_dump(mode="json", exclude_none=True),
        headers=dict(headers) if headers else None,
        background=background,
    )


def _field_name(loc: Sequence[Any]) -> str:
    """Путь ошибки Pydantic → имя поля формы: без префикса `body`/`query`/…, вложенность через точку."""
    parts = [str(part) for part in loc]
    if parts and parts[0] in {"body", "query", "path", "header", "cookie"}:
        parts = parts[1:]
    return ".".join(parts) if parts else "body"


def _fields_from_validation(errors: Sequence[Mapping[str, Any]]) -> list[ApiErrorField]:
    fields: list[ApiErrorField] = []
    for err in errors:
        kind = str(err.get("type", "value_error"))
        message = _FIELD_MESSAGES.get(kind)
        if message is None:
            # Незнакомый тип ошибки: текст Pydantic без служебного префикса лучше, чем код.
            message = str(err.get("msg", "Недопустимое значение")).removeprefix("Value error, ")
        fields.append(ApiErrorField(name=_field_name(err.get("loc", ())), code=kind, message=message))
    return fields


async def _handle_api_exception(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiException)
    # Письма транзакции, зафиксированной при `commit=True`: их кладёт сюда TxRoute уже после фиксации.
    background: BackgroundTask | None = getattr(request.state, "after_commit", None)
    return error_response(exc.status, exc.code, exc.message, exc.params, exc.fields, exc.headers, background)


async def _handle_validation(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return error_response(422, "validation_error", fields=_fields_from_validation(exc.errors()))


async def _handle_http(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = STATUS_CODES.get(exc.status_code, "error")
    # Текст `detail` Starlette («Not Found») клиенту не нужен: он показывает текст по коду.
    return error_response(exc.status_code, code, headers=exc.headers)


async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    # Тело без деталей (Арх. 9.2); подробности — только в журнале сервера.
    log.exception("необработанная ошибка: %s %s", request.method, request.url.path)
    return error_response(500, "internal_error")


def install_error_handlers(app: FastAPI) -> None:
    """Подключить обработчики к приложению (основному и демо-ФСП)."""
    app.add_exception_handler(ApiException, _handle_api_exception)
    app.add_exception_handler(RequestValidationError, _handle_validation)
    app.add_exception_handler(StarletteHTTPException, _handle_http)
    app.add_exception_handler(Exception, _handle_unexpected)


def patch_openapi_errors(schema: dict[str, Any]) -> dict[str, Any]:
    """Привести схему OpenAPI к фактическому формату ошибок.

    FastAPI сам дописывает роутам ответ 422 со схемой `HTTPValidationError`, а сервер отвечает `ApiError`.
    Чтобы сгенерированный клиент и Schemathesis видели правду, ссылки заменяются на `ApiError`, а неиспользуемые
    схемы удаляются.
    """
    components = schema.setdefault("components", {}).setdefault("schemas", {})
    if "ApiError" not in components:
        defs = ApiError.model_json_schema(ref_template="#/components/schemas/{model}")
        for name, sub in defs.pop("$defs", {}).items():
            components.setdefault(name, sub)
        components["ApiError"] = defs
    api_error_ref = {"$ref": "#/components/schemas/ApiError"}
    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            response = operation.get("responses", {}).get("422")
            if not response:
                continue
            for media in response.get("content", {}).values():
                if media.get("schema", {}).get("$ref", "").endswith("/HTTPValidationError"):
                    media["schema"] = api_error_ref
                    response["description"] = _STATUS_DESCRIPTIONS[422]
    components.pop("HTTPValidationError", None)
    components.pop("ValidationError", None)
    return schema
