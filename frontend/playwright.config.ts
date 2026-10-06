import { defineConfig, devices } from '@playwright/test'

/**
 * Playwright: автопроверка вёрстки (приложение E, §4.7) и сквозные тесты.
 *
 * Проекты:
 *   layout — tests/layout: витрина компонентов и экраны каркаса на перехвате запросов, бэкенд не нужен;
 *   setup  — tests/auth.setup.ts: вход в демо-аккаунты стенда, состояние сессий — в tests/.auth;
 *   e2e    — tests/e2e (сборочный пакет): сквозные пути на живом стенде, зависит от setup.
 *
 * Адрес стенда задаёт E2E_BASE_URL (её передаёт сервис e2e в compose.yml: http://web) либо BASE_URL.
 * Без них поднимается dev-сервер Vite.
 * Эталонные скриншоты снимаются только в образе mcr.microsoft.com/playwright:v1.63.0-noble.
 */
const standURL = process.env.E2E_BASE_URL || process.env.BASE_URL
const baseURL = standURL ?? 'http://127.0.0.1:5173'

export default defineConfig({
  testDir: './tests',
  outputDir: './test-results',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  timeout: 60_000,
  expect: {
    timeout: 10_000,
    toHaveScreenshot: { animations: 'disabled' },
  },
  use: {
    baseURL,
    locale: 'ru-RU',
    timezoneId: 'Europe/Moscow',
    // Движение отключено: проверяется раскладка, а не кадры анимации (E §4.7).
    reducedMotion: 'reduce',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'layout',
      testDir: './tests/layout',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'setup',
      testMatch: /auth\.setup\.ts/,
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'e2e',
      testDir: './tests/e2e',
      dependencies: ['setup'],
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: standURL
    ? undefined
    : {
        command: 'npm run dev',
        url: baseURL,
        reuseExistingServer: true,
        timeout: 60_000,
      },
})
