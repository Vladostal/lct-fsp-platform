import { expect, test } from '@playwright/test'
import { mockApi } from '../utils/api-mock'
import { collectLayoutIssues, expectCleanLayout, settle } from '../utils/layout'
import { MIN_VIEWPORT, VIEWPORTS } from '../utils/viewports'

/**
 * Витрина компонентов `/demo/components` (E §9.2, P7): все общие компоненты с проверочными строками проходят
 * G1–G3 на трёх ширинах и на 320 px; дополнительно — axe, область нажатия на 375 и перекрытие фокуса.
 */
const SHOWCASE = '/demo/components'
const screenshotDir = process.env.SHOWCASE_SCREENSHOT_DIR ?? 'test-results/screenshots'

for (const viewport of VIEWPORTS) {
  test.describe(`витрина · ${viewport.name}`, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } })

    test.beforeEach(async ({ page }) => {
      await mockApi(page)
      await page.goto(SHOWCASE)
      await expect(page.getByRole('heading', { level: 1, name: 'Витрина компонентов' })).toBeVisible()
    })

    test('текст не накладывается и не обрезается, контраст и имена в порядке', async ({ page }) => {
      await expectCleanLayout(page, { tapTargets: viewport.width === 375, focus: true })
    })

    test('открытый диалог и боковая панель', async ({ page }) => {
      await page.getByRole('button', { name: 'Открыть диалог' }).click()
      const dialog = page.getByRole('dialog', { name: 'Принять приглашение?' })
      await expect(dialog).toBeVisible()
      // В открытом диалоге — не больше одной своей основной кнопки (G5).
      await expect(dialog.locator('[data-variant="primary"]')).toHaveCount(1)
      await expectCleanLayout(page, { axe: true })
      await page.keyboard.press('Escape')
      await expect(dialog).toBeHidden()
      // Esc возвращает фокус на элемент, открывший слой (G10).
      await expect(page.getByRole('button', { name: 'Открыть диалог' })).toBeFocused()

      await page.getByRole('button', { name: 'Открыть панель' }).click()
      const sheet = page.getByRole('dialog', { name: 'Кандидат К-10042' })
      await expect(sheet).toBeVisible()
      await expectCleanLayout(page, { axe: true })
      await page.keyboard.press('Escape')
      await expect(sheet).toBeHidden()
    })

    test('поле тегов: поиск по алиасу, свой тег, удаление с клавиатуры', async ({ page }) => {
      const input = page.getByRole('combobox', { name: 'Стек' })
      await input.fill('кафка')
      await page.getByRole('option', { name: 'Apache Kafka' }).click()
      await expect(page.getByRole('button', { name: 'Убрать Apache Kafka' })).toBeVisible()
      await input.fill('Свой навык')
      await page.keyboard.press('Enter')
      await expect(page.getByRole('button', { name: 'Убрать Свой навык' })).toBeVisible()
      await page.keyboard.press('Backspace')
      await expect(page.getByRole('button', { name: 'Убрать Свой навык' })).toHaveCount(0)
      await page.keyboard.press('Escape')
      await expectCleanLayout(page, { axe: false })
    })

    test('снимок страницы @screenshots', async ({ page }) => {
      test.skip(!process.env.SHOWCASE_SCREENSHOTS, 'снимки снимаются по запросу: npm run screenshots')
      await settle(page)
      await page.screenshot({ path: `${screenshotDir}/showcase-${viewport.name}.png`, fullPage: true })
    })
  })
}

test.describe('витрина · тёмная тема', () => {
  test.use({ viewport: { width: 1280, height: 800 } })

  test('контраст и раскладка в тёмной теме', async ({ page }) => {
    await page.addInitScript(() => window.localStorage.setItem('fsp-theme', 'dark'))
    await mockApi(page)
    await page.goto(SHOWCASE)
    await expect(page.getByRole('heading', { level: 1, name: 'Витрина компонентов' })).toBeVisible()
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
    await expectCleanLayout(page, { focus: true })
  })
})

test.describe('витрина · 320 (наименьшая ширина)', () => {
  test.use({ viewport: { width: MIN_VIEWPORT.width, height: MIN_VIEWPORT.height } })

  test('G1–G3 выполняются на 320 px', async ({ page }) => {
    await mockApi(page)
    await page.goto(SHOWCASE)
    const issues = (await collectLayoutIssues(page, { axe: false })).filter((issue) => /^G[123]$/.test(issue.check))
    expect(issues, issues.map((issue) => `${issue.check} · ${issue.selector} · ${issue.detail}`).join('\n')).toEqual([])
  })
})
