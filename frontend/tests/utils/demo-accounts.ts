/** Именованные демо-аккаунты сида (Арх. 13.5) и файлы с состоянием их сессий для сквозных тестов. */
import path from 'node:path'
import type { Page } from '@playwright/test'

export const DEMO_ACCOUNTS = ['orbita', 'anna', 'dmitry', 'ivan', 'gleb', 'boris', 'olga', 'maria', 'petr'] as const
export type DemoAccount = (typeof DEMO_ACCOUNTS)[number]

/** Файл состояния сессии аккаунта (каталог tests/.auth не попадает в репозиторий). */
export function authFile(key: DemoAccount): string {
  return path.join(import.meta.dirname, '..', '.auth', `${key}.json`)
}

/** Войти в демо-аккаунт внутри теста (нужно для `nina`: каждый вход создаёт отдельный клон). */
export async function loginAsDemo(page: Page, key: DemoAccount | 'nina'): Promise<void> {
  await page.goto('/')
  const response = await page.request.post('/api/v1/demo/login', {
    data: { account_key: key },
    headers: { Origin: new URL(page.url()).origin },
  })
  if (!response.ok()) throw new Error(`Не удалось войти в демо-аккаунт ${key}: HTTP ${response.status()}`)
}
