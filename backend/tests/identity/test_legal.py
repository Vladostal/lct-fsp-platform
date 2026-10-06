"""`GET /legal/{doc}` (Арх. 9.4) и целостность текстов согласий."""

from __future__ import annotations

import hashlib

import pytest

from app.modules.identity import legal


@pytest.mark.parametrize("doc", ["processing", "publication", "privacy"])
def test_legal_doc(client, doc):
    response = client.get(f"/api/v1/legal/{doc}")
    assert response.status_code == 200
    body = response.json()
    assert body["doc"] == doc and body["version"] and body["title"] and body["text"]
    assert body["sha256"] == hashlib.sha256(body["text"].encode()).hexdigest()


def test_unknown_doc_is_404(client):
    response = client.get("/api/v1/legal/other")
    assert response.status_code == 404 and response.json()["code"] == "not_found"
    assert client.get("/api/v1/legal/..%2Fservice").status_code == 404


def test_processing_text_names_the_quarantine_and_basis():
    """Текст согласия называет срок хранения отметки об удалении и основание (поправка R3-tz-compliance-7)."""
    text = legal.get_doc("processing").text.lower()  # type: ignore[union-attr]
    assert "30" in text and "хэш" in text
