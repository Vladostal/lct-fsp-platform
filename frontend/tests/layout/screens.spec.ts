import { expect, type Page, type Route, test } from '@playwright/test'
import {
  apiError,
  CANDIDATE,
  DECLARED_CATEGORY,
  DECLARED_CONTRIBUTIONS,
  DECLARED_STATE,
  EMPLOYER,
  json,
  type MockOptions,
  mockApi,
} from '../utils/api-mock'
import { expectCleanLayout } from '../utils/layout'
import { STRESS } from '../utils/stress'
import { VIEWPORTS } from '../utils/viewports'

/**
 * Экраны каркаса на перехвате запросов (бэкенд не нужен): лендинг, вход и регистрация (P1–P5a), аккаунт (C14),
 * каркасы кабинета, мастера и теста, 404. На трёх ширинах: нет горизонтальной прокрутки, текст не накладывается
 * и не обрезается, одна основная кнопка, axe без нарушений; на 375 — область нажатия не меньше 44 px.
 */

type Screen = {
  name: string
  path: string
  mock?: MockOptions
  /** Заголовок h1, по которому понятно, что экран загрузился. */
  heading: string | RegExp
  /** Действия перед проверкой (открыть диалог, вызвать ошибку). */
  prepare?: (page: Page) => Promise<void>
}

/** Идущая сессия теста с одним заданием: заголовок экрана C5 — условие текущего задания. */
const TEST_PROMPT = 'Что напечатает программа? Ответ — целое число.'
const TEST_SESSION: MockOptions['handlers'] = {
  'GET /assessment/sessions/session-1': (route) =>
    json(route, {
      id: 'session-1',
      status: 'in_progress',
      target: {
        code: 'backend:middle',
        title: 'Backend · Middle',
        specialization: { code: 'backend', title: 'Backend-разработка' },
        grade: { code: 'middle', title: 'Middle' },
      },
      expires_at: new Date(Date.now() + 30 * 60_000).toISOString(),
      server_now: new Date().toISOString(),
      progress: { answered: 3, min_total: 14, max_total: 26 },
      item: {
        id: 'item-4',
        kind: 'numeric_input',
        skill_label: 'Чтение кода и поиск ошибок',
        prompt: TEST_PROMPT,
        code: {
          language: 'python',
          text: 'total = 0\nfor j in range(1, 7):\n    if j > 3:\n        total += j * 3\nprint(total)',
        },
        tables: null,
        options: null,
        blocks: null,
        input: { placeholder: 'целое число', unit: null, max_length: 8 },
      },
    }),
}

/** Кандидат на шаге «Опрос»: мастер показывает степпер. */
const WIZARD_STATE: MockOptions['handlers'] = {
  'GET /assessment/state': (route) =>
    json(route, {
      survey_completed: false,
      direction: null,
      specialization: null,
      main_language: null,
      claimed_grade: null,
      claim_locked: false,
      category: null,
      level: null,
      active_session: null,
      last_session: null,
      next_actions: [],
    }),
}

/** Кандидат с заявленным грейдом: теста по специализации нет, профиль ещё не опубликован. */
const DECLARED_CANDIDATE: MockOptions['handlers'] = {
  'GET /assessment/state': (route) => json(route, DECLARED_STATE),
  'GET /assessment/history': (route) => json(route, []),
  'GET /assessment/survey': (route) => json(route, { version: 'v1', questions: [], answers: {} }),
  'GET /candidate/evidence': (route) =>
    json(route, { strength: { label: 'medium', contributions: DECLARED_CONTRIBUTIONS }, skills: [] }),
  'GET /candidate/consents': (route) =>
    json(route, {
      processing: { current_version: '2026-10-01', granted: true, granted_at: '2026-10-05T09:00:00Z' },
      publication: { current_version: '2026-10-01', granted: false, granted_at: null },
      fsp_data: null,
      visibility: { state: 'unpublished', pause_reason: null, auto_paused_until: null },
    }),
}

/** Карточка кандидата с заявленным грейдом глазами работодателя: `level` отсутствует. */
const DECLARED_CARD_ID = '33333333-3333-4333-8333-333333333333'
const DECLARED_CARD: MockOptions['handlers'] = {
  [`GET /employer/candidates/${DECLARED_CARD_ID}`]: (route) =>
    json(route, {
      candidate_id: DECLARED_CARD_ID,
      public_code: 'К-20417',
      display_name: null,
      category: DECLARED_CATEGORY,
      level: null,
      strength: { label: 'medium', contributions: DECLARED_CONTRIBUTIONS },
      skills: [
        { skill: { code: 'react', title: 'React' }, kind: 'declared', kind_label: 'заявлено кандидатом', detail: null },
      ],
      custom_skills: [],
      declared: { city: 'Казань', experience_years: 3, roles: [], about: null },
      fsp: { mode: 'none', neutral_text: 'Достижений ФСП нет или кандидат их не открыл.' },
      work_formats: ['remote'],
      relocation_ready: false,
      available: true,
      disclosed: false,
      is_demo: false,
      match: null,
      pinned: null,
    }),
  'GET /employer/invitations/pair-states': (route) => json(route, { items: [] }),
}

const SCREENS: Screen[] = [
  { name: 'P1 лендинг', path: '/', heading: /Платформа ИТ-специалистов, проверенных ФСП/ },
  { name: 'P2 регистрация', path: '/signup?role=employer', heading: 'Регистрация' },
  {
    name: 'P2 регистрация: ошибки полей',
    path: '/signup',
    heading: 'Регистрация',
    prepare: async (page) => {
      await page.getByLabel('E-mail').fill('не-адрес')
      await page.locator('input[name="password"]').fill('123')
      await page.getByRole('checkbox', { name: /Согласен\(на\) на обработку/ }).click()
      await page.getByRole('checkbox', { name: /Мне исполнилось 18 лет/ }).click()
      await page.getByRole('button', { name: 'Зарегистрироваться' }).click()
      await expect(page.getByText('Пароль короче 8 знаков')).toBeVisible()
    },
  },
  {
    name: 'P3 проверьте почту: длинный адрес',
    path: `/signup/check-email?email=${encodeURIComponent(STRESS.email)}`,
    heading: 'Проверьте почту',
  },
  {
    name: 'P4 ссылка недействительна',
    path: '/verify-email?token=used',
    mock: { handlers: { 'POST /auth/verify-email': (route) => apiError(route, 400, 'token_invalid') } },
    heading: 'Ссылка недействительна или уже использована',
  },
  {
    name: 'P4 ссылка устарела',
    path: '/verify-email?token=old',
    mock: { handlers: { 'POST /auth/verify-email': (route) => apiError(route, 400, 'token_expired') } },
    heading: 'Ссылка устарела',
  },
  {
    name: 'P4 нужен пароль (другой браузер)',
    path: '/verify-email?token=other-browser',
    mock: { handlers: { 'POST /auth/verify-email': (route) => apiError(route, 409, 'password_required') } },
    heading: 'Подтвердите, что это вы',
  },
  { name: 'P5 вход', path: '/login?next=%2Fcandidate%2Fprofile', heading: 'Вход' },
  {
    name: 'P5 вход: неверный пароль',
    path: '/login',
    mock: { handlers: { 'POST /auth/login': (route) => apiError(route, 401, 'invalid_credentials') } },
    heading: 'Вход',
    prepare: async (page) => {
      await page.getByLabel('E-mail').fill('anna@example.com')
      await page.locator('input[name="password"]').fill('wrong-password')
      await page.getByRole('button', { name: 'Войти' }).click()
      await expect(page.getByText('Неверный e-mail или пароль')).toBeVisible()
    },
  },
  {
    name: 'P5 вход: адрес не подтверждён',
    path: '/login',
    mock: { handlers: { 'POST /auth/login': (route) => apiError(route, 403, 'email_not_verified') } },
    heading: 'Вход',
    prepare: async (page) => {
      await page.getByLabel('E-mail').fill('anna@example.com')
      await page.locator('input[name="password"]').fill('correct-password')
      await page.getByRole('button', { name: 'Войти' }).click()
      await expect(page.getByRole('button', { name: 'Отправить письмо ещё раз' })).toBeVisible()
    },
  },
  { name: 'P5a сброс пароля', path: '/password/forgot', heading: 'Сброс пароля' },
  { name: 'P5a новый пароль', path: '/password/reset?token=abc', heading: 'Новый пароль' },
  { name: 'P5a ссылка без токена', path: '/password/reset', heading: 'Ссылка недействительна или устарела' },
  { name: 'P8 документ', path: '/legal/processing', heading: 'Согласие на обработку персональных данных' },
  { name: '404 для гостя', path: '/net-takoy-stranicy', heading: 'Здесь ничего нет' },
  { name: 'C7 каркас кабинета кандидата', path: '/candidate', mock: { me: CANDIDATE }, heading: 'Обзор' },
  { name: 'C14 аккаунт', path: '/candidate/settings/account', mock: { me: CANDIDATE }, heading: 'Аккаунт' },
  {
    name: 'C14 аккаунт: диалог удаления',
    path: '/candidate/settings/account',
    mock: { me: CANDIDATE },
    heading: 'Аккаунт',
    prepare: async (page) => {
      await page.getByRole('button', { name: 'Отозвать согласие и удалить данные' }).click()
      const dialog = page.getByRole('alertdialog', { name: 'Удалить аккаунт и все данные?' })
      await expect(dialog).toBeVisible()
      // Последствие названо числом до нажатия (Арх. 11.7, п. 4).
      await expect(dialog.getByText(/через 30\sдней/)).toBeVisible()
    },
  },
  {
    name: 'C14 аккаунт демо: действия неактивны',
    path: '/candidate/settings/account',
    mock: { me: { ...CANDIDATE, is_demo: true, email: 'anna@demo.test' } },
    heading: 'Аккаунт',
    prepare: async (page) => {
      await expect(page.getByRole('button', { name: 'Отозвать согласие и удалить данные' })).toBeDisabled()
      await expect(page.getByRole('button', { name: 'Сменить пароль' })).toBeDisabled()
    },
  },
  { name: '404 в кабинете', path: '/candidate/net-takoy', mock: { me: CANDIDATE }, heading: 'Здесь ничего нет' },
  {
    name: 'C2 каркас мастера со степпером',
    path: '/candidate/onboarding/survey',
    mock: { me: CANDIDATE, handlers: WIZARD_STATE },
    heading: 'Направление и специализация',
  },
  {
    name: 'C5 каркас теста',
    path: '/candidate/test/session-1',
    mock: { me: CANDIDATE, handlers: TEST_SESSION },
    heading: TEST_PROMPT,
  },
  {
    name: 'C10 заявленный грейд: пометка, форма смены грейда, публикация',
    path: '/candidate/category',
    mock: { me: CANDIDATE, handlers: DECLARED_CANDIDATE },
    heading: 'Категория и тесты',
    prepare: async (page) => {
      // Грейд не выдаётся за подтверждённый: пометка «заявлен», шкалы уровня нет.
      await expect(page.locator('[data-slot="category-chip-declared"]').first()).toContainText('заявлен')
      await expect(page.getByText(/Грейд заявлен .* · тест готовится/)).toBeVisible()
      await expect(page.locator('[data-slot="level-scale"]')).toHaveCount(0)
      // Первая смена заявленного грейда свободна; кнопка активна после выбора другого грейда.
      const change = page.getByRole('button', { name: 'Сменить заявленный грейд' })
      await expect(change).toBeDisabled()
      await page.getByRole('radio', { name: 'Senior' }).click()
      await expect(change).toBeEnabled()
      await expect(page.getByRole('button', { name: 'Опубликовать профиль' })).toBeVisible()
      // Итог под полосами: тест и ФСП — подтверждено, стаж и навыки — заявлено.
      await expect(page.locator('[data-slot="contribution-summary"]')).toHaveText(
        /Подтверждено: 0 из 40 \(тест и ФСП\) · Заявлено кандидатом: 33,5 из 60 \(стаж и навыки\)/,
      )
      // Нажатие прокрутило страницу: флажок согласия ушёл под липкую шапку, и axe счёл бы его область нажатия
      // перекрытой. Раскладка проверяется с начала страницы, как на остальных экранах.
      await page.evaluate(() => window.scrollTo(0, 0))
    },
  },
  {
    name: 'C2 опрос: специализация без теста выбирается',
    path: '/candidate/onboarding/survey',
    mock: {
      me: CANDIDATE,
      handlers: {
        ...WIZARD_STATE,
        'GET /candidate/profile': (route) =>
          json(route, {
            public_code: 'К-10042',
            first_name: 'Анна',
            last_name: 'Петрова',
            hints: { grade_hint: null, specialization_hint: null },
          }),
        'GET /assessment/survey': (route) =>
          json(route, {
            version: 'v1',
            answers: {},
            questions: [
              {
                id: 'specialization',
                title: 'Специализация',
                kind: 'single',
                required: true,
                depends_on: null,
                max: null,
                options: [
                  { code: 'backend', title: 'Backend-разработка', parent: null, available: true },
                  { code: 'frontend', title: 'Frontend-разработка', parent: null, available: false },
                ],
              },
            ],
          }),
      },
    },
    heading: 'Направление и специализация',
    prepare: async (page) => {
      const option = page.getByRole('radio', { name: /Frontend-разработка/ })
      await expect(option).toBeEnabled()
      await expect(page.getByText('тест готовится — грейд будет заявленным')).toBeVisible()
      await option.click()
      await expect(page.getByRole('button', { name: 'Продолжить' })).toBeEnabled()
      await page.evaluate(() => window.scrollTo(0, 0))
    },
  },
  {
    name: 'C3 грейд без теста: грейд заявляется, тест пропускается',
    path: '/candidate/onboarding/grade',
    mock: {
      me: CANDIDATE,
      handlers: {
        'GET /assessment/state': (route) => json(route, { ...DECLARED_STATE, claimed_grade: null, category: null }),
        'GET /assessment/survey': (route) => json(route, { version: 'v1', questions: [], answers: {} }),
        // Состав теста для специализации без теста пуст, а его сбой экран не блокирует.
        'GET /assessment/blueprints': (route) => apiError(route, 503, 'bank_unavailable'),
        'GET /candidate/profile': (route) =>
          json(route, {
            public_code: 'К-10042',
            first_name: 'Анна',
            last_name: 'Петрова',
            hints: { grade_hint: null, specialization_hint: null },
          }),
      },
    },
    heading: 'Заявите грейд',
    prepare: async (page) => {
      await expect(page.getByText(/Тест по специализации «Frontend-разработка» готовится/)).toBeVisible()
      // Все грейды доступны, хотя теста нет.
      await expect(page.getByRole('radio', { name: /Senior/ })).toBeEnabled()
      await page.getByRole('radio', { name: /Middle/ }).click()
      await expect(page.getByRole('button', { name: 'Заявить грейд' })).toBeEnabled()
      await page.evaluate(() => window.scrollTo(0, 0))
    },
  },
  {
    name: 'E3 потребность: специализация без теста выбирается, показано предупреждение',
    path: '/employer/needs/new',
    mock: { me: EMPLOYER },
    heading: 'Описание потребности',
    prepare: async (page) => {
      await page.getByRole('combobox', { name: /Специализация/ }).click()
      const option = page.getByRole('option', { name: /Frontend-разработка — тест готовится, грейд заявленный/ })
      await expect(option).toBeEnabled()
      await option.click()
      // Список закрылся и вернул фокус в поле: дальше страница не прокручивается сама.
      await expect(page.getByRole('listbox')).toHaveCount(0)
      await expect(page.getByRole('combobox', { name: /Специализация/ })).toHaveText('Frontend-разработка')
      await expect(page.getByText('По этой специализации тест готовится')).toBeVisible()
      await expect(page.getByText(/кандидаты с заявленным грейдом/)).toBeVisible()
      await page.evaluate(() => window.scrollTo(0, 0))
    },
  },
  {
    name: 'C10 заявленный грейд: после смены форма закрыта до даты',
    path: '/candidate/category',
    mock: {
      me: CANDIDATE,
      handlers: {
        ...DECLARED_CANDIDATE,
        'GET /assessment/state': (route) =>
          json(route, {
            ...DECLARED_STATE,
            category: { ...DECLARED_STATE.category, change_available_at: '2026-12-30T10:00:00Z' },
          }),
      },
    },
    heading: 'Категория и тесты',
    prepare: async (page) => {
      await expect(page.getByText(/Сменить заявленный грейд можно с 30\sдек/)).toBeVisible()
      await expect(page.getByRole('radio', { name: 'Senior' })).toBeDisabled()
      await expect(page.getByRole('button', { name: 'Сменить заявленный грейд' })).toBeDisabled()
    },
  },
  {
    name: 'C7 обзор: заявленный грейд ведёт на экран категории',
    path: '/candidate',
    mock: { me: CANDIDATE, handlers: DECLARED_CANDIDATE },
    heading: 'Обзор',
    prepare: async (page) => {
      await expect(page.getByText('Грейд заявлен, профиль не опубликован')).toBeVisible()
      await expect(page.getByRole('link', { name: 'Опубликовать профиль' })).toHaveAttribute(
        'href',
        '/candidate/category#publish',
      )
    },
  },
  {
    name: 'E5 карточка кандидата без уровня: грейд заявлен',
    path: `/employer/candidates/${DECLARED_CARD_ID}`,
    mock: { me: EMPLOYER, handlers: DECLARED_CARD },
    heading: 'Карточка кандидата',
    prepare: async (page) => {
      await expect(page.locator('[data-slot="category-chip-declared"]')).toContainText('заявлен')
      await expect(page.getByText('Грейд заявлен, тест готовится')).toBeVisible()
      await page.getByRole('button', { name: 'Вклад в оценку' }).click()
      await expect(page.locator('[data-slot="contribution-summary"]')).toBeVisible()
    },
  },
  { name: 'E2 каркас кабинета работодателя', path: '/employer/needs', mock: { me: EMPLOYER }, heading: 'Потребности' },
  { name: 'E10 аккаунт работодателя', path: '/employer/settings/account', mock: { me: EMPLOYER }, heading: 'Аккаунт' },
]

for (const viewport of VIEWPORTS) {
  test.describe(`экраны каркаса · ${viewport.name}`, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } })

    for (const screen of SCREENS) {
      test(screen.name, async ({ page }) => {
        await mockApi(page, screen.mock)
        await page.goto(screen.path)
        await expect(page.getByRole('heading', { level: 1, name: screen.heading })).toBeVisible()
        await screen.prepare?.(page)
        await expectCleanLayout(page, { tapTargets: viewport.width === 375, focus: true })
      })
    }
  })
}

test.describe('охрана маршрутов', () => {
  test('гость на закрытом маршруте уходит на вход с next', async ({ page }) => {
    await mockApi(page)
    await page.goto('/candidate/invitations?tab=accepted')
    await expect(page).toHaveURL(/\/login\?next=%2Fcandidate%2Finvitations%3Ftab%3Daccepted$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Вход' })).toBeVisible()
  })

  test('чужая роль перенаправляется на свой первый экран', async ({ page }) => {
    await mockApi(page, { me: EMPLOYER })
    await page.goto('/candidate/profile')
    // Потребностей нет — первый экран работодателя — описание потребности (E §1.4).
    await expect(page).toHaveURL(/\/employer\/needs\/new$/)
    await expect(page.getByText('Этот раздел доступен только кандидатам')).toBeVisible()
  })

  test('кандидат на шаге опроса не попадает дальше своего шага', async ({ page }) => {
    await mockApi(page, { me: CANDIDATE, handlers: WIZARD_STATE })
    await page.goto('/candidate/invitations')
    await expect(page).toHaveURL(/\/candidate\/onboarding\/survey$/)
    // Пройденный шаг доступен, будущий — нет.
    await page.goto('/candidate/onboarding/profile')
    await expect(page).toHaveURL(/\/candidate\/onboarding\/profile$/)
    await page.goto('/candidate/test/new')
    await expect(page).toHaveURL(/\/candidate\/onboarding\/survey$/)
  })

  test('вошедший не видит форму входа; next с чужим адресом игнорируется', async ({ page }) => {
    await mockApi(page, { me: CANDIDATE })
    await page.goto('/login?next=//evil.example/path')
    await expect(page).toHaveURL(/\/candidate$/)
  })

  test('вход ведёт на next, если это путь внутри сайта', async ({ page }) => {
    let signedIn = false
    await mockApi(page, {
      handlers: {
        'GET /auth/me': (route) => (signedIn ? json(route, CANDIDATE) : apiError(route, 401, 'not_authenticated')),
        'POST /auth/login': (route) => {
          signedIn = true
          return json(route, CANDIDATE)
        },
      },
    })
    await page.goto('/login?next=%2Fcandidate%2Fcategory')
    await page.getByLabel('E-mail').fill('  Anna@Example.com ')
    await page.locator('input[name="password"]').fill('correct-password')
    const request = page.waitForRequest('**/api/v1/auth/login')
    await page.getByRole('button', { name: 'Войти' }).click()
    // Адрес уходит на сервер обрезанным и в нижнем регистре (Арх. 10.1).
    expect((await request).postDataJSON()).toEqual({ email: 'anna@example.com', password: 'correct-password' })
    await expect(page).toHaveURL(/\/candidate\/category$/)
  })

  test('регистрация отправляет версию согласия и открывает «Проверьте почту»', async ({ page }) => {
    await mockApi(page, {
      handlers: { 'POST /auth/signup': (route) => route.fulfill({ status: 202, body: '' }) },
    })
    await page.goto('/signup?role=employer')
    await expect(page.getByRole('radio', { name: 'Работодатель' })).toBeChecked()
    await page.getByLabel('E-mail').fill('hr@example.com')
    await page.locator('input[name="password"]').fill('correct-password')
    // Без двух отметок кнопка неактивна, причина названа текстом (E §9.2, P2).
    await expect(page.getByRole('button', { name: 'Зарегистрироваться' })).toHaveAttribute('aria-disabled', 'true')
    await expect(page.getByText('Чтобы зарегистрироваться, отметьте согласие и возраст')).toBeVisible()
    await page.getByRole('checkbox', { name: /Согласен\(на\) на обработку/ }).click()
    await page.getByRole('checkbox', { name: /Мне исполнилось 18 лет/ }).click()
    const request = page.waitForRequest('**/api/v1/auth/signup')
    await page.getByRole('button', { name: 'Зарегистрироваться' }).click()
    expect((await request).postDataJSON()).toEqual({
      email: 'hr@example.com',
      password: 'correct-password',
      role: 'employer',
      consent_processing: true,
      consent_version: '2026-10-01',
      is_adult: true,
    })
    // Адрес почты в адресную строку не попадает: экран берёт его из хранилища вкладки.
    await expect(page).toHaveURL(/\/signup\/check-email$/)
    await expect(page.getByText('hr@example.com')).toBeVisible()
    await expect(page.getByRole('heading', { level: 1, name: 'Проверьте почту' })).toBeVisible()
  })

  test('401 в кабинете: сессия истекла — переход на вход с возвратом', async ({ page }) => {
    let expired = false
    await mockApi(page, {
      me: CANDIDATE,
      handlers: {
        'GET /candidate/invitations/summary': (route) =>
          expired
            ? apiError(route, 401, 'not_authenticated')
            : json(route, {
                awaiting: 0,
                accepted: 1,
                archived: 0,
                outcome_prompts: 0,
                strikes: { count: 0, limit: 2 },
                visibility: { state: 'visible', pause_reason: null, auto_paused_until: null },
              }),
      },
    })
    await page.goto('/candidate/category')
    await expect(page.getByRole('heading', { level: 1, name: 'Категория и тесты' })).toBeVisible()
    expired = true
    // Опрос сводки раз в 20 с ждать незачем: возврат фокуса на вкладку обновляет её сразу.
    await page.evaluate(() => window.dispatchEvent(new Event('visibilitychange')))
    await expect(page).toHaveURL(/\/login\?next=%2Fcandidate%2Fcategory$/, { timeout: 15_000 })
    await expect(page.getByText('Сессия истекла. Войдите снова')).toBeVisible()
  })
})

test.describe('демо-вход: блок ведущего', () => {
  test('ключ уходит с каждым запросом; сдвиг часов и сброс вызывают свои адреса', async ({ page }) => {
    const KEY = 'host-key-for-tests'
    const seen: string[] = []
    let offset = 0
    const clock = () => ({
      now: new Date(Date.UTC(2026, 9, 9, 10) + offset * 1000).toISOString(),
      offset_seconds: offset,
    })
    const guarded = (name: string, reply: (route: Route) => Promise<void> | void) => (route: Route) => {
      if (route.request().headers()['x-admin-token'] !== KEY) return apiError(route, 403, 'forbidden')
      seen.push(name)
      return reply(route)
    }
    await mockApi(page, {
      handlers: {
        'GET /demo/accounts': (route) => json(route, []),
        'GET /demo/clock': guarded('clock', (route) => json(route, clock())),
        'POST /demo/clock/advance': guarded('advance', (route) => {
          offset += route.request().postDataJSON().hours * 3600
          return json(route, clock())
        }),
        'POST /demo/reset': guarded('reset', (route) => json(route, { reset_at: clock().now })),
      },
    })
    await page.goto('/demo')
    await page.locator('summary').filter({ hasText: 'Для ведущего' }).click()

    // Неверный ключ отклоняется сразу — по запросу часов, а не при первом действии.
    await page.getByLabel('Ключ ведущего').fill('wrong')
    await page.getByRole('button', { name: 'Применить ключ' }).click()
    await expect(page.getByText('Ключ не подошёл')).toBeVisible()
    expect(seen).toEqual([])

    await page.getByLabel('Ключ ведущего').fill(KEY)
    await page.getByRole('button', { name: 'Применить ключ' }).click()
    await expect(page.getByText(/Время сервиса:\s+9\s+окт/)).toBeVisible()
    await expect(page.getByText('Ключ не подошёл')).toHaveCount(0)

    await page.getByRole('button', { name: '+7 дней' }).click()
    await expect(page.getByText(/Время сервиса:\s+16\s+окт/)).toBeVisible()

    await page.getByRole('button', { name: 'Сбросить демо-данные' }).click()
    const dialog = page.getByRole('alertdialog', { name: 'Сбросить демо-данные?' })
    await dialog.getByRole('button', { name: 'Сбросить' }).click()
    await expect(dialog).toBeHidden()
    expect(seen).toContain('advance')
    expect(seen).toContain('reset')
  })
})

test.describe('сеанс', () => {
  test('выход из меню пользователя ведёт на лендинг', async ({ page }) => {
    let signedIn = true
    await mockApi(page, {
      handlers: {
        'GET /auth/me': (route) => (signedIn ? json(route, CANDIDATE) : apiError(route, 401, 'not_authenticated')),
        'POST /auth/logout': (route) => {
          signedIn = false
          return route.fulfill({ status: 204, body: '' })
        },
      },
    })
    await page.goto('/candidate/category')
    await page.getByRole('button', { name: 'Меню пользователя' }).click()
    await expect(page.getByRole('menu')).toContainText('anna@example.com')
    await page.getByRole('menuitem', { name: 'Выйти' }).click()
    await expect(page).toHaveURL(/\/$/)
    await expect(
      page.getByRole('heading', { level: 1, name: /Платформа ИТ-специалистов, проверенных ФСП/ }),
    ).toBeVisible()
    await expect(page.getByText('Вы вышли из аккаунта')).toBeVisible()
  })

  test('удаление аккаунта: неверный пароль — ошибка под полем, верный — выход на лендинг', async ({ page }) => {
    let deleted = false
    await mockApi(page, {
      handlers: {
        'GET /auth/me': (route) => (deleted ? apiError(route, 401, 'not_authenticated') : json(route, EMPLOYER)),
        'POST /auth/account/delete': (route) => {
          const body = route.request().postDataJSON() as { password: string }
          if (body.password !== 'correct-password') return apiError(route, 422, 'current_password_invalid')
          deleted = true
          return route.fulfill({ status: 204, body: '' })
        },
      },
    })
    await page.goto('/employer/settings/account')
    await page.getByRole('button', { name: 'Отозвать согласие и удалить данные' }).click()
    const dialog = page.getByRole('alertdialog')
    await dialog.locator('input[name="password"]').fill('wrong')
    await dialog.getByRole('button', { name: 'Удалить аккаунт' }).click()
    await expect(dialog.getByText('Пароль не подошёл')).toBeVisible()
    await dialog.locator('input[name="password"]').fill('correct-password')
    await dialog.getByRole('button', { name: 'Удалить аккаунт' }).click()
    await expect(page).toHaveURL(/\/$/)
    await expect(page.getByText('Аккаунт удалён')).toBeVisible()
  })

  test('нижний таб-бар на узком экране: активный пункт, переход по пункту', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 })
    await mockApi(page, { me: CANDIDATE })
    await page.goto('/candidate')
    const tabbar = page.getByRole('navigation', { name: 'Основная навигация' })
    await expect(tabbar.getByRole('link', { name: 'Обзор' })).toHaveAttribute('aria-current', 'page')
    await expect(tabbar.getByRole('link', { name: /Приглашения/ })).toBeVisible()
    await expectCleanLayout(page, { tapTargets: true })
    await tabbar.getByRole('link', { name: 'Профиль' }).click()
    await expect(page).toHaveURL(/\/candidate\/profile/)
  })
})

test.describe('клавиатура', () => {
  test('кольцо фокуса видно на каждом элементе: 2 px brand-600, появляется без перехода', async ({ page }) => {
    await mockApi(page)
    await page.goto('/signup')
    await expect(page.getByRole('heading', { level: 1, name: 'Регистрация' })).toBeVisible()
    const seen: string[] = []
    for (let step = 0; step < 14; step += 1) {
      await page.keyboard.press('Tab')
      // Стиль читается сразу после нажатия: кольцо не должно «проявляться» переходом из цвета текста.
      const focused = await page.evaluate(() => {
        const el = document.activeElement as HTMLElement
        const style = getComputedStyle(el)
        return {
          name: (el.getAttribute('aria-label') || el.textContent || el.getAttribute('name') || el.tagName)
            .trim()
            .slice(0, 30),
          focusVisible: el.matches(':focus-visible'),
          outline: `${style.outlineStyle} ${style.outlineWidth} ${style.outlineColor} ${style.outlineOffset}`,
        }
      })
      seen.push(focused.name)
      expect(focused.focusVisible, focused.name).toBe(true)
      expect(focused.outline, focused.name).toBe('solid 2px rgb(64, 47, 255) 2px')
    }
    // Первая остановка — ссылка «К содержимому» (E §7); порядок Tab идёт по порядку чтения формы.
    expect(seen[0]).toBe('К содержимому')
    expect(seen).toContain('Показать пароль')
  })
})
