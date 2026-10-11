# syntax=docker/dockerfile:1.7
#
# Сервис web (Арх. 2.1): сборка SPA на Node 24 LTS, раздача nginx.
#   docker compose build web        — контекст сборки ./frontend (так записано в compose.yml)
#
# Конфигурация nginx лежит вне образа: compose монтирует infra/nginx/default.conf как шаблон
# /etc/nginx/templates/default.conf.template, и официальный образ nginx подставляет в него переменные окружения
# при старте. Условные части (доверенный внешний прокси, базовая авторизация ящика /mail/) шаблоном не выразить,
# поэтому их готовит скрипт ниже: он пишет файлы в /etc/nginx/fsp/, а шаблон подключает их через include.

FROM node:24-alpine AS build
WORKDIR /app
# Сначала только манифесты: слой с зависимостями пересобирается лишь при изменении lock-файла.
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# Сборка без проверки типов: её выполняет отдельный шаг `npm run typecheck` в CI. Так недописанный экран соседнего
# пакета не роняет запуск стенда (план работ, раздел 3).
RUN npm run build


FROM nginx:1.29-alpine AS runtime

# openssl — для хеша пароля базовой авторизации ящика (apr1).
RUN apk add --no-cache openssl

# Значения по умолчанию; compose переопределяет их из .env (Арх. 13.3).
#   APP_NAME, MAILPIT_PUBLIC_URL — попадают в /app-config.js, который интерфейс читает при запуске;
#   API_UPSTREAM, MAILPIT_UPSTREAM — адреса сервисов compose;
#   NGINX_REAL_IP_FROM — адрес внешнего прокси с HTTPS (пусто — прокси нет);
#   MAIL_UI_USER, MAIL_UI_PASSWORD — базовая авторизация ящика /mail/ (пусто — ящик открыт);
#   NGINX_ENTRYPOINT_LOCAL_RESOLVERS — образ nginx кладёт DNS-серверы контейнера в NGINX_LOCAL_RESOLVERS.
ENV APP_NAME="ФСП.Подбор" \
    MAILPIT_PUBLIC_URL="/mail/" \
    API_UPSTREAM="api:8000" \
    MAILPIT_UPSTREAM="mailpit:8025" \
    NGINX_REAL_IP_FROM="" \
    MAIL_UI_USER="" \
    MAIL_UI_PASSWORD="" \
    NGINX_ENTRYPOINT_LOCAL_RESOLVERS="1"

COPY --from=build /app/dist /usr/share/nginx/html

# Заголовки безопасности для страниц SPA. Отдельным файлом: add_header в location отменяет заголовки уровня
# server, поэтому набор подключается в каждом location явно.
COPY <<'CONF' /etc/nginx/fsp/security-headers.conf
add_header X-Content-Type-Options "nosniff" always;
add_header X-Frame-Options "DENY" always;
add_header Referrer-Policy "same-origin" always;
add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;
add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'" always;
CONF

# Скрипт старта: условные части конфигурации и /app-config.js. Выполняется точкой входа образа nginx до запуска
# сервера (каталог /docker-entrypoint.d).
COPY --chmod=755 <<'SH' /docker-entrypoint.d/15-fsp-conditional.sh
#!/bin/sh
set -eu

DIR=/etc/nginx/fsp
mkdir -p "$DIR"
log() { echo "15-fsp-conditional.sh: $*"; }

# --- 1. Адрес клиента за внешним прокси (Арх. 10.1) -----------------------------------------------------------------
# По умолчанию X-Real-IP — адрес соединения. Если перед web стоит прокси с HTTPS, его адрес задаётся в
# NGINX_REAL_IP_FROM: тогда nginx берёт адрес клиента из X-Forwarded-For этого прокси — и только от него.
: > "$DIR/real-ip.conf"
if [ -n "${NGINX_REAL_IP_FROM:-}" ]; then
  for addr in $(printf '%s' "$NGINX_REAL_IP_FROM" | tr ',;' '  '); do
    # Только адрес или подсеть: значение попадает в конфигурацию, посторонние символы недопустимы.
    if ! printf '%s' "$addr" | grep -Eq '^[0-9A-Fa-f:.]+(/[0-9]{1,3})?$'; then
      log "ошибка: NGINX_REAL_IP_FROM содержит недопустимое значение «$addr» (нужен IP-адрес или подсеть CIDR)"
      exit 1
    fi
    echo "set_real_ip_from $addr;" >> "$DIR/real-ip.conf"
  done
  echo "real_ip_header X-Forwarded-For;" >> "$DIR/real-ip.conf"
  log "адрес клиента берётся из X-Forwarded-For от доверенного прокси: $NGINX_REAL_IP_FROM"
fi

# --- 2. Базовая авторизация почтового ящика стенда (Арх. 10.2) ------------------------------------------------------
# На публичном стенде ящик закрыт: иначе любой посетитель читал бы чужие ссылки подтверждения.
: > "$DIR/mail-auth.conf"
rm -f "$DIR/mail.htpasswd"
if [ -n "${MAIL_UI_USER:-}" ] && [ -n "${MAIL_UI_PASSWORD:-}" ]; then
  if printf '%s' "$MAIL_UI_USER" | grep -q '[:[:space:]]'; then
    log "ошибка: MAIL_UI_USER не должен содержать двоеточие и пробелы"
    exit 1
  fi
  hash=$(printf '%s' "$MAIL_UI_PASSWORD" | openssl passwd -apr1 -stdin)
  printf '%s:%s\n' "$MAIL_UI_USER" "$hash" > "$DIR/mail.htpasswd"
  # Файл читают рабочие процессы nginx (пользователь nginx), остальным он недоступен.
  chown root:nginx "$DIR/mail.htpasswd"
  chmod 640 "$DIR/mail.htpasswd"
  {
    echo 'auth_basic "Mail";'
    echo "auth_basic_user_file $DIR/mail.htpasswd;"
  } > "$DIR/mail-auth.conf"
  log "ящик /mail/ закрыт базовой авторизацией"
elif [ -n "${MAIL_UI_USER:-}" ] || [ -n "${MAIL_UI_PASSWORD:-}" ]; then
  # Задана только одна из двух переменных — это ошибка настройки. Ящик закрывается целиком, а не остаётся открытым.
  echo 'return 403;' > "$DIR/mail-auth.conf"
  log "внимание: задана только одна из переменных MAIL_UI_USER и MAIL_UI_PASSWORD — ящик /mail/ закрыт (403)"
fi

# --- 3. Настройки интерфейса ----------------------------------------------------------------------------------------
# /app-config.js читается страницей до запуска приложения. Значения экранируются как строки JSON.
json_string() {
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/</\\u003c/g' | tr -d '\r\n'
}
cat > /usr/share/nginx/html/app-config.js <<CONFIG
window.__APP_CONFIG__ = { "appName": "$(json_string "${APP_NAME:-}")", "mailpitUrl": "$(json_string "${MAILPIT_PUBLIC_URL-/mail/}")" }
CONFIG
SH

EXPOSE 80

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
  CMD wget -q -O /dev/null http://127.0.0.1/healthz || exit 1
