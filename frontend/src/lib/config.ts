/**
 * Настройки стенда, известные интерфейсу до первого запроса к API.
 * Источник — /app-config.js (в контейнере web его отдаёт nginx из переменных APP_NAME и MAILPIT_PUBLIC_URL, Арх. 13.3);
 * в разработке значения можно переопределить переменными VITE_APP_NAME и VITE_MAILPIT_PUBLIC_URL.
 */
type RuntimeConfig = { appName?: string; mailpitUrl?: string }

declare global {
  interface Window {
    __APP_CONFIG__?: RuntimeConfig
  }
}

const runtime: RuntimeConfig = (typeof window !== 'undefined' && window.__APP_CONFIG__) || {}

function pick(...values: (string | undefined)[]): string | undefined {
  return values.find((value) => typeof value === 'string')
}

/** Название продукта в интерфейсе (`APP_NAME`). */
export const APP_NAME: string = pick(import.meta.env.VITE_APP_NAME, runtime.appName) || 'ФСП.Подбор'

/** Ссылка на почтовый ящик стенда (`MAILPIT_PUBLIC_URL`); пустая строка — подсказки о ящике нет (Арх. 11.8, P3). */
export const MAILPIT_PUBLIC_URL: string = pick(import.meta.env.VITE_MAILPIT_PUBLIC_URL, runtime.mailpitUrl) ?? '/mail/'

/** Префикс REST API: один origin с интерфейсом (Арх. 9.1). */
export const API_PREFIX = '/api/v1'

/** Заголовок документа: «{экран} · {APP_NAME}» (E §7). */
export function pageTitle(screen?: string | null): string {
  return screen ? `${screen} · ${APP_NAME}` : APP_NAME
}
