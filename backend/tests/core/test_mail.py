"""Почта: шаблоны ядра, сборка письма, устойчивость к сбою SMTP (Арх. 2.4, п. 4; 10.2)."""

from __future__ import annotations

import logging

import pytest
from jinja2 import TemplateNotFound, UndefinedError

from app.core import mail

CONTEXTS = {
    "verify_email": {"link": "http://localhost:8080/verify-email?token=abc", "expires_hours": 24},
    "already_registered": {
        "login_link": "http://localhost:8080/login",
        "reset_link": "http://localhost:8080/password/forgot",
    },
    "password_reset": {"link": "http://localhost:8080/password/reset?token=abc", "expires_minutes": 60},
    "reregister_cooldown": {"available_at": "04.11.2026"},
}


@pytest.mark.parametrize("template", sorted(CONTEXTS))
def test_core_templates_render(template, settings):
    letter = mail.render(template, "user@example.com", CONTEXTS[template])
    assert letter.to == "user@example.com" and letter.template == template
    assert settings.app_name in letter.subject and "Тема:" not in letter.text
    for value in CONTEXTS[template].values():
        assert str(value) in letter.text
    assert "{{" not in letter.text and letter.html is None


def test_missing_variable_and_missing_template_fail_inside_the_request():
    with pytest.raises(UndefinedError):
        mail.render("verify_email", "user@example.com", {})  # нет link — ошибка, а не пустое место в письме
    with pytest.raises(TemplateNotFound):
        mail.render("no_such_template", "user@example.com", {})


def test_message_headers_and_cyrillic_body(settings):
    message = mail.build_message(mail.render("password_reset", "user@example.com", CONTEXTS["password_reset"]))
    assert message["To"] == "user@example.com"
    assert settings.mail_from in message["From"]
    assert message["Auto-Submitted"] == "auto-generated"
    assert message["Message-ID"] and message["Date"]
    assert "Сброс пароля" in str(message["Subject"])
    assert "новый пароль" in message.get_content()


def test_queue_is_per_session(db):
    mail.enqueue(db, "reregister_cooldown", "user@example.com", CONTEXTS["reregister_cooldown"])
    assert [item.template for item in mail.pending(db)] == ["reregister_cooldown"]
    assert len(mail.take(db)) == 1 and mail.pending(db) == []
    mail.enqueue(db, "reregister_cooldown", "user@example.com", CONTEXTS["reregister_cooldown"])
    mail.discard(db)
    assert mail.take(db) == []


def test_smtp_failure_is_logged_with_masked_address_and_does_not_raise(caplog):
    def broken(messages):
        raise ConnectionRefusedError("smtp down")

    previous = mail.set_transport(broken)
    try:
        with caplog.at_level(logging.WARNING, logger="app.mail"):
            mail.deliver([mail.render("verify_email", "ivan.petrov@example.com", CONTEXTS["verify_email"])])
    finally:
        mail.set_transport(previous)
    assert "письма не отправлены" in caplog.text
    assert "i***@example.com" in caplog.text and "ivan.petrov" not in caplog.text


def test_module_templates_directory_is_discovered(tmp_path, monkeypatch):
    """Модуль кладёт свои шаблоны в app/modules/<модуль>/mail_templates — ядро править не нужно."""
    module_dir = tmp_path / "app" / "modules" / "contact" / "mail_templates"
    module_dir.mkdir(parents=True)
    (module_dir / "invitation_received.txt").write_text(
        "Тема: Приглашение от {{ company }}\n\nОткройте {{ base_url }}\n", "utf-8"
    )
    (module_dir / "invitation_received.html").write_text("<p>{{ company }}</p>", "utf-8")
    (tmp_path / "app" / "core" / "mail_templates").mkdir(parents=True)
    monkeypatch.setattr(mail, "BACKEND_DIR", tmp_path)
    mail.reset_templates()
    try:
        letter = mail.render("invitation_received", "c@example.com", {"company": "Орбита <b>"})
        assert letter.subject == "Приглашение от Орбита <b>"
        assert "http://localhost:8080" in letter.text
        assert letter.html == "<p>Орбита &lt;b&gt;</p>"  # в HTML значения экранируются
        assert mail.build_message(letter).is_multipart()
    finally:
        monkeypatch.undo()
        mail.reset_templates()
