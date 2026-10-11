import { expect, test } from '@playwright/test'
import { CANDIDATE, json, mockApi, SERVER_NOW } from '../utils/api-mock'

const accounts = [
  { key: 'anna', title: 'Анна', role: 'candidate', state_label: 'Категория подтверждена' },
  { key: 'hr_orbita', title: 'Орбита', role: 'employer', state_label: 'Профиль компании заполнен' },
]

test('демо: гость видит доступные аккаунты', async ({ page }) => {
  const requests: string[] = []
  page.on('request', (request) => {
    const path = new URL(request.url()).pathname
    if (path.startsWith('/api/v1/demo/')) requests.push(path)
  })
  await mockApi(page, { handlers: { 'GET /demo/accounts': (route) => json(route, accounts) } })
  await page.goto('/demo')
  await expect(page.getByRole('button', { name: 'Войти как Анна' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Войти как Орбита' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Начать сценарий заново' })).toHaveCount(0)
  expect(requests).toEqual(['/api/v1/demo/accounts'])
})

test('демо: перезапуск использует контракт сценария и показывает результат', async ({ page }) => {
  await mockApi(page, {
    me: { ...CANDIDATE, is_demo: true },
    handlers: {
      'GET /demo/accounts': (route) => json(route, accounts),
      'POST /demo/scenario/restart': (route) => json(route, { restarted_at: SERVER_NOW }),
    },
  })
  await page.goto('/demo')
  await expect(page.getByText('Перезапуск ещё не выполнялся.')).toBeVisible()
  const response = page.waitForResponse((r) => r.url().endsWith('/demo/scenario/restart'))
  await page.getByRole('button', { name: 'Начать сценарий заново' }).click()
  expect((await response).status()).toBe(200)
  await expect(page.getByText('Сценарий перезапущен', { exact: true })).toBeVisible()
  await expect(page.getByText(/^Последний перезапуск:/)).toBeVisible()
})
