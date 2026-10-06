/**
 * Перехват запросов к API для проверок без бэкенда (план, раздел 5: «до сида пакеты интерфейса работают
 * на перехвате запросов Playwright»). Неописанный путь отвечает 404 `not_found` в общем формате ошибки.
 */
import type { Page, Route } from '@playwright/test'

export type MockMe = {
  id: string
  email: string
  role: 'candidate' | 'employer'
  is_demo: boolean
  server_now: string
}

export const SERVER_NOW = '2026-10-05T09:00:00Z'

export const CANDIDATE: MockMe = {
  id: '11111111-1111-4111-8111-111111111111',
  email: 'anna@example.com',
  role: 'candidate',
  is_demo: false,
  server_now: SERVER_NOW,
}

export const EMPLOYER: MockMe = {
  id: '22222222-2222-4222-8222-222222222222',
  email: 'hr@example.com',
  role: 'employer',
  is_demo: false,
  server_now: SERVER_NOW,
}

export const CATALOG = {
  directions: [{ code: 'dev', title: 'Разработка' }],
  specializations: [
    { code: 'backend', title: 'Backend-разработка', title_short: 'Backend', direction_code: 'dev', available: true },
  ],
  grades: [
    { code: 'junior', title: 'Junior', order: 1, description: 'Решает типовые задачи с поддержкой', available: true },
    { code: 'middle', title: 'Middle', order: 2, description: 'Самостоятельно ведёт задачи', available: true },
    { code: 'senior', title: 'Senior', order: 3, description: 'Проектирует и отвечает за результат', available: true },
  ],
  skills: [{ code: 'python', title: 'Python', kind: 'language', aliases: ['py'] }],
  roles: [{ code: 'backend_dev', title: 'Backend-разработчик' }],
  available_categories: ['backend:junior', 'backend:middle', 'backend:senior'],
  limits: { salary_min: 30000, salary_max: 3000000, salary_max_ratio: 1.5, reregister_cooldown_days: 30 },
  features: { demo: true, vacancies: false, pulse: false, integrations: false },
}

export const LEGAL_PROCESSING = {
  doc: 'processing',
  version: '2026-10-01',
  title: 'Согласие на обработку персональных данных',
  text: '# 1. Что обрабатывается\n\nАдрес электронной почты, данные профиля, результаты тестов и история приглашений.\n\n# 2. Срок\n\nДо отзыва согласия. Отзыв удаляет аккаунт и все данные немедленно; резервных копий стенд не ведёт.',
  sha256: '0'.repeat(64),
}

type Handler = (route: Route) => Promise<void> | void
export type MockOptions = {
  /** Текущий пользователь; null — гость (401). */
  me?: MockMe | null
  /** Свои обработчики: ключ — «МЕТОД /путь без /api/v1». */
  handlers?: Record<string, Handler>
}

export function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

export function apiError(route: Route, status: number, code: string, extra: Record<string, unknown> = {}) {
  return json(route, { code, message: code, ...extra }, status)
}

/** Подключить перехват: сессия, каталог, документ согласия и данные шапки кабинета — по умолчанию. */
export async function mockApi(page: Page, options: MockOptions = {}): Promise<void> {
  const me = options.me ?? null
  const defaults: Record<string, Handler> = {
    'GET /auth/me': (route) => (me ? json(route, me) : apiError(route, 401, 'not_authenticated')),
    'GET /catalog': (route) => json(route, CATALOG),
    'GET /legal/processing': (route) => json(route, LEGAL_PROCESSING),
    'GET /candidate/profile': (route) =>
      json(route, {
        public_code: 'К-10042',
        email: CANDIDATE.email,
        last_name: 'Петрова',
        first_name: 'Анна',
        middle_name: null,
        city: 'Казань',
        phone: null,
        telegram: null,
        link: null,
        experience_years: 4,
        roles: [],
        about: null,
      }),
    'GET /assessment/state': (route) =>
      json(route, {
        survey_completed: true,
        direction: { code: 'dev', title: 'Разработка' },
        specialization: { code: 'backend', title: 'Backend-разработка' },
        main_language: { code: 'python', title: 'Python' },
        claimed_grade: { code: 'middle', title: 'Middle' },
        claim_locked: true,
        category: {
          code: 'backend:middle',
          title: 'Backend · Middle',
          specialization: { code: 'backend', title: 'Backend' },
          grade: { code: 'middle', title: 'Middle' },
          assigned_at: '2026-09-20T10:00:00Z',
          change_available_at: '2026-12-19T10:00:00Z',
          level_session_id: 'session-1',
        },
        level: null,
        active_session: null,
        last_session: null,
        next_actions: [],
      }),
    'GET /candidate/invitations/summary': (route) =>
      json(route, {
        awaiting: 3,
        accepted: 1,
        archived: 2,
        outcome_prompts: 0,
        strikes: { count: 0, limit: 2 },
        visibility: { state: 'visible', pause_reason: null, auto_paused_until: null },
      }),
    'GET /employer/company': (route) =>
      json(route, {
        name: 'Орбита',
        sphere: 'Финтех',
        description: 'Платёжный сервис',
        site: 'https://example.com',
        city: 'Москва',
        contact_method: { kind: 'email', value: 'hr@example.com' },
        trust_level: 'basic',
        trust_label: 'Новая компания',
        on_platform_since: '2026-09-01T00:00:00Z',
        is_complete: true,
      }),
    'GET /employer/needs': (route) => json(route, []),
    'GET /employer/invitations/quota': (route) =>
      json(route, { used: 3, limit: 10, next_release_at: null, daily_used: 1, daily_limit: 20, frozen: false }),
  }
  const handlers = { ...defaults, ...options.handlers }

  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname.replace(/^\/api\/v1/, '')
    const handler = handlers[`${request.method()} ${path}`]
    if (handler) return handler(route)
    return apiError(route, 404, 'not_found')
  })
}
