"""T5. Демо-провайдер ФСП ID: страница входа, решение, код авторизации, PKCE, повтор и срок кода, чужой redirect_uri."""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core import clock
from app.fsp_mock import oidc
from app.fsp_mock import reference as ref
from app.fsp_mock.models import AuthCode
from app.fsp_mock.personas import persona_fsp_id
from app.fsp_mock.registry_service import registry_session
from tests.fsp import mockdata

AUTHORIZE = "/api/fsp-mock/oidc/authorize"
DECISION = "/api/fsp-mock/oidc/authorize/decision"
VERIFIER = "v" * 64


def challenge(verifier: str = VERIFIER) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def params(**overrides: str) -> dict[str, str]:
    values = {
        "response_type": "code",
        "client_id": ref.CLIENT_ID,
        "redirect_uri": oidc.expected_redirect_uri(),
        "scope": ref.SCOPE,
        "state": "state-123",
        "nonce": "nonce-456",
        "code_challenge": challenge(),
        "code_challenge_method": "S256",
    }
    values.update(overrides)
    return values


def issue(client: TestClient, fsp_id: UUID, **overrides: str) -> str:
    response = client.post(DECISION, data={**params(**overrides), "fsp_id": str(fsp_id), "decision": "allow"},
                           follow_redirects=False)  # fmt: skip
    assert response.status_code == 302, response.text
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["state"] == [overrides.get("state", "state-123")]
    return query["code"][0]


def redeem(db: Session, code: str, **overrides: str) -> oidc.RedeemedCode:
    values = {"code_verifier": VERIFIER, "redirect_uri": oidc.expected_redirect_uri(), "client_id": ref.CLIENT_ID}
    values.update(overrides)
    with registry_session() as session:
        return oidc.redeem_code(session, code=code, now=clock.real_now(), **values)  # type: ignore[arg-type]


@pytest.fixture
def persona(db: Session) -> UUID:
    fsp_id = mockdata.add_athlete(db, fsp_id=persona_fsp_id("anna"), persona_key="anna")
    db.commit()
    return fsp_id


def test_authorize_page_lists_personas(client: TestClient, persona: UUID) -> None:
    page = client.get(AUTHORIZE, params=params())
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    assert "Демонстрационный ФСП ID" in page.text and "Анна Соколова" in page.text and "свободен" in page.text
    assert page.headers["Cache-Control"] == "no-store"
    for pick in oidc.PICKS:
        assert pick in page.text


@pytest.mark.parametrize(
    "broken",
    [
        {"state": ""},
        {"code_challenge": ""},
        {"nonce": ""},
        {"client_id": "other"},
        {"response_type": "token"},
        {"code_challenge_method": "plain"},
        {"redirect_uri": "https://evil.example.com/cb"},
    ],
)
def test_authorize_rejects_bad_request_without_redirect(
    client: TestClient, persona: UUID, broken: dict[str, str]
) -> None:
    """Ошибка запроса показывается страницей и не перенаправляет: иначе открытый редирект."""
    query = params(**broken)
    page = client.get(AUTHORIZE, params=query, follow_redirects=False)
    assert page.status_code == 400 and "Запрос не выполнен" in page.text
    decision = client.post(
        DECISION, data={**query, "fsp_id": str(persona), "decision": "allow"}, follow_redirects=False
    )
    assert decision.status_code == 400 and "location" not in decision.headers


def test_deny_redirects_with_access_denied(client: TestClient, persona: UUID) -> None:
    response = client.post(
        DECISION, data={**params(), "fsp_id": str(persona), "decision": "deny"}, follow_redirects=False
    )
    assert response.status_code == 302
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query == {"error": ["access_denied"], "state": ["state-123"]}


def test_code_is_stored_hashed_and_redeemed_once(client: TestClient, db: Session, persona: UUID) -> None:
    code = issue(client, persona)
    row = db.get(AuthCode, oidc.hash_code(code))
    assert row is not None and row.code_hash != code and code not in row.code_hash
    redeemed = redeem(db, code)
    assert redeemed.fsp_id == persona and redeemed.nonce == "nonce-456"
    with pytest.raises(oidc.InvalidGrant):
        redeem(db, code)


def test_wrong_code_verifier_fails_and_burns_code(client: TestClient, db: Session, persona: UUID) -> None:
    code = issue(client, persona)
    with pytest.raises(oidc.InvalidGrant):
        redeem(db, code, code_verifier="w" * 64)
    with pytest.raises(oidc.InvalidGrant):
        redeem(db, code)


def test_expired_code(client: TestClient, db: Session, persona: UUID, freeze_now: Callable[..., object]) -> None:
    code = issue(client, persona)
    freeze_now.tick(seconds=ref.AUTH_CODE_TTL_SECONDS + 1)  # type: ignore[attr-defined]
    with pytest.raises(oidc.InvalidGrant):
        redeem(db, code)


def test_foreign_redirect_uri_and_unknown_code(client: TestClient, db: Session, persona: UUID) -> None:
    code = issue(client, persona)
    with pytest.raises(oidc.InvalidGrant):
        redeem(db, code, redirect_uri="https://evil.example.com/cb")
    with pytest.raises(oidc.InvalidGrant):
        redeem(db, "no-such-code")


def test_quick_picks(client: TestClient, db: Session, persona: UUID) -> None:
    free = mockdata.add_athlete(db)
    mockdata.add_result(db, free, place=1)
    empty = mockdata.add_athlete(db)
    db.commit()
    for pick, expected in (("random_free_with_history", free), ("random_free_empty", empty)):
        response = client.post(DECISION, data={**params(), "pick": pick}, follow_redirects=False)
        code = parse_qs(urlsplit(response.headers["location"]).query)["code"][0]
        assert redeem(db, code).fsp_id == expected
    response = client.post(DECISION, data={**params(), "pick": "new_account"}, follow_redirects=False)
    code = parse_qs(urlsplit(response.headers["location"]).query)["code"][0]
    assert redeem(db, code).fsp_id not in {persona, free, empty}


def test_unknown_athlete_id_and_bad_pick(client: TestClient, persona: UUID) -> None:
    unknown = {**params(), "fsp_id": "00000000-0000-0000-0000-000000000000", "decision": "allow"}
    bad = client.post(DECISION, data=unknown, follow_redirects=False)
    assert bad.status_code == 400
    bad_pick = client.post(DECISION, data={**params(), "pick": "everyone"}, follow_redirects=False)
    assert bad_pick.status_code == 400
