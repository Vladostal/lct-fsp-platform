# Образ api и migrate (Арх. 2.1, 13.7): Python 3.13.16, зависимости строго из uv.lock.
FROM python:3.13.16-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH

# Системные библиотеки WeasyPrint (PDF-профиль и документация): без них импорт weasyprint падает.
# tzdata — часовой пояс APP_TZ для дат «на сегодня».
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /usr/local/bin/uv

# Раскладка повторяет репозиторий: код — /srv/backend, рядом compose монтирует /srv/docs/validation и /srv/data.
WORKDIR /srv/backend

# Сначала только описание зависимостей: слой с окружением пересобирается лишь при изменении uv.lock.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Код копируется по каталогам, а не целиком: локальные .venv, кэши и тесты в образ не попадают.
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

# Процесс работает не от root. Каталог кэша нужен fontconfig (WeasyPrint): без него каждый PDF пишет ошибки в журнал.
RUN useradd --no-create-home --uid 10001 --shell /usr/sbin/nologin app \
    && mkdir -p /var/cache/app && chown app:app /var/cache/app
ENV HOME=/var/cache/app XDG_CACHE_HOME=/var/cache/app
USER app

EXPOSE 8000

# Один воркер; без --proxy-headers: адрес клиента приложение определяет само (Арх. 10.1).
CMD ["uvicorn", "app.main:app", "--host=0.0.0.0", "--port=8000", "--workers=1", "--no-proxy-headers", "--no-access-log"]
