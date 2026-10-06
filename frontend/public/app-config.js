// Настройки стенда, которые интерфейс читает при запуске. В контейнере web этот адрес отдаёт nginx
// (infra/nginx/default.conf) со значениями APP_NAME и MAILPIT_PUBLIC_URL из окружения; этот файл — значения по умолчанию
// для dev-сервера Vite.
window.__APP_CONFIG__ = { appName: 'ФСП.Подбор', mailpitUrl: '/mail/' }
