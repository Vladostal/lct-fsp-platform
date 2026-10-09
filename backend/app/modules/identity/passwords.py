"""Проверка нового пароля на очевидную слабость (Арх. 10.1).

Правил состава («обязательно цифра и заглавная») нет намеренно: они ухудшают пароли. Отсекается только то,
что подбирается первой сотней попыток: один повторённый знак, одни цифры и самые расхожие пароли. То же правило
повторено на клиенте (`frontend/src/features/auth/schemas.ts`), чтобы ошибка была видна до отправки формы.
"""

from __future__ import annotations

#: Самые расхожие пароли длиной от восьми знаков (сравнение без учёта регистра).
COMMON_PASSWORDS: frozenset[str] = frozenset(
    {
        "password", "password1", "password12", "password123", "passw0rd", "p@ssw0rd", "qwertyui", "qwertyuiop",
        "qwerty123", "qwerty1234", "qwerty12345", "1q2w3e4r", "1q2w3e4r5t", "1qaz2wsx", "zaq12wsx", "qazwsxedc",
        "abcd1234", "abc12345", "a1b2c3d4", "iloveyou", "letmein1", "welcome1", "welcome123", "admin123",
        "administrator", "football", "baseball", "superman", "sunshine", "princess", "trustno1", "starwars",
        "йцукенгш", "йцукенгшщз", "пароль123", "парольпароль",
    }
)  # fmt: skip

MESSAGE = "Пароль слишком простой: не используйте одни цифры, один повторённый знак и расхожие пароли"


def is_trivial(password: str) -> bool:
    """Пароль из одного повторённого знака, из одних цифр либо из списка расхожих."""
    return len(set(password)) == 1 or password.isdigit() or password.casefold() in COMMON_PASSWORDS
