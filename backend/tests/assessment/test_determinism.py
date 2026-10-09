"""Воспроизводимость банка: один seed — один вариант в любом процессе и приёмка семейства при любом секрете.

Обе проверки появились после найденных ошибок:

* `db.fd_keys` обходил множество атрибутов ключа, а порядок обхода множества строк зависит от `PYTHONHASHSEED`:
  один и тот же seed давал разные варианты в разных процессах (3–5 вариантов из 180);
* уровень 3 `code.bug_logic` выбирал шаблон, который никогда не даёт редкой ошибки: брак доходил до 52 % при
  пороге 50 %, и приёмка семейства зависела от значения `ASSESSMENT_SECRET` (на стенде со случайным секретом
  семейство могло не попасть в банк).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.modules.assessment.bank.build import MAX_REJECT_SHARE, BuildOptions, build_family
from app.modules.assessment.families import discover

BACKEND_DIR = Path(__file__).resolve().parents[2]

#: Печатает отпечаток вариантов каждого семейства: первые принятые варианты уровня для сидов 1..N.
_DIGEST_SCRIPT = """
import hashlib, json, sys
from app.modules.assessment.families import discover
from app.modules.assessment.families._lib.contract import Reject, variant_to_json

skip = set(sys.argv[2].split(","))
out = {}
for family in sorted(discover().families, key=lambda item: item.meta.id):
    if family.meta.id in skip:
        continue
    digest = hashlib.sha256()
    for level in (item.level for item in family.meta.levels):
        for seed in range(1, int(sys.argv[1]) + 1):
            try:
                line = json.dumps(variant_to_json(family.generate(level, seed)), sort_keys=True, ensure_ascii=False)
            except Reject as exc:
                line = f"reject:{exc}"
            digest.update(line.encode())
    out[family.meta.id] = digest.hexdigest()
print(json.dumps(out))
"""

#: Семейства на настоящем `git`: генерация на порядок дольше, а множеств строк в них нет.
_SLOW = ("git.log_reach", "git.merge_rebase", "git.reset_restore")


def _digests(hash_seed: str, seeds: int = 25) -> dict[str, str]:
    env = {
        **os.environ,
        "PYTHONHASHSEED": hash_seed,
        "PYTHONPATH": str(BACKEND_DIR),
        "ASSESSMENT_SECRET": "test-only-assessment-secret",
        "ADMIN_TOKEN": "test-only-admin-token",
    }
    done = subprocess.run(
        [sys.executable, "-c", _DIGEST_SCRIPT, str(seeds), ",".join(_SLOW)],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_generation_does_not_depend_on_python_hash_seed() -> None:
    first, second, third = _digests("0"), _digests("1"), _digests("4242")
    assert len(first) >= 25
    differs = sorted(family for family in first if not first[family] == second[family] == third[family])
    assert differs == [], f"варианты зависят от PYTHONHASHSEED: {differs}"


@pytest.mark.parametrize("secret", ["test-secret", "rnd-a1", "rnd-b2", "rnd-c3", "s1"])
def test_bug_logic_is_accepted_whatever_the_secret(secret: str) -> None:
    """С шаблоном `longest_run` на уровне 3 секреты `test-secret` и `s1` давали брак 52 % и отказ в приёмке."""
    family = next(item for item in discover().families if item.meta.id == "code.bug_logic")
    result = build_family(family, BuildOptions(secret=secret, per_level=60, time_check=False))
    assert result.errors == []
    for level in result.levels:
        assert level.ok and level.accepted == 60, (secret, level.level, level.errors)
        # Запас до порога: брак уровня заметно ниже предельного, а не «чуть-чуть прошёл».
        assert level.reject_share <= MAX_REJECT_SHARE - 0.08, (secret, level.level, level.reject_share)
