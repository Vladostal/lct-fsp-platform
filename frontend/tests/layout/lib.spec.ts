import { expect, test } from '@playwright/test'
import { CATALOG, DECLARED_STATE, mockApi } from '../utils/api-mock'

/**
 * Проверки чистых функций каркаса (`lib/format`, `lib/guards`, `lib/api`) в настоящем браузере: модули
 * загружаются с dev-сервера Vite как исходники. На собранном стенде (E2E_BASE_URL, BASE_URL) исходников нет —
 * там эти проверки пропускаются.
 */
const onStand = Boolean(process.env.E2E_BASE_URL || process.env.BASE_URL)

// Типы модулей нужны только компилятору: в браузере модуль загружается по адресу dev-сервера.
type FormatModule = typeof import('../../src/lib/format')
type GuardsModule = typeof import('../../src/lib/guards')
type ApiModule = typeof import('../../src/lib/api')
type ErrorsModule = typeof import('../../src/content/errors')
type CategoryModule = typeof import('../../src/lib/category')

const SRC = {
  format: '/src/lib/format.ts',
  guards: '/src/lib/guards.ts',
  api: '/src/lib/api.ts',
  errors: '/src/content/errors.ts',
  category: '/src/lib/category.ts',
} as const

test.describe('функции lib', () => {
  test.skip(onStand, 'исходные модули доступны только на dev-сервере')

  test.beforeEach(async ({ page }) => {
    await mockApi(page)
    await page.goto('/login')
  })

  test('format: деньги, вилка, склонения, перечисления, сроки', async ({ page }) => {
    const result = await page.evaluate(async (src) => {
      const f: FormatModule = await import(/* @vite-ignore */ src.format)
      const now = new Date('2026-10-05T12:00:00Z')
      const nbsp = (text: string) => text.replace(/ /g, ' ')
      return {
        money: nbsp(f.formatMoney(180000)),
        range: nbsp(f.formatSalaryRange(180000, 240000)),
        rangeRaw: f.formatSalaryRange(180000, 240000),
        compact: nbsp(f.formatSalaryRange(180000, 240000, { compact: true })),
        compactOdd: nbsp(f.formatSalaryRange(180500, 240000, { compact: true })),
        aria: nbsp(f.salaryRangeAriaLabel(180000, 240000)),
        plurals: [1, 2, 5, 11, 21, 22, 25].map((n) => nbsp(f.pluralize(n, f.PLURALS.day))),
        list: [
          f.formatList(['A']),
          f.formatList(['A', 'B']),
          f.formatList(['A', 'B', 'C']),
          nbsp(f.formatList(['A', 'B', 'C', 'D', 'E'])),
        ],
        sameYear: nbsp(f.formatDate('2026-10-12T09:00:00Z', now)),
        otherYear: nbsp(f.formatDate('2025-10-12T09:00:00Z', now)),
        days: nbsp(f.formatDeadline('2026-10-08T12:00:00Z', 'ответить', now)),
        hours: nbsp(f.formatRemaining('2026-10-06T10:00:00Z', now) ?? ''),
        minutes: nbsp(f.formatRemaining('2026-10-05T12:20:00Z', now) ?? ''),
        expired: nbsp(f.formatDeadline('2026-10-01T12:00:00Z', 'ответить', now)),
        timer: [f.formatTimer(125_000), f.formatTimer(3_725_000), f.formatTimer(-5)],
        duration: [45, 120, 7200].map((s) => nbsp(f.formatDuration(s))),
        title: [f.candidateTitle(null, 'К-10042'), f.candidateTitle('Анна Петрова', 'К-10042')],
      }
    }, SRC)
    expect(result.money).toBe('180 000 ₽')
    expect(result.range).toBe('180 000 – 240 000 ₽')
    // Пробелы внутри вилки неразрывные: она никогда не переносится (E §3.3).
    expect(result.rangeRaw).not.toContain(' ')
    expect(result.compact).toBe('180–240 тыс. ₽')
    expect(result.compactOdd).toBe('180 500 – 240 000 ₽')
    expect(result.aria).toBe('от 180 000 до 240 000 рублей в месяц')
    expect(result.plurals).toEqual(['1 день', '2 дня', '5 дней', '11 дней', '21 день', '22 дня', '25 дней'])
    expect(result.list).toEqual(['A', 'A и B', 'A, B и C', 'A, B, C и ещё 2'])
    expect(result.sameYear).toBe('12 окт.')
    expect(result.otherYear).toBe('12 окт. 2025')
    expect(result.days).toBe('ответить до 8 окт. · осталось 3 дня')
    expect(result.hours).toBe('22 часа')
    expect(result.minutes).toBe('20 минут')
    expect(result.expired).toBe('срок истёк 1 окт.')
    expect(result.timer).toEqual(['02:05', '1:02:05', '00:00'])
    expect(result.duration).toEqual(['45 с', '2 мин', '2 ч'])
    expect(result.title).toEqual(['Кандидат К-10042', 'Анна Петрова'])
  })

  test('guards: шаг мастера, первый экран, адрес возврата', async ({ page }) => {
    const result = await page.evaluate(async (src) => {
      const g: GuardsModule = await import(/* @vite-ignore */ src.guards)
      const noState = {
        category: null,
        last_session: null,
        survey_completed: false,
        claimed_grade: null,
        active_session: null,
      }
      const named = { first_name: 'Анна', last_name: 'Петрова' }
      const grade = { code: 'middle', title: 'Middle' }
      const done = { ...noState, last_session: { id: 's1' } } as never
      const passed = { ...noState, last_session: { id: 's1' }, survey_completed: true }
      const claimed = { ...passed, claimed_grade: grade } as never
      const switched = passed as never
      const active = { ...noState, survey_completed: true, claimed_grade: grade, active_session: { id: 's9' } } as never
      return {
        steps: [
          g.onboardingStep({ first_name: null, last_name: null }, noState),
          g.onboardingStep(named, noState),
          g.onboardingStep(named, { ...noState, survey_completed: true }),
          g.onboardingStep(named, { ...noState, survey_completed: true, claimed_grade: grade }),
          g.onboardingStep({ first_name: null, last_name: null }, done),
        ],
        home: [
          g.home({ role: 'candidate' }, { profile: named, state: noState }),
          g.home({ role: 'candidate' }, { profile: named, state: active }),
          g.home({ role: 'candidate' }, { profile: named, state: done }),
          g.home({ role: 'candidate' }, {}),
          g.home({ role: 'employer' }, { company: { is_complete: false }, needs: [] }),
          g.home({ role: 'employer' }, { company: { is_complete: true }, needs: [] }),
          g.home({ role: 'employer' }, { company: { is_complete: true }, needs: [{ id: 'n1' }] }),
        ],
        next: [
          g.safeNext('/candidate/profile?tab=1'),
          g.safeNext('//evil.example'),
          g.safeNext('https://evil.example'),
          g.safeNext('/a\\b'),
          g.safeNext('/a//b'),
          g.safeNext(''),
          g.safeNext(undefined),
        ],
        login: [g.loginHref('/candidate/invitations?tab=accepted'), g.loginHref('//evil'), g.loginHref('/')],
        candidate: [
          // шаг «опрос»: пройденный шаг доступен, будущий и кабинет — нет
          g.candidateGuard('/candidate/onboarding/profile', { profile: named, state: noState }),
          g.candidateGuard('/candidate/onboarding/grade', { profile: named, state: noState }),
          g.candidateGuard('/candidate/invitations', { profile: named, state: noState }),
          g.candidateGuard('/candidate/test/new', { profile: named, state: noState }),
          // идёт тест: шаги мастера ведут на экран теста, сам экран теста открыт
          g.candidateGuard('/candidate/onboarding/survey', { profile: named, state: active }),
          g.candidateGuard('/candidate/test/s9', { profile: named, state: active }),
          // мастер пройден: шаги 1–3 закрыты, брифинг повторной попытки открыт
          g.candidateGuard('/candidate/onboarding/profile', { profile: named, state: done }),
          g.candidateGuard('/candidate/test/new', { profile: named, state: done }),
          g.candidateGuard('/candidate/category', { profile: named, state: done }),
          // мастер пройден: опрос открыт (смена специализации), шаг «Грейд» — только пока грейд не заявлен
          g.candidateGuard('/candidate/onboarding/survey', { profile: named, state: done }),
          g.candidateGuard('/candidate/onboarding/grade', { profile: named, state: claimed }),
          g.candidateGuard('/candidate/onboarding/grade', { profile: named, state: switched }),
          // данных нет (эндпоинт недоступен): охрана шага не вмешивается
          g.candidateGuard('/candidate/invitations', {}),
        ],
        employer: [
          g.employerGuard('/employer/needs', { company: { is_complete: false } }),
          g.employerGuard('/employer/onboarding/company', { company: { is_complete: false } }),
          g.employerGuard('/employer/settings/account', { company: { is_complete: false } }),
          g.employerGuard('/employer/needs', { company: { is_complete: true } }),
        ],
      }
    }, SRC)
    expect(result.steps).toEqual(['profile', 'survey', 'grade', 'test', 'done'])
    expect(result.home).toEqual([
      '/candidate/onboarding/survey',
      '/candidate/test/s9',
      '/candidate',
      '/candidate',
      '/employer/onboarding/company',
      '/employer/needs/new',
      '/employer/needs',
    ])
    expect(result.next).toEqual(['/candidate/profile?tab=1', null, null, null, null, null, null])
    expect(result.login).toEqual(['/login?next=%2Fcandidate%2Finvitations%3Ftab%3Daccepted', '/login', '/login'])
    expect(result.candidate).toEqual([
      null,
      '/candidate/onboarding/survey',
      '/candidate/onboarding/survey',
      '/candidate/onboarding/survey',
      '/candidate/test/s9',
      null,
      '/candidate',
      null,
      null,
      null,
      '/candidate',
      null,
      null,
    ])
    expect(result.employer).toEqual(['/employer/onboarding/company', null, null, null])
  })

  test('заявленный грейд: мастер пройден, экран категории открыт, основание категории', async ({ page }) => {
    const result = await page.evaluate(
      async ({ src, state, catalog }) => {
        const g: GuardsModule = await import(/* @vite-ignore */ src.guards)
        const c: CategoryModule = await import(/* @vite-ignore */ src.category)
        const api: ApiModule = await import(/* @vite-ignore */ src.api)
        const named = { first_name: 'Анна', last_name: 'Петрова' }
        const ref = (code: string, basis?: 'test' | 'declared' | null) => ({ basis, specialization: { code } })
        return {
          // Заявленный грейд даёт категорию без теста: сессии нет, но мастер пройден.
          step: g.onboardingStep(named, state as never),
          home: g.home({ role: 'candidate' }, { profile: named, state: state as never }),
          guard: [
            g.candidateGuard('/candidate/category', { profile: named, state: state as never }),
            g.candidateGuard('/candidate/onboarding/grade', { profile: named, state: state as never }),
          ],
          // Общий текст — про опрос: тест написан, но сейчас недоступен. «Тест готовится» здесь было бы неправдой;
          // форма потребности для кода вне справочника берёт свой текст.
          unknown: api.errorText('specialization_unavailable'),
          hasTest: [
            c.hasTest(catalog, 'backend'),
            c.hasTest(catalog, 'frontend'),
            c.hasTest(catalog, 'unknown'),
            c.hasTest(null, 'frontend'),
          ],
          declared: [
            c.isDeclared(ref('frontend', 'declared'), catalog),
            c.isDeclared(ref('backend', 'test'), catalog),
            // `basis` главнее справочника: тест появился, а грейд ещё заявленный — и наоборот.
            c.isDeclared(ref('backend', 'declared'), catalog),
            c.isDeclared(ref('frontend', 'test'), catalog),
            // Ответ без `basis` (приглашения): основание берётся из справочника.
            c.isDeclared(ref('frontend'), catalog),
            c.isDeclared(ref('backend', null), catalog),
            c.isDeclared(ref('frontend'), null),
            c.isDeclared(null, catalog),
          ],
        }
      },
      { src: SRC, state: DECLARED_STATE, catalog: CATALOG },
    )
    expect(result.step).toBe('done')
    expect(result.home).toBe('/candidate')
    expect(result.guard).toEqual([null, '/candidate'])
    expect(result.unknown).toBe('Тест по этой специализации временно недоступен. Попробуйте позже')
    expect(result.hasTest).toEqual([true, false, true, true])
    expect(result.declared).toEqual([true, false, true, false, true, false, false, false])
  })

  test('api: тексты ошибок по коду, статусу и параметрам; словарь покрывает коды Арх. 9.12', async ({ page }) => {
    const result = await page.evaluate(async (src) => {
      const api: ApiModule = await import(/* @vite-ignore */ src.api)
      const errors: ErrorsModule = await import(/* @vite-ignore */ src.errors)
      const nbsp = (text: string) => text.replace(/ /g, ' ')
      const make = (status: number, code: string, extra: Record<string, unknown> = {}) =>
        api.toApiError({ code, message: 'сообщение сервера', ...extra }, new Response(null, { status }))
      return {
        byCode: api.errorText('invalid_credentials'),
        params: nbsp(api.errorText('salary_range_too_wide', { max_to: 270000 })),
        bare: api.errorText('salary_range_too_wide'),
        cooldown: nbsp(
          api.errorText('cooldown_active', { reason: 'grade_change', available_at: '2026-12-19T10:00:00Z' }),
        ),
        retry: nbsp(api.errorMessage(make(429, 'rate_limited', { params: { retry_after: 45 } }))),
        unknownCode: api.errorMessage(make(409, 'future_code')),
        unknown401: api.errorMessage(make(401, 'whatever')),
        own403: api.errorMessage(make(403, 'email_not_verified')),
        generic403: api.errorMessage(make(403, 'something_else')),
        notFound: api.errorMessage(make(404, 'not_found')),
        validation: nbsp(
          api.errorMessage(
            make(422, 'validation_error', {
              fields: [
                { name: 'email', code: 'format', message: 'x' },
                { name: 'password', code: 'short', message: 'y' },
              ],
            }),
          ),
        ),
        server: api.errorMessage(make(500, 'internal_error')),
        own503: api.errorMessage(make(503, 'bank_unavailable')),
        network: api.errorMessage(api.toApiError(new TypeError('Failed to fetch'))),
        notApi: api.errorMessage(new Error('boom')),
        isApi: [api.isApiError(make(400, 'x')), api.isApiError(new Error('x'))],
        codes: Object.keys(errors.ERROR_TEXTS),
        unfilled: Object.entries(errors.ERROR_TEXTS)
          .map(([code]) => [code, api.errorText(code)] as const)
          .filter(([, text]) => /\{\w+\}/.test(text) || text.trim() === '')
          .map(([code]) => code),
      }
    }, SRC)
    expect(result.byCode).toBe('Неверный e-mail или пароль')
    expect(result.params).toBe('Вилка слишком широкая: «до» — не больше 270 000 ₽')
    expect(result.bare).toBe('Вилка слишком широкая: уменьшите верхнюю границу')
    expect(result.cooldown).toBe('Сменить грейд можно с 19 дек.')
    expect(result.retry).toBe('Слишком часто. Повторите через 45 с')
    expect(result.unknownCode).toBe('сообщение сервера')
    expect(result.unknown401).toBe('Сессия истекла. Войдите снова')
    expect(result.own403).toBe('Адрес не подтверждён. Отправьте письмо ещё раз')
    expect(result.generic403).toBe('Нет доступа к этому разделу')
    expect(result.notFound).toBe('Здесь ничего нет: ссылка устарела или объект удалён')
    expect(result.validation).toBe('Исправьте 2 поля')
    expect(result.server).toBe('Не удалось загрузить данные. Проверьте соединение и повторите')
    expect(result.own503).toBe('Тест временно недоступен. Попробуйте позже')
    expect(result.network).toBe('Не удалось загрузить данные. Проверьте соединение и повторите')
    expect(result.notApi).toBe('Не получилось выполнить действие. Повторите попытку')
    expect(result.isApi).toEqual([true, false])
    // Без параметров ни один текст не показывает незаполненную подстановку (E §9.1, G17).
    expect(result.unfilled).toEqual([])
    // Все коды сводки Арх. 9.12 и общие коды Арх. 9.2 есть в словаре.
    for (const code of ARCH_ERROR_CODES) {
      expect(result.codes, `код ${code}`).toContain(code)
    }
  })
})

/** Коды ошибок модулей (Арх. 9.12) и общие коды (Арх. 9.2). */
const ARCH_ERROR_CODES = [
  // 9.2
  'not_authenticated',
  'forbidden',
  'not_found',
  'feature_disabled',
  'validation_error',
  'rate_limited',
  'internal_error',
  // identity
  'token_invalid',
  'token_expired',
  'invalid_credentials',
  'email_not_verified',
  'demo_account_readonly',
  'password_required',
  'current_password_invalid',
  // assessment
  'survey_required',
  'claim_required',
  'claim_locked',
  'survey_version_mismatch',
  'specialization_change_requires_confirm',
  'session_active',
  'cooldown_active',
  'item_already_answered',
  'session_finished',
  'session_expired',
  'specialization_unavailable',
  'grade_unavailable',
  'grade_not_allowed',
  'invalid_transition',
  'bank_unavailable',
  // pulse
  'assignment_closed',
  'pulse_task_limit',
  'assignment_expired',
  'skill_not_testable',
  // profile
  'resume_too_large',
  'resume_not_pdf',
  'resume_encrypted',
  'resume_too_many_pages',
  'resume_no_text',
  'resume_unreadable',
  'resume_timeout',
  'min_salary_not_on_ladder',
  'resume_rate_limited',
  'no_category',
  'profile_incomplete',
  'consent_version_outdated',
  'publication_consent_required',
  'not_disclosed',
  // fsp
  'fsp_link_exists',
  'fsp_consent_outdated',
  'fsp_consent_required',
  'fsp_too_many_attempts',
  'fsp_sync_too_frequent',
  'fsp_not_linked',
  'fsp_unavailable',
  // matching
  'company_profile_incomplete',
  'need_archived',
  'parent_mismatch',
  'different_need',
  'pin_limit',
  'candidate_not_in_need',
  'text_too_short',
  'text_too_long',
  'skill_unknown',
  'filter_invalid',
  'cursor_invalid',
  'shortlist_rate_limited',
  'card_open_limit',
  'bank_page_limit',
  // общие правила вилки
  'salary_order',
  'salary_out_of_bounds',
  'salary_range_too_wide',
  // contact
  'candidate_unavailable',
  'active_invitation_exists',
  'pair_cooldown',
  'conditions_mismatch',
  'revision_not_allowed',
  'invitation_not_actionable',
  'complaint_exists',
  'demo_sender_restricted',
  'sending_frozen',
  'format_not_accepted',
  'revision_below_condition',
  'disclose_invalid',
  'condition_invalid',
  'daily_limit_exceeded',
  // vacancies
  'vacancy_closed',
  'vacancy_status_invalid',
  'application_exists',
  'application_limit_exceeded',
  'application_not_actionable',
  'category_required',
  'invitation_pending',
  'interest_limit_exceeded',
  // integrations, demo
  'webhook_url_invalid',
  'sessions_in_progress',
] as const
