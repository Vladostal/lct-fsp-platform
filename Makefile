# Команды проекта (Арх. 12.6). Справка: make help
#
# Локальное окружение бэкенда — backend/.venv (создаёт make venv через uv). Команды с базой ходят в базу
# разработки на 127.0.0.1:5432 (make dev-db). Тесты читают только своё окружение (backend/tests/conftest.py).

SHELL := /bin/bash
.DEFAULT_GOAL := help
.PHONY: help venv up down dev-db dev-db-down dev-init dev-api init-env test test-db-clean lint snapshot openapi client \
        bank bank-check seed demo-reset eval-testing eval-matching eval-contact eval docs-pdf versions e2e

# uv: из PATH либо из окружения в корне проекта (python3 -m venv .venv && .venv/bin/pip install uv).
UV ?= $(shell command -v uv 2>/dev/null || echo $(CURDIR)/.venv/bin/uv)
VENV := backend/.venv
BIN := .venv/bin
PY := $(BIN)/python

COMPOSE ?= docker compose
COMPOSE_DEV := $(COMPOSE) -f compose.yml -f compose.dev.yml

# База и почта разработки (compose.dev.yml публикует их на 127.0.0.1).
DEV_DATABASE_URL ?= postgresql+psycopg://app:app@127.0.0.1:5432/app
# Окружение локальных команд: значения из .env, но адреса — локальные.
LOCAL_ENV := APP_ENV_FILE=../.env DATABASE_URL=$(DEV_DATABASE_URL) SMTP_HOST=127.0.0.1 SMTP_PORT=1025

# PKG — модуль или пакет: каталоги backend/app/modules/<PKG>, backend/app/<PKG>, backend/tests/<PKG>.
# PKG=core — каркас: app/core, app/shared, main.py, wiring.py, scripts, tests/core, conftest.py.
# T — явные пути тестов вместо вычисленных по PKG; ARGS — дополнительные аргументы команды (pytest, eval).
PKG ?=
T ?=
ARGS ?=

CORE_SRC := app/core app/shared app/main.py app/wiring.py app/scripts alembic/env.py
CORE_TESTS := tests/core tests/conftest.py tests/architecture/test_import_contracts.py

help: ## Список команд
	@grep -hE '^[a-zA-Z0-9_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  \033[1m%-16s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "  Примеры: make test PKG=contact · make lint PKG=core · make test T=tests/assessment/families ARGS='-k sql -x'"

# --- окружение ---------------------------------------------------------------------------------------------------------

venv: ## Создать или обновить backend/.venv строго по uv.lock
	@test -x "$(UV)" || { echo "uv не найден: python3 -m venv .venv && .venv/bin/pip install uv"; exit 1; }
	cd backend && "$(UV)" sync --frozen

$(VENV)/bin/python:
	@$(MAKE) --no-print-directory venv

# --- стенд -------------------------------------------------------------------------------------------------------------

up: ## Поднять стенд: http://localhost:8080 (нужен .env: cp .env.example .env)
	@test -f .env || { echo "нет файла .env: cp .env.example .env (или make init-env для публичного стенда)"; exit 1; }
	$(COMPOSE) up --build -d
	@echo "стенд: http://localhost:8080 · почта: http://localhost:8080/mail/ · Swagger: http://localhost:8080/api/docs"

down: ## Остановить стенд (данные остаются; удалить том БД — docker compose down -v)
	$(COMPOSE) down

dev-db: ## База и почта для локальной разработки и тестов (127.0.0.1:5432, SMTP 1025, ящик 8025/mail/)
	@test -f .env || cp .env.example .env
	$(COMPOSE_DEV) up -d db mailpit

dev-db-down: ## Остановить базу и почту разработки
	$(COMPOSE_DEV) stop db mailpit

dev-init: $(VENV)/bin/python ## Локальная инициализация: схема и шаги INIT_STEPS в базе разработки
	cd backend && $(LOCAL_ENV) $(PY) -m app.scripts.init

dev-api: $(VENV)/bin/python ## Локальный сервер API с перезагрузкой: http://127.0.0.1:8000/api/docs
	cd backend && $(LOCAL_ENV) $(BIN)/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 --no-proxy-headers

define INIT_ENV_PY
import pathlib, re, secrets, sys
source, target = pathlib.Path(".env.example"), pathlib.Path(".env")
values = {
    "ASSESSMENT_SECRET": secrets.token_hex(32),
    "ADMIN_TOKEN": secrets.token_hex(32),
    "MAIL_UI_USER": "jury",
    "MAIL_UI_PASSWORD": secrets.token_urlsafe(12),
    "DEMO_PUBLIC_RESTART": "false",
    "WIRING_STRICT": "true",
}
text = source.read_text(encoding="utf-8")
for key, value in values.items():
    text, count = re.subn(rf"(?m)^{key}=.*$$", f"{key}={value}", text)
    if not count:
        sys.exit(f"в .env.example нет переменной {key}")
target.write_text(text, encoding="utf-8")
target.chmod(0o600)
print(".env создан: случайные ASSESSMENT_SECRET и ADMIN_TOKEN, пароль ящика /mail/ (MAIL_UI_USER=jury), DEMO_PUBLIC_RESTART=false.")
print("Для публичного стенда задайте вручную: APP_ENV=production, PUBLIC_BASE_URL=https://…, COOKIE_SECURE=true,")
print("NGINX_REAL_IP_FROM=<адрес внешнего прокси>, REREGISTER_COOLDOWN_DAYS и флаги FEATURE_* принятых усилений (Арх. 13.8).")
endef
export INIT_ENV_PY

init-env: ## Создать .env из .env.example со случайными секретами (публичный стенд); FORCE=1 — перезаписать
	@if [ -f .env ] && [ -z "$(FORCE)" ]; then echo ".env уже есть; перезаписать: make init-env FORCE=1"; exit 1; fi
	@python3 -c "$$INIT_ENV_PY"

# --- проверки ----------------------------------------------------------------------------------------------------------

test: $(VENV)/bin/python ## pytest: всё, один пакет (PKG=модуль) или явные пути (T=...); каждый запуск — в своей базе
	@cd backend && \
	if [ -n "$(T)" ]; then paths="$(T)"; \
	elif [ "$(PKG)" = "core" ]; then paths="tests/core tests/architecture/test_import_contracts.py"; \
	elif [ -n "$(PKG)" ]; then paths="tests/$(PKG)"; \
	else paths=""; fi; \
	if [ -n "$(PKG)" ] && [ -z "$(T)" ] && [ "$(PKG)" != "core" ] && [ ! -d "tests/$(PKG)" ]; then \
	  echo "нет каталога backend/tests/$(PKG)"; exit 1; fi; \
	echo "pytest $$paths $(ARGS)"; \
	$(PY) -m pytest $$paths $(ARGS)

test-db-clean: ## Удалить оставшиеся базы test_* после аварийно убитых прогонов (только когда тесты никто не гоняет)
	@if [ -z "$(CONFIRM)" ]; then echo "удалит ВСЕ базы test_* на сервере разработки, включая идущие прогоны: make test-db-clean CONFIRM=1"; exit 1; fi
	@$(COMPOSE_DEV) exec -T db psql -U app -d app -Atc "SELECT datname FROM pg_database WHERE datname LIKE 'test\_%'" \
	  | while read -r name; do echo "DROP DATABASE $$name"; \
	      $(COMPOSE_DEV) exec -T db psql -U app -d app -qc "DROP DATABASE IF EXISTS \"$$name\" WITH (FORCE)"; done

lint: $(VENV)/bin/python ## ruff, mypy, import-linter; с PKG — только пакет; без PKG — всё, alembic check, tsc и biome
	@cd backend && set -e; \
	if [ "$(PKG)" = "core" ]; then src="$(CORE_SRC)"; tests="$(CORE_TESTS)"; \
	elif [ -n "$(PKG)" ]; then \
	  src=""; tests=""; \
	  for path in app/modules/$(PKG) app/$(PKG); do [ -e "$$path" ] && src="$$src $$path"; done; \
	  [ -e "tests/$(PKG)" ] && tests="tests/$(PKG)"; \
	  if [ -z "$$src$$tests" ]; then echo "нет каталогов пакета $(PKG)"; exit 1; fi; \
	else src="app alembic/env.py"; tests="tests"; fi; \
	echo "ruff check $$src $$tests"; \
	$(BIN)/ruff check $$src $$tests; \
	if [ -n "$$src" ]; then \
	  if [ -n "$(PKG)" ]; then \
	    echo "mypy --follow-imports=silent $$src"; $(BIN)/mypy --follow-imports=silent $$src; \
	  else \
	    echo "mypy $$src"; $(BIN)/mypy $$src; \
	  fi; \
	fi; \
	echo "lint-imports"; \
	$(BIN)/lint-imports --no-cache
ifeq ($(PKG),)
	@if ls backend/alembic/versions/*.py >/dev/null 2>&1; then \
	  echo "alembic check"; cd backend && $(LOCAL_ENV) $(BIN)/alembic check; \
	else echo "alembic check пропущен: начальной миграции ещё нет (схема создаётся из метаданных, Арх. 13.2)"; fi
	cd frontend && npm run typecheck && npm run lint
endif

# --- точки отката и артефакты --------------------------------------------------------------------------------------------

SNAPSHOT_DIR ?= ../snapshots

snapshot: ## Архив рабочего каталога без зависимостей и сборок в ../snapshots/ (точка отката)
	@mkdir -p "$(SNAPSHOT_DIR)"
	@name="$(SNAPSHOT_DIR)/$(notdir $(CURDIR))-$$(date +%Y%m%d-%H%M%S).tar.gz"; \
	COPYFILE_DISABLE=1 tar -czf "$$name" \
	  --exclude='./.git' --exclude='node_modules' --exclude='.venv' --exclude='dist' --exclude='__pycache__' \
	  --exclude='.mypy_cache' --exclude='.ruff_cache' --exclude='.pytest_cache' --exclude='.import_linter_cache' \
	  --exclude='test-results' --exclude='playwright-report' --exclude='.DS_Store' . && \
	echo "снимок: $$name ($$(du -h "$$name" | cut -f1))"

openapi: $(VENV)/bin/python ## Выгрузить docs/api/openapi.json без запуска сервера (запускает сборочный пакет)
	cd backend && $(LOCAL_ENV) $(PY) -m app.scripts.export_openapi $(ARGS)

client: ## Сгенерировать клиент фронтенда из docs/api/openapi.json (запускает сборочный пакет)
	cd frontend && npm run client

# Скрипты сборки документации принадлежат сборочному пакету (docs/submission). PDF собирается в образе api:
# там установлены системные библиотеки WeasyPrint.
DOCS_PDF_SCRIPT ?= docs/submission/build_docs.py
VERSIONS_SCRIPT ?= docs/submission/build_versions.py

docs-pdf: ## PDF сопроводительной документации в docs/submission/ (WeasyPrint, в контейнере)
	@test -f $(DOCS_PDF_SCRIPT) || { echo "нет $(DOCS_PDF_SCRIPT): скрипт сборки документации ещё не написан"; exit 1; }
	$(COMPOSE) run --rm --no-deps --user "$$(id -u):$$(id -g)" -v "$(CURDIR)":/srv/repo -w /srv/repo \
	  -e PYTHONPATH=/srv/backend api python $(DOCS_PDF_SCRIPT) $(ARGS)

versions: $(VENV)/bin/python ## Таблица библиотек из uv.lock и package-lock.json
	@test -f $(VERSIONS_SCRIPT) || { echo "нет $(VERSIONS_SCRIPT): скрипт таблицы версий ещё не написан"; exit 1; }
	$(VENV)/bin/python $(VERSIONS_SCRIPT) $(ARGS)

# --- данные и валидация --------------------------------------------------------------------------------------------------

bank: $(VENV)/bin/python ## Собрать банк заданий в базе разработки
	cd backend && $(LOCAL_ENV) $(PY) -m app.modules.assessment.bank build $(ARGS)

bank-check: $(VENV)/bin/python ## Проверить банк заданий без записи
	cd backend && $(LOCAL_ENV) $(PY) -m app.modules.assessment.bank build --check-only $(ARGS)

seed: $(VENV)/bin/python ## Сид демо-данных в базе разработки
	cd backend && $(LOCAL_ENV) $(PY) -m app.seed all $(ARGS)

demo-reset: $(VENV)/bin/python ## Сброс демо: пересоздать сид от текущего времени сервиса
	cd backend && $(LOCAL_ENV) $(PY) -m app.seed all --reset $(ARGS)

eval-testing: $(VENV)/bin/python ## Отчёт валидации тестирования → docs/validation/testing
	cd backend && $(LOCAL_ENV) $(PY) -m app.eval.testing --seed 20261005 --n 4000 --out ../docs/validation/testing $(ARGS)

eval-matching: $(VENV)/bin/python ## Отчёт валидации подбора → docs/validation/matching (быстро: ARGS=--quick)
	cd backend && $(LOCAL_ENV) $(PY) -m app.eval.matching run --out ../docs/validation/matching $(ARGS)

eval-contact: $(VENV)/bin/python ## Отчёт валидации контакта → docs/validation/contact
	cd backend && $(LOCAL_ENV) $(PY) -m app.eval.contact --out ../docs/validation/contact $(ARGS)

eval: eval-testing eval-matching eval-contact ## Все три отчёта валидации

e2e: ## Сквозные тесты Playwright в контейнере (стенд должен быть поднят: make up)
	$(COMPOSE) --profile test run --rm e2e
