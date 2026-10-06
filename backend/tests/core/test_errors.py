"""Формат ошибки везде `ApiError` (Арх. 9.2): 404, 422, 500 и собственные коды."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.core.deps import Db
from app.core.errors import ApiException, error_responses, field_error, patch_openapi_errors, validation_error
from app.shared.schemas import ApiError


class Payload(BaseModel):
    title: str = Field(min_length=3)
    amount: int = Field(ge=1)
    nested: dict[str, int] | None = None


def _router(tx_router: APIRouter) -> APIRouter:
    @tx_router.post("/items", responses=error_responses(409, 422))
    def create_item(payload: Payload, db: Db) -> dict[str, str]:
        if payload.title == "conflict":
            raise ApiException(409, "pair_cooldown", "Рано", params={"until": "2026-11-01"})
        if payload.title == "fields":
            raise validation_error(field_error("city", "required", "Укажите город"))
        if payload.title == "crash":
            raise RuntimeError("секретная деталь, которой не место в ответе")
        return {"title": payload.title}

    @tx_router.get("/items")
    def list_items(limit: Annotated[int, Query(ge=1, le=50)] = 20) -> dict[str, int]:
        return {"limit": limit}

    return tx_router


def assert_api_error(body: dict, code: str) -> ApiError:
    error = ApiError.model_validate(body)
    assert error.code == code
    assert error.message
    assert set(body) <= {"code", "message", "params", "fields"}
    return error


def test_unknown_route_is_api_error_404(probe, tx_router):
    response = probe(_router(tx_router)).get("/api/v1/nothing-here")
    assert response.status_code == 404
    assert_api_error(response.json(), "not_found")


def test_method_not_allowed_is_api_error(probe, tx_router):
    response = probe(_router(tx_router)).delete("/api/v1/items")
    assert response.status_code == 405
    assert_api_error(response.json(), "method_not_allowed")


def test_validation_error_lists_fields_by_form_name(probe, tx_router):
    response = probe(_router(tx_router)).post("/api/v1/items", json={"title": "ab", "amount": 0})
    assert response.status_code == 422
    error = assert_api_error(response.json(), "validation_error")
    assert error.fields is not None
    by_name = {item.name: item for item in error.fields}
    assert set(by_name) == {"title", "amount"}  # без префикса body
    assert by_name["title"].code == "string_too_short"
    assert by_name["title"].message == "Слишком короткое значение"


def test_validation_error_for_query_and_missing_body(probe, tx_router):
    client = probe(_router(tx_router))
    response = client.get("/api/v1/items", params={"limit": 500})
    assert response.status_code == 422
    assert [item.name for item in assert_api_error(response.json(), "validation_error").fields] == ["limit"]

    response = client.post("/api/v1/items", content=b"{not json", headers={"content-type": "application/json"})
    assert response.status_code == 422
    assert_api_error(response.json(), "validation_error")


def test_api_exception_carries_code_params_and_fields(probe, tx_router):
    client = probe(_router(tx_router))
    response = client.post("/api/v1/items", json={"title": "conflict", "amount": 1})
    assert response.status_code == 409
    assert response.json() == {"code": "pair_cooldown", "message": "Рано", "params": {"until": "2026-11-01"}}

    response = client.post("/api/v1/items", json={"title": "fields", "amount": 1})
    assert response.status_code == 422
    assert response.json()["fields"] == [{"name": "city", "code": "required", "message": "Укажите город"}]


def test_unhandled_error_is_500_without_details(probe, tx_router):
    client = probe(_router(tx_router), raise_server_exceptions=False)
    response = client.post("/api/v1/items", json={"title": "crash", "amount": 1})
    assert response.status_code == 500
    assert_api_error(response.json(), "internal_error")
    assert "секретная" not in response.text


def test_default_message_comes_from_dictionary():
    assert ApiException(401, "not_authenticated").message == "Сессия истекла. Войдите снова"
    assert ApiException(409, "some_module_code").message == "some_module_code"  # текст кода модуля — у клиента


def test_security_headers_on_every_response(probe, tx_router):
    client = probe(_router(tx_router))
    for response in (client.get("/api/v1/items"), client.get("/api/v1/nothing-here")):
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"


def test_foreign_origin_rejected_for_unsafe_methods_only(probe, tx_router):
    client = probe(_router(tx_router))
    body = {"title": "valid", "amount": 1}
    foreign = {"Origin": "https://evil.example.com"}
    rejected = client.post("/api/v1/items", json=body, headers=foreign)
    assert rejected.status_code == 403
    assert_api_error(rejected.json(), "forbidden")
    # Свой origin, dev-сервер Vite и запрос без Origin проходят; GET с чужим Origin — тоже (состояние не меняет).
    assert client.post("/api/v1/items", json=body, headers={"Origin": "http://localhost:8080"}).status_code == 200
    assert client.post("/api/v1/items", json=body, headers={"Origin": "http://localhost:5173"}).status_code == 200
    assert client.post("/api/v1/items", json=body).status_code == 200
    assert client.get("/api/v1/items", headers=foreign).status_code == 200


def test_openapi_declares_api_error_instead_of_fastapi_validation_schema(app):
    schema = app.openapi()
    assert "HTTPValidationError" not in schema["components"]["schemas"]
    assert "ApiError" in schema["components"]["schemas"]
    health = schema["paths"]["/api/v1/health"]["get"]
    assert health["operationId"] == "core-health"
    assert health["responses"]["503"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ApiError"
    }


def test_patch_openapi_replaces_422_reference():
    schema = {
        "paths": {
            "/x": {
                "post": {
                    "responses": {
                        "422": {
                            "description": "Validation Error",
                            "content": {
                                "application/json": {"schema": {"$ref": "#/components/schemas/HTTPValidationError"}}
                            },
                        }
                    }
                }
            }
        },
        "components": {"schemas": {"HTTPValidationError": {}, "ValidationError": {}}},
    }
    patched = patch_openapi_errors(schema)
    media = patched["paths"]["/x"]["post"]["responses"]["422"]["content"]["application/json"]
    assert media["schema"] == {"$ref": "#/components/schemas/ApiError"}
    assert set(patched["components"]["schemas"]) == {"ApiError", "ApiErrorField"}
