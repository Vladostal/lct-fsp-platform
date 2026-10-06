/**
 * Настройка сгенерированного клиента и разбор ошибок API (Арх. 9.2, 11.5).
 *
 * Правила ветвления: 401, 403, 404 — по HTTP-статусу, остальное — по `code`; текст — из content/errors.ts,
 * при отсутствии кода в словаре — `message` сервера, при отсутствии и его — общий текст.
 *
 * Все ошибки, которые бросает сгенерированный клиент (`throwOnError: true`, в том числе хуки TanStack Query),
 * проходят через перехватчик и становятся экземплярами класса `ApiError` — у экрана один способ их читать.
 */
import type { FieldValues, Path, UseFormSetError } from 'react-hook-form'
import type { ApiError as ApiErrorBody } from '@/client'
import { client } from '@/client/client.gen'
import {
  COOLDOWN_ERROR_TEXTS,
  ERROR_TEXTS,
  type ErrorTemplate,
  FALLBACK_ERROR_TEXT,
  STATUS_ERROR_TEXTS,
} from '@/content/errors'
import { API_PREFIX } from '@/lib/config'
import { formatDate, formatDateTime, formatDuration, formatNumber, PLURALS, pluralize } from '@/lib/format'

export type ErrorParams = Record<string, string | number>
export type ApiFieldError = { name: string; code: string; message: string }

/** Ошибка запроса к API. `status = 0` — сеть недоступна или ответ не получен. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly params: ErrorParams
  readonly fields: ApiFieldError[]
  /** `message` из тела ответа, если сервер его прислал. */
  readonly serverMessage: string | null

  constructor(init: {
    status: number
    code: string
    message?: string | null
    params?: ErrorParams
    fields?: ApiFieldError[]
  }) {
    super(init.message || init.code)
    this.name = 'ApiError'
    this.status = init.status
    this.code = init.code
    this.params = init.params ?? {}
    this.fields = init.fields ?? []
    this.serverMessage = init.message || null
  }

  /** Сеть или сервер недоступны: показывается ErrorState с «Повторить». */
  get isUnavailable(): boolean {
    return this.status === 0 || this.status >= 500
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError
}

/** Ошибка API с заданным HTTP-статусом. */
export function hasStatus(error: unknown, status: number): error is ApiError {
  return isApiError(error) && error.status === status
}

/** Ошибка API с одним из заданных кодов. */
export function hasCode(error: unknown, ...codes: string[]): error is ApiError {
  return isApiError(error) && codes.includes(error.code)
}

const STATUS_CODES: Record<number, string> = {
  401: 'not_authenticated',
  403: 'forbidden',
  404: 'not_found',
  422: 'validation_error',
  429: 'rate_limited',
}

function isErrorBody(value: unknown): value is ApiErrorBody {
  return typeof value === 'object' && value !== null && typeof (value as { code?: unknown }).code === 'string'
}

/** Привести то, что бросил клиент (тело ответа, текст, исключение fetch), к `ApiError`. */
export function toApiError(error: unknown, response?: Response): ApiError {
  if (isApiError(error)) return error
  const status = response?.status ?? 0
  if (isErrorBody(error)) {
    return new ApiError({
      status,
      code: error.code,
      message: typeof error.message === 'string' ? error.message : null,
      params: (error.params as ErrorParams | undefined) ?? {},
      fields: (error.fields as ApiFieldError[] | undefined) ?? [],
    })
  }
  if (status === 0) return new ApiError({ status: 0, code: 'network_error' })
  return new ApiError({ status, code: STATUS_CODES[status] ?? (status >= 500 ? 'internal_error' : 'unknown_error') })
}

// ───────────────────────── Тексты ошибок ─────────────────────────

const ISO_DATE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/

/** Формат параметра по его имени: длительности, даты и числа выглядят так же, как в остальном интерфейсе. */
function formatParam(name: string, value: string | number): string {
  if (name === 'retry_after' && typeof value === 'number') return formatDuration(value)
  if (typeof value === 'number') return formatNumber(value)
  if (ISO_DATE.test(value)) return name === 'next_release_at' ? formatDateTime(value) : formatDate(value)
  return value
}

/** Подставить параметры; null — если хотя бы одного параметра нет. */
function fill(template: string, params: ErrorParams): string | null {
  let missing = false
  const text = template.replace(/\{(\w+)\}/g, (_, name: string) => {
    const value = params[name]
    if (value === undefined || value === null) {
      missing = true
      return ''
    }
    return formatParam(name, value)
  })
  return missing ? null : text
}

function render(template: ErrorTemplate, params: ErrorParams): string {
  if (typeof template === 'string') return fill(template, params) ?? FALLBACK_ERROR_TEXT
  return fill(template.text, params) ?? template.bare
}

function lookup(code: string, params: ErrorParams): string | null {
  if (code === 'cooldown_active' && typeof params.reason === 'string') {
    const byReason = COOLDOWN_ERROR_TEXTS[params.reason]
    if (byReason) return render(byReason, params)
  }
  const template = ERROR_TEXTS[code]
  return template ? render(template, params) : null
}

/**
 * Текст ошибки по коду (словарь content/errors.ts) с подстановкой параметров.
 * Кода в словаре нет — общий текст «Не получилось выполнить действие…».
 */
export function errorText(code: string, params: ErrorParams = {}): string {
  return lookup(code, params) ?? FALLBACK_ERROR_TEXT
}

/**
 * Текст для показа пользователю по любой пойманной ошибке (E §6.4):
 * сеть и 5xx — «Не удалось загрузить данные…»; 422 с полями — «Исправьте {n} полей»; код из словаря;
 * 401, 403, 404, 429 — текст статуса; иначе `message` сервера или общий текст.
 */
export function errorMessage(error: unknown): string {
  if (!isApiError(error)) return FALLBACK_ERROR_TEXT
  const own = lookup(error.code, error.params)
  if (error.isUnavailable) {
    // 503 с собственным кодом (банк заданий, ФСП ID) объясняется точнее общего текста.
    return own && error.code !== 'internal_error' ? own : STATUS_ERROR_TEXTS.network
  }
  if (error.code === 'validation_error' && error.fields.length > 0) {
    return `Исправьте ${pluralize(error.fields.length, PLURALS.field)}`
  }
  if (own) return own
  if (error.status === 401) return STATUS_ERROR_TEXTS.unauthorized
  if (error.status === 403) return STATUS_ERROR_TEXTS.forbidden
  if (error.status === 404) return STATUS_ERROR_TEXTS.notFound
  if (error.status === 429) return render(STATUS_ERROR_TEXTS.rateLimited, error.params)
  return error.serverMessage ?? FALLBACK_ERROR_TEXT
}

/**
 * Привязать ошибки полей (`fields[]`) к полям react-hook-form по `name` (Арх. 11.5).
 * Возвращает число привязанных полей; фокус встаёт на первое из них (E §7).
 * `known` — имена полей формы: ошибки остальных полей остаются для общей плашки.
 */
export function applyFieldErrors<T extends FieldValues>(
  error: unknown,
  setError: UseFormSetError<T>,
  known?: readonly Path<T>[],
): number {
  if (!isApiError(error)) return 0
  let applied = 0
  for (const field of error.fields) {
    const name = field.name as Path<T>
    if (known && !known.includes(name)) continue
    setError(name, { type: field.code || 'server', message: field.message }, { shouldFocus: applied === 0 })
    applied += 1
  }
  return applied
}

// ───────────────────────── Клиент ─────────────────────────

type UnauthorizedHandler = (error: ApiError, request: Request | undefined) => void

let unauthorizedHandler: UnauthorizedHandler | null = null

/** Что делать при 401 на запрос кабинета (Арх. 11.3): подключается один раз в main.tsx. */
export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  unauthorizedHandler = handler
}

let configured = false

/** Настроить сгенерированный клиент: один origin, cookie сессии, единый разбор ошибок. Идемпотентно. */
export function setupApiClient(): void {
  if (configured) return
  configured = true
  client.setConfig({ baseUrl: '', credentials: 'same-origin' })
  client.interceptors.error.use((error, response, request) => {
    const apiError = toApiError(error, response)
    if (apiError.status === 401) unauthorizedHandler?.(apiError, request)
    return apiError
  })
}

setupApiClient()

export type ApiRequestOptions = {
  query?: Record<string, string | number | boolean | null | undefined | readonly (string | number)[]>
  body?: unknown
  headers?: Record<string, string>
  signal?: AbortSignal
}

type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

async function request<T>(method: Method, path: string, options: ApiRequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { ...options.headers }
  if (options.body !== undefined && !(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'
  }
  const result = await client.request({
    method,
    url: `${API_PREFIX}${path}`,
    query: options.query,
    body: options.body,
    headers,
    signal: options.signal,
    throwOnError: true,
  })
  return result.data as T
}

/**
 * Тонкая обёртка над сгенерированным клиентом для запросов каркаса (сессия, каталог, шапка кабинета) и для
 * эндпоинтов, которых ещё нет в `src/client`. Путь — без префикса `/api/v1`. Ошибка — всегда `ApiError`.
 * Экраны доменов используют функции и хуки из `src/client`.
 */
export const api = {
  get: <T>(path: string, options?: Omit<ApiRequestOptions, 'body'>) => request<T>('GET', path, options),
  post: <T = void>(path: string, body?: unknown, options?: Omit<ApiRequestOptions, 'body'>) =>
    request<T>('POST', path, { ...options, body }),
  put: <T = void>(path: string, body?: unknown, options?: Omit<ApiRequestOptions, 'body'>) =>
    request<T>('PUT', path, { ...options, body }),
  patch: <T = void>(path: string, body?: unknown, options?: Omit<ApiRequestOptions, 'body'>) =>
    request<T>('PATCH', path, { ...options, body }),
  delete: <T = void>(path: string, options?: Omit<ApiRequestOptions, 'body'>) => request<T>('DELETE', path, options),
}
