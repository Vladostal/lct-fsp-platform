"""Сборка банка в памяти: генерация вариантов по уровням, линтер, сверка с оракулом, отчёт (Арх. 5.3; прил. A, §2.7).

Этот файл ничего не пишет в базу: он превращает загруженные семейства в принятые варианты и отчёт о браке.
Запись в таблицы — отдельный шаг (`bank/store.py`), который получает готовый `BankBuild`.

Порядок набора уровня:

1. seed варианта `n = 0, 1, 2, …` — `HMAC_SHA256(ASSESSMENT_SECRET, "variant:{id}:{version}:{level}:{n}")[:8]`;
2. `generate(level, seed)`; `Reject` и любое исключение — брак;
3. `lint_variant` (L01–L08, L10), затем правило распределения ответов L09, затем `oracle_check`, если он есть;
4. набор идёт до квоты либо до `5 × квота` попыток.

Уровень принят, если набрана квота, брак не выше 50 %, каждый вызов `generate` уложился в 200 мс, а в среднем
на принятый вариант ушло не больше 30 мс. Семейство принято, если приняты все его уровни. Сборка детерминирована:
при том же секрете и той же версии семейства получается тот же набор вариантов.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.modules.assessment.bank.linter import AnswerBalance, LintIssue, lint_variant
from app.modules.assessment.families._lib.contract import (
    Family,
    OracleUnavailable,
    Reject,
    Variant,
    content_hash,
)
from app.modules.assessment.families.registry import REGISTRY

__all__ = [
    "MAX_ATTEMPTS_FACTOR",
    "MAX_CALL_MS",
    "MAX_MEAN_MS",
    "MAX_REJECT_SHARE",
    "BankBuild",
    "BuildOptions",
    "FamilyBuild",
    "LevelBuild",
    "build_bank",
    "build_family",
    "variant_seed",
]

#: Попыток на уровень — не больше `5 × квота` (приложение A, §2.7).
MAX_ATTEMPTS_FACTOR = 5
#: Наибольшая доля брака на уровне.
MAX_REJECT_SHARE = 0.5
#: Пределы времени `generate` (Арх. 5.3): один вызов и среднее на принятый вариант, миллисекунды.
MAX_CALL_MS = 200.0
MAX_MEAN_MS = 30.0
#: Сколько примеров сообщений каждого вида брака хранить в отчёте уровня.
_EXAMPLES_PER_CODE = 3


@dataclass(frozen=True)
class BuildOptions:
    """Параметры сборки."""

    secret: str
    per_level: int = 60
    demo_per_level: int = 3
    #: Не требовать `oracle_check` и не считать недоступный оракул ошибкой (локальная проверка без git и Node.js).
    skip_oracle: bool = False
    #: Проверять пределы времени `generate`; выключается на перегруженной машине и в тестах.
    time_check: bool = True


@dataclass
class LevelBuild:
    """Результат набора одного уровня."""

    level: int
    b: float
    quota: int
    attempts: int = 0
    #: Принятые варианты в порядке `n`; `demo` — варианты предпросмотра из отдельного пространства seed.
    variants: list[Variant] = field(default_factory=list)
    demo: list[Variant] = field(default_factory=list)
    #: Код брака -> число вариантов: `L01`…`L10`, `reject:<причина>`, `error:<исключение>`, `oracle`, `time`.
    rejects: Counter[str] = field(default_factory=Counter)
    #: Код брака -> первые сообщения с seed: по ним автор воспроизводит случай вызовом `generate(level, seed)`.
    examples: dict[str, list[str]] = field(default_factory=dict)
    max_ms: float = 0.0
    total_ms: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def accepted(self) -> int:
        """Число принятых вариантов."""
        return len(self.variants)

    @property
    def reject_share(self) -> float:
        """Доля брака среди попыток."""
        return 0.0 if not self.attempts else 1 - self.accepted / self.attempts

    @property
    def mean_ms(self) -> float:
        """Время генерации на принятый вариант: всё время `generate`, включая брак, делённое на число принятых."""
        return self.total_ms / self.accepted if self.accepted else self.total_ms

    @property
    def ok(self) -> bool:
        """Принят ли уровень."""
        return not self.errors

    def note(self, code: str, seed: int, message: str) -> None:
        """Учесть бракованный вариант."""
        self.rejects[code] += 1
        bucket = self.examples.setdefault(code, [])
        if len(bucket) < _EXAMPLES_PER_CODE:
            bucket.append(f"seed={seed}: {message}")

    def to_json(self) -> dict[str, Any]:
        """Строка `bank_report.json`."""
        return {
            "level": self.level,
            "b": self.b,
            "quota": self.quota,
            "attempts": self.attempts,
            "accepted": self.accepted,
            "demo": len(self.demo),
            "reject_share": round(self.reject_share, 3),
            "rejects": dict(sorted(self.rejects.items())),
            "examples": self.examples,
            "max_ms": round(self.max_ms, 1),
            "mean_ms_per_accepted": round(self.mean_ms, 1),
            "ok": self.ok,
            "errors": self.errors,
        }


@dataclass
class FamilyBuild:
    """Результат сборки семейства."""

    family: Family
    levels: list[LevelBuild] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Принято ли семейство: нет ошибок семейства и приняты все уровни."""
        return not self.errors and all(level.ok for level in self.levels)

    def to_json(self) -> dict[str, Any]:
        """Раздел семейства в `bank_report.json`."""
        meta = self.family.meta
        spec = REGISTRY.get(meta.id)
        return {
            "id": meta.id,
            "version": meta.version,
            "title": meta.title,
            "module": self.family.module,
            "group": meta.group,
            "priority": meta.priority,
            "core_p0": bool(spec and spec.core_p0),
            "oracle": spec.oracle if spec else None,
            "oracle_check": self.family.oracle_check is not None,
            # Семейства без независимого оракула называются в отчёте: их ключ проверяет человек (Арх. 5.3, H2).
            "manual_review": bool(spec and spec.oracle == "manual"),
            "ok": self.ok,
            "errors": self.errors,
            "levels": [level.to_json() for level in self.levels],
        }


@dataclass
class BankBuild:
    """Результат сборки набора семейств."""

    options: BuildOptions
    families: list[FamilyBuild] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Приняты ли все собранные семейства."""
        return all(family.ok for family in self.families)

    def accepted(self) -> list[Family]:
        """Принятые семейства: по ним считается доступность пар (Арх. 5.2)."""
        return [item.family for item in self.families if item.ok]


def variant_seed(secret: str, family_id: str, version: int, level: int, n: int, *, demo: bool = False) -> int:
    """Seed варианта (приложение A, §2.7): первые 8 байт HMAC-SHA256, целое без знака (до 2^64 − 1).

    У вариантов предпросмотра своё пространство seed (префикс `demo:`): они не пересекаются с вариантами сессий.
    """
    label = f"{'demo:' if demo else ''}variant:{family_id}:{version}:{level}:{n}"
    digest = hmac.new(secret.encode("utf-8"), label.encode("utf-8"), hashlib.sha256).digest()
    return int.from_bytes(digest[:8], "big")


def _attempt(
    family: Family, out: LevelBuild, seed: int, hashes: set[str], options: BuildOptions, balance: AnswerBalance | None
) -> Variant | None:
    """Одна попытка: вариант либо `None` с записью причины брака в `out`."""
    started = time.perf_counter()
    produced: object = None
    failure: tuple[str, str] | None = None
    try:
        produced = family.generate(out.level, seed)
    except Reject as exc:
        failure = (f"reject:{exc.reason}", "вырожденные параметры")
    except Exception as exc:
        failure = (f"error:{type(exc).__name__}", str(exc))
    elapsed = (time.perf_counter() - started) * 1000
    out.total_ms += elapsed
    out.max_ms = max(out.max_ms, elapsed)
    if failure is not None:
        out.note(failure[0], seed, failure[1])
        return None
    if not isinstance(produced, Variant):
        out.note("L01", seed, f"generate вернул {type(produced).__name__}, а не Variant")
        return None
    variant = produced
    if (variant.level, variant.seed) != (out.level, seed):
        out.note("L01", seed, "level или seed варианта не совпадают с аргументами generate")
        return None
    if options.time_check and elapsed > MAX_CALL_MS:
        out.note("time", seed, f"generate работал {elapsed:.0f} мс при пределе {MAX_CALL_MS:.0f} мс")
        return None
    issues: list[LintIssue] = lint_variant(family, variant, seen_hashes=hashes)
    if not issues and balance is not None:
        issues = balance.check(variant)
    if issues:
        # Вариант считается браком один раз — по первому нарушению; остальные видны в примерах.
        out.note(issues[0].code, seed, "; ".join(issue.message for issue in issues))
        return None
    if family.oracle_check is not None and not options.skip_oracle:
        try:
            mismatch = list(family.oracle_check(variant))
        except OracleUnavailable as exc:
            text = f"оракул недоступен: {exc}; установите его или запустите с --skip-oracle"
            if text not in out.errors:
                out.errors.append(text)
            mismatch = []
        except Exception as exc:
            mismatch = [f"oracle_check упал: {type(exc).__name__}: {exc}"]
        if mismatch:
            out.note("oracle", seed, "; ".join(str(item) for item in mismatch))
            return None
    return variant


def _build_level(family: Family, level: int, b: float, options: BuildOptions) -> LevelBuild:
    meta = family.meta
    out = LevelBuild(level=level, b=b, quota=options.per_level)
    hashes: set[str] = set()
    balance = AnswerBalance(quota=options.per_level)
    for n in range(options.per_level * MAX_ATTEMPTS_FACTOR):
        if out.accepted >= options.per_level:
            break
        out.attempts += 1
        seed = variant_seed(options.secret, meta.id, meta.version, level, n)
        variant = _attempt(family, out, seed, hashes, options, balance)
        if variant is not None:
            out.variants.append(variant)
            hashes.add(content_hash(variant))
            balance.add(variant)

    # Варианты предпросмотра: тот же линтер, но без правила распределения — их всего три.
    demo_out = LevelBuild(level=level, b=b, quota=options.demo_per_level)
    for n in range(options.demo_per_level * MAX_ATTEMPTS_FACTOR * 2):
        if len(out.demo) >= options.demo_per_level:
            break
        seed = variant_seed(options.secret, meta.id, meta.version, level, n, demo=True)
        variant = _attempt(family, demo_out, seed, hashes, options, None)
        if variant is not None:
            out.demo.append(variant)
            hashes.add(content_hash(variant))
    out.errors.extend(error for error in demo_out.errors if error not in out.errors)

    if out.accepted < options.per_level:
        out.errors.append(f"принято {out.accepted} из {options.per_level} за {out.attempts} попыток")
    if out.reject_share > MAX_REJECT_SHARE:
        out.errors.append(f"брак {out.reject_share:.0%} выше {MAX_REJECT_SHARE:.0%}")
    if len(out.demo) < options.demo_per_level:
        out.errors.append(f"вариантов предпросмотра {len(out.demo)} из {options.demo_per_level}")
    if options.time_check and out.mean_ms > MAX_MEAN_MS:
        out.errors.append(f"в среднем {out.mean_ms:.0f} мс на принятый вариант при пределе {MAX_MEAN_MS:.0f} мс")
    return out


def build_family(family: Family, options: BuildOptions) -> FamilyBuild:
    """Собрать все уровни семейства."""
    result = FamilyBuild(family=family)
    spec = REGISTRY.get(family.meta.id)
    if spec is not None and spec.needs_oracle_check and family.oracle_check is None and not options.skip_oracle:
        result.errors.append(
            f"нет oracle_check: ключ семейства обязан сверяться с независимым оракулом «{spec.oracle}» (Арх. 5.3)"
        )
    for level in family.meta.levels:
        result.levels.append(_build_level(family, level.level, level.b, options))
    return result


def build_bank(families: Iterable[Family], options: BuildOptions, only: Sequence[str] = ()) -> BankBuild:
    """Собрать семейства; `only` — идентификаторы, которыми ограничена сборка (`--family`)."""
    result = BankBuild(options=options)
    for family in families:
        if only and family.meta.id not in only:
            continue
        result.families.append(build_family(family, options))
    return result
