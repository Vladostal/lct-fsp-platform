"""Загрузка резюме: проверки до разбора, учёт загрузок, ответ `ResumeParseResult` (Арх. 6.14, 10.7)."""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.errors import ApiException
from app.modules.profile.constants import (
    RESUME_FIELDS_TOTAL,
    RESUME_MAX_BYTES,
    RESUME_PARSER_VERSION,
    RESUME_RATE_PER_HOUR,
)
from app.modules.profile.models import ResumeUpload
from app.modules.profile.resume.parser import ERRORS, ResumeFailure, build_result, run_extract
from app.modules.profile.schemas import ResumeParseResult

SIGNATURE = b"%PDF-"
SIGNATURE_WINDOW = 1024


def _error(code: str, *, commit: bool = False) -> ApiException:
    status, message = ERRORS[code]
    return ApiException(status, code, message, commit=commit)


def check_before_parse(db: Session, candidate_id: UUID, data: bytes, now: datetime) -> None:
    """Проверки до разбора — первая сработавшая: размер, сигнатура `%PDF-`, частота (10 в час, счёт строк загрузок)."""
    if len(data) > RESUME_MAX_BYTES:
        raise _error("resume_too_large")
    if SIGNATURE not in data[:SIGNATURE_WINDOW]:
        raise _error("resume_not_pdf")
    since = now - timedelta(hours=1)
    recent = db.scalar(
        select(func.count())
        .select_from(ResumeUpload)
        .where(ResumeUpload.user_id == candidate_id, ResumeUpload.created_at > since)
    )
    if (recent or 0) >= RESUME_RATE_PER_HOUR:
        raise _error("resume_rate_limited")


def upload_resume(db: Session, candidate_id: UUID, data: bytes, now: datetime) -> ResumeParseResult:
    """Разобрать PDF и сохранить результат только как предзаполнение формы.

    Байты файла нигде не остаются: в базе — хэш, размер и результат разбора, который обнуляется при сохранении
    профиля с этой загрузкой либо через 24 часа (`purge_resume_results`). Неудачный разбор тоже записывается
    (код ошибки, страницы нет): он считается в часовом лимите, поэтому «тяжёлый» файл нельзя слать бесконечно.
    """
    check_before_parse(db, candidate_id, data, now)
    started = time.monotonic()
    digest = hashlib.sha256(data).hexdigest()
    try:
        extracted = run_extract(data)
    except ResumeFailure as failure:
        if failure.code == "resume_rate_limited":  # очередь занята: загрузка не началась, строки нет
            raise _error(failure.code) from None
        db.add(
            ResumeUpload(
                id=uuid4(),
                user_id=candidate_id,
                sha256=digest,
                size_bytes=len(data),
                status="failed",
                error_code=failure.code,
                parser_version=RESUME_PARSER_VERSION,
                created_at=now,
            )
        )
        db.flush()
        raise _error(failure.code, commit=True) from None

    parsed = build_result(
        extracted["text"],
        today=clock.to_local_date(now),
        pages=int(extracted["pages"]),
        engine=str(extracted["engine"]),
        started=started,
    )
    upload_id = uuid4()
    result = ResumeParseResult(
        upload_id=upload_id,
        fields=parsed.fields,
        recognized=parsed.recognized,
        total=RESUME_FIELDS_TOTAL,
        unknown_terms=parsed.unknown_terms,
        meta=parsed.meta,
    )
    db.add(
        ResumeUpload(
            id=upload_id,
            user_id=candidate_id,
            sha256=digest,
            size_bytes=len(data),
            pages=parsed.meta.pages,
            engine=parsed.meta.engine,
            status="parsed",
            result=result.model_dump(mode="json"),
            parser_version=RESUME_PARSER_VERSION,
            created_at=now,
        )
    )
    db.flush()
    return result
