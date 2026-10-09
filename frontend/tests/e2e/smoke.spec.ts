/**
 * Сквозные проверки на живом стенде с демо-данными: `make e2e` (стенд поднят, `DEMO_MODE=true`,
 * в `ALLOWED_ORIGINS` есть адрес, по которому тесты видят стенд: для сервиса `e2e` из compose — `http://web`).
 *
 * Тесты только читают состояние демо-аккаунтов: порядок запуска и повторные прогоны ничего не ломают.
 * Сессии готовит `tests/auth.setup.ts`.
 */
import { expect, test } from '@playwright/test'
import { authFile } from '../utils/demo-accounts'

type ShortlistItem = {
  position: number
  relation: string
  display_name: string | null
  must_covered: number
  must_total: number
}

test.describe('работодатель', () => {
  test.use({ storageState: authFile('orbita') })

  test('подборка под потребность: строки объяснены, сначала закрывшие обязательные навыки', async ({ page }) => {
    const needs = await (await page.request.get('/api/v1/employer/needs')).json()
    expect(needs.length).toBeGreaterThan(0)
    const need = needs[0]

    await page.goto(`/employer/needs/${need.id}`)
    await expect(page.getByRole('heading', { level: 1, name: need.title })).toBeVisible()
    await expect(page.getByText('Как сформирована подборка')).toBeVisible()
    await expect(page.getByText(/из \d+ обязательных навыков/).first()).toBeVisible()

    const versions = await (await page.request.get(`/api/v1/employer/needs/${need.id}/shortlists`)).json()
    const latest = versions.find((row: { is_latest: boolean }) => row.is_latest)
    const snapshot = await (await page.request.get(`/api/v1/employer/shortlists/${latest.id}`)).json()
    const exact: ShortlistItem[] = snapshot.items.filter((item: ShortlistItem) => item.relation === 'exact')
    expect(exact.length).toBeGreaterThan(3)

    // Первый ключ порядка внутри раздела — число обязательных навыков без данных: оно не убывает сверху вниз.
    const missing = exact.map((item) => item.must_total - item.must_covered)
    expect(missing).toEqual([...missing].sort((a, b) => a - b))
    // Имя кандидата есть только у раскрытых пар; в самой подборке это заведомо не все строки.
    expect(snapshot.items.some((item: ShortlistItem) => item.display_name === null)).toBe(true)
  })

  test('карточка кандидата до приглашения: доводы есть, имени и контактов нет', async ({ page }) => {
    const needs = await (await page.request.get('/api/v1/employer/needs')).json()
    const versions = await (await page.request.get(`/api/v1/employer/needs/${needs[0].id}/shortlists`)).json()
    const snapshot = await (await page.request.get(`/api/v1/employer/shortlists/${versions[0].id}`)).json()
    const hidden = snapshot.items.find((item: ShortlistItem) => item.display_name === null)
    expect(hidden).toBeTruthy()

    const card = await page.request.get(`/api/v1/employer/candidates/${hidden.candidate_id}?need_id=${needs[0].id}`)
    expect(card.status()).toBe(200)
    const body = await card.json()
    expect(body.disclosed).toBe(false)
    expect(body.display_name).toBeNull()
    expect(body.match.reasons.length).toBeGreaterThan(0)
    expect(JSON.stringify(body)).not.toMatch(/@demo\.test|\+7\d{10}/)

    const contacts = await page.request.get(`/api/v1/employer/candidates/${hidden.candidate_id}/contacts`)
    expect(contacts.status()).toBe(403)
    expect((await contacts.json()).code).toBe('not_disclosed')
  })

  test('банк кандидатов фильтруется по специализации и грейду', async ({ page }) => {
    await page.goto('/employer/search')
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    const bank = await (
      await page.request.get('/api/v1/employer/candidates?specialization=backend&grade=senior')
    ).json()
    expect(bank.items.length).toBeGreaterThan(0)
    for (const item of bank.items) expect(item.category.code).toBe('backend:senior')
  })
})

test.describe('работодатель: форма приглашения', () => {
  test.use({ storageState: authFile('orbita') })

  /** Кандидат банка, которому эта компания ещё не писала: форма откроется, а не блокировка «уже приглашён». */
  async function freeCandidate(page: import('@playwright/test').Page): Promise<{ id: string; code: string }> {
    const bank = await (await page.request.get('/api/v1/employer/candidates?specialization=backend&limit=50')).json()
    const ids = bank.items.map((item: { candidate_id: string }) => item.candidate_id)
    const pairs = await (
      await page.request.get(`/api/v1/employer/invitations/pair-states?candidate_ids=${ids.join(',')}`)
    ).json()
    const busy = new Set(
      pairs.items
        .filter((pair: { invitation: unknown; pair_block: unknown }) => pair.invitation || pair.pair_block)
        .map((pair: { candidate_id: string }) => pair.candidate_id),
    )
    const free = bank.items.find((item: { candidate_id: string }) => !busy.has(item.candidate_id))
    expect(free, 'в банке нет кандидата без приглашения от демо-компании').toBeTruthy()
    return { id: free.candidate_id, code: free.public_code }
  }

  test('из подборки: форма открыта и заполнена из потребности, вилка обязательна', async ({ page }) => {
    const needs = await (await page.request.get('/api/v1/employer/needs')).json()
    const need = needs[0]
    const candidate = await freeCandidate(page)

    await page.goto(`/employer/needs/${need.id}?candidate=${candidate.id}&invite=true`)
    await expect(page.getByRole('heading', { name: 'Приглашение · шаг 1 из 2: условия' })).toBeVisible()
    await expect(page.getByText(candidate.code).last()).toBeVisible()
    // Раньше на этом месте стояла заглушка «шаг подключается вместе с модулем приглашений».
    await expect(page.getByText('подключается вместе с модулем')).toHaveCount(0)
    await expect(page.getByLabel('Заголовок предложения')).toHaveValue(need.title)
    await expect(page.getByRole('button', { name: 'Проверить и отправить' })).toBeVisible()
  })

  test('из банка и со страницы карточки: форма без привязки к потребности', async ({ page }) => {
    const candidate = await freeCandidate(page)

    await page.goto(`/employer/search?candidate=${candidate.id}&invite=true`)
    await expect(page.getByRole('heading', { name: 'Приглашение · шаг 1 из 2: условия' })).toBeVisible()
    await expect(page.getByLabel('Заголовок предложения')).toHaveValue('')
    // Пустую форму отправить нельзя: вилка и описание обязательны.
    await page.getByRole('button', { name: 'Проверить и отправить' }).click()
    await expect(page.getByText('Укажите вилку')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Приглашение · шаг 1 из 2: условия' })).toBeVisible()

    await page.goto(`/employer/candidates/${candidate.id}?invite=true`)
    await expect(page.getByRole('heading', { name: 'Приглашение · шаг 1 из 2: условия' })).toBeVisible()
  })
})

test.describe('кандидат без категории', () => {
  test.use({ storageState: authFile('petr') })

  test('кнопка «Пройти тест на Junior» открывает тест именно на Junior', async ({ page }) => {
    await page.goto('/candidate')
    const link = page.getByRole('link', { name: 'Пройти тест на Junior' })
    await expect(link).toBeVisible()
    await link.click()
    await expect(page).toHaveURL(/\/candidate\/test\/new\?grade=junior$/)
    await expect(page.getByRole('heading', { level: 1, name: /Junior/ })).toBeVisible()
  })
})

test.describe('кандидат с приглашением', () => {
  test.use({ storageState: authFile('anna') })

  test('в приглашении видны компания и вилка в рублях', async ({ page }) => {
    // Приглашение Анны может быть уже принято или отклонено на этом стенде: ищем по всем вкладкам.
    let invitation: { id: string; company_name: string; salary_from: number; salary_to: number } | undefined
    for (const tab of ['', '?status=accepted', '?status=archived']) {
      const list = await (await page.request.get(`/api/v1/candidate/invitations${tab}`)).json()
      invitation = list.items?.[0]
      if (invitation) break
    }
    expect(invitation, 'у демо-кандидата нет ни одного приглашения').toBeTruthy()
    if (!invitation) return
    expect(invitation.company_name).toBeTruthy()
    expect(invitation.salary_from).toBeGreaterThan(0)
    expect(invitation.salary_to).toBeGreaterThanOrEqual(invitation.salary_from)

    await page.goto(`/candidate/invitations/${invitation.id}`)
    await expect(page.getByText(invitation.company_name).first()).toBeVisible()
    await expect(page.getByText('₽').first()).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Способ связи' })).toBeVisible()
  })
})

test.describe('без входа', () => {
  test('страница «Как это работает» показывает числа отчётов валидации', async ({ page }) => {
    await page.goto('/how-it-works')
    await expect(page.getByRole('heading', { name: 'Механика подбора' })).toBeVisible()
    await expect(page.getByText('Точность первой десятки: наш порядок')).toBeVisible()
    const summary = await (await page.request.get('/api/v1/validation/summary')).json()
    expect(summary.matching.p10_ours).toBeGreaterThan(summary.matching.p10_declared)
  })

  test('кабинет без сессии уводит на вход', async ({ page }) => {
    await page.goto('/employer/needs')
    await expect(page).toHaveURL(/\/login/)
  })
})
