/**
 * Подготовка сквозных тестов: вход в именованные демо-аккаунты стенда (Арх. 13.5) и сохранение состояния сессии.
 * Тесты проекта `e2e` подключают его так: `test.use({ storageState: authFile('anna') })`.
 *
 * Требует живого стенда с `DEMO_MODE=true`. Аккаунт `nina` не сохраняется: каждый вход «как Нина» создаёт
 * новый клон, и общий файл состояния сталкивал бы тесты между собой — её тест входит сам (`loginAsDemo`).
 */
import { expect, test as setup } from '@playwright/test'
import { authFile, DEMO_ACCOUNTS } from './utils/demo-accounts'

for (const key of DEMO_ACCOUNTS) {
  setup(`вход в демо-аккаунт ${key}`, async ({ page }) => {
    // Запрос идёт из страницы стенда, чтобы заголовок Origin совпал с адресом стенда (проверка Арх. 10.1).
    await page.goto('/')
    const response = await page.request.post('/api/v1/demo/login', {
      data: { account_key: key },
      headers: { Origin: new URL(page.url()).origin },
    })
    setup.skip(response.status() === 404, 'демо-режим на стенде выключен (features.demo = false)')
    expect(response.status(), `POST /demo/login для ${key}`).toBe(200)
    const me = await response.json()
    expect(me.is_demo).toBe(true)
    await page.context().storageState({ path: authFile(key) })
  })
}
