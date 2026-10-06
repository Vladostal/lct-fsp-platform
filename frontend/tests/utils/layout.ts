/**
 * Автопроверка вёрстки (приложение E, §4.7; чек-лист §9.1). Функции собирают нарушения и возвращают их списком:
 * тест печатает все замечания страницы разом, а не падает на первом.
 *
 * Проверки:
 *   G1  нет горизонтальной прокрутки страницы;
 *   G2  текст не накладывается на текст и на элементы управления;
 *   G3  текст не выходит за контейнер и не обрезается без многоточия и title;
 *   G4  один h1; G5 в main не больше одной кнопки primary;
 *   G9  axe: контраст и имена элементов; G13 область нажатия не меньше 44 × 44 px;
 *   G14 элемент в фокусе не перекрыт липкими панелями; G17 в тексте нет «undefined», «NaN», пустых подстановок.
 */
import AxeBuilder from '@axe-core/playwright'
import { expect, type Page } from '@playwright/test'

export type Issue = { check: string; selector: string; detail: string }

/** Дождаться шрифтов и спокойного состояния страницы: до этого измерять раскладку рано. */
export async function settle(page: Page): Promise<void> {
  await page.waitForLoadState('networkidle')
  await page.evaluate(async () => {
    await document.fonts.ready
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve(null))))
  })
}

/** G1. Нет горизонтальной прокрутки страницы. */
export async function checkNoHorizontalScroll(page: Page): Promise<Issue[]> {
  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }))
  return scrollWidth <= clientWidth
    ? []
    : [{ check: 'G1', selector: 'html', detail: `scrollWidth ${scrollWidth} > clientWidth ${clientWidth}` }]
}

/**
 * G2 и G3 одним проходом по DOM.
 *
 * Единица проверки — строка текста: прямоугольники `Range.getClientRects()` текстового узла. Это точнее, чем
 * рамка элемента: у инлайнового элемента `clientWidth` равен нулю, а у многострочного рамка захватывает
 * чужие строки.
 *
 * G3: строка должна лежать внутри своего блочного контейнера и внутри каждого предка, который обрезает
 * содержимое (`overflow` не `visible`). Выход допустим только при явном усечении (многоточие или line-clamp)
 * либо собственной прокрутке — и только если у элемента есть `title` или `aria-label`.
 * G2: строки разных элементов не пересекаются больше чем на 1 px по обеим осям; текст не лежит поверх
 * чужого элемента управления. Исключения: потомки `[data-overlay]` и липких панелей `[data-sticky]`.
 */
export async function checkText(page: Page): Promise<Issue[]> {
  return page.evaluate(() => {
    type Line = { el: Element; rect: DOMRect; text: string }
    const issues: { check: string; selector: string; detail: string }[] = []
    const TOLERANCE = 1

    const describe = (el: Element): string => {
      const parts: string[] = []
      let node: Element | null = el
      while (node && parts.length < 4 && node !== document.body) {
        const slot = node.getAttribute('data-slot')
        const id = node.id ? `#${node.id}` : ''
        parts.unshift(`${node.tagName.toLowerCase()}${id}${slot ? `[data-slot="${slot}"]` : ''}`)
        node = node.parentElement
      }
      return parts.join(' > ')
    }

    const isHidden = (el: Element): boolean => {
      for (let node: Element | null = el; node; node = node.parentElement) {
        const style = getComputedStyle(node)
        if (style.display === 'none' || style.visibility === 'hidden' || style.visibility === 'collapse') return true
        if (Number.parseFloat(style.opacity) === 0) return true
        if (node.getAttribute('aria-hidden') === 'true' && node.matches('[data-slot="skeleton"], svg')) return true
        // Скрытое от глаз, но доступное скринридеру (sr-only): квадрат 1 px с обрезкой.
        if (style.position === 'absolute' && node.clientWidth <= 1 && node.clientHeight <= 1) return true
      }
      return false
    }

    const blockContainer = (el: Element): Element => {
      let node: Element | null = el
      while (node) {
        const display = getComputedStyle(node).display
        if (display !== 'inline' && display !== 'contents') return node
        node = node.parentElement
      }
      return document.body
    }

    const hasName = (el: Element): boolean =>
      Boolean(el.getAttribute('title') || el.getAttribute('aria-label') || el.getAttribute('aria-labelledby'))

    // Открыт модальный слой — проверяется только он: страница под ним закрыта затемнением и недоступна.
    const openLayers = Array.from(document.querySelectorAll('[role="dialog"], [role="alertdialog"]')).filter(
      (el) => el.getAttribute('data-state') === 'open',
    )
    const scope: Element = openLayers[openLayers.length - 1] ?? document.body

    // Сбор строк текста.
    const lines: Line[] = []
    const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT)
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const text = node.textContent?.trim() ?? ''
      const parent = node.parentElement
      if (!text || !parent) continue
      if (parent.closest('script, style, noscript, option, title')) continue
      if (isHidden(parent)) continue
      const range = document.createRange()
      range.selectNodeContents(node)
      for (const rect of Array.from(range.getClientRects())) {
        if (rect.width < 1 || rect.height < 1) continue
        lines.push({ el: parent, rect, text })
      }
    }

    // G3: выход за контейнер и обрезание.
    const reported = new Set<Element>()
    for (const line of lines) {
      if (reported.has(line.el)) continue
      const container = blockContainer(line.el)
      const box = container.getBoundingClientRect()
      // По вертикали допуск шире: прямоугольник текста — это область глифов шрифта (выше кегля), и при плотном
      // интерлиньяже она на несколько пикселей выступает за строку, хотя сами буквы на месте.
      const vertical = Math.max(TOLERANCE, Number.parseFloat(getComputedStyle(line.el).fontSize) * 0.3)
      const sticksOut =
        line.rect.left < box.left - TOLERANCE ||
        line.rect.right > box.right + TOLERANCE ||
        line.rect.top < box.top - vertical ||
        line.rect.bottom > box.bottom + vertical

      // Предок, который обрезает или прокручивает содержимое и за границы которого вышла строка.
      let clipper: Element | null = null
      for (let node: Element | null = container; node && node !== document.documentElement; node = node.parentElement) {
        const style = getComputedStyle(node)
        const clips = [style.overflowX, style.overflowY].some((value) => value !== 'visible')
        if (!clips) continue
        const rect = node.getBoundingClientRect()
        if (
          line.rect.left < rect.left - TOLERANCE ||
          line.rect.right > rect.right + TOLERANCE ||
          line.rect.top < rect.top - vertical ||
          line.rect.bottom > rect.bottom + vertical
        ) {
          clipper = node
          break
        }
      }

      if (clipper) {
        const style = getComputedStyle(clipper)
        const scrollable = [style.overflowX, style.overflowY].some((value) => value === 'auto' || value === 'scroll')
        const ellipsis = style.textOverflow === 'ellipsis'
        const clamp = style.webkitLineClamp !== 'none' && style.webkitLineClamp !== ''
        const named = hasName(clipper) || hasName(line.el)
        // Диалоги и панели прокручивают собственное содержимое: имя есть у слоя, а не у его тела.
        const insideNamedLayer = Boolean(
          clipper.closest('[role="dialog"], [role="alertdialog"], [role="listbox"], [role="menu"]'),
        )
        if (!((scrollable && (named || insideNamedLayer)) || ((ellipsis || clamp) && named))) {
          reported.add(line.el)
          issues.push({
            check: 'G3',
            selector: describe(line.el),
            detail: `текст обрезан без явного усечения и title: «${line.text.slice(0, 60)}»`,
          })
        }
        continue
      }
      if (sticksOut) {
        reported.add(line.el)
        issues.push({
          check: 'G3',
          selector: describe(line.el),
          detail: `текст выходит за контейнер ${describe(container)}: «${line.text.slice(0, 60)}»`,
        })
      }
    }

    // G2: наложение. Проверяются только строки, которые видны на экране целиком (не обрезаны и не прокручены).
    const exempt = (el: Element) =>
      Boolean(el.closest('[data-overlay], [data-sticky], [data-radix-popper-content-wrapper], [data-sonner-toaster]'))
    const visibleLines = lines.filter((line) => !exempt(line.el) && !reported.has(line.el))
    const intersects = (a: DOMRect, b: DOMRect) =>
      Math.min(a.right, b.right) - Math.max(a.left, b.left) > TOLERANCE &&
      Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > TOLERANCE

    // Строки, скрытые усечением (многоточие, line-clamp) или прокруткой, в сравнении не участвуют.
    const clippedAway = (line: Line): boolean => {
      for (let node: Element | null = line.el; node && node !== document.documentElement; node = node.parentElement) {
        const style = getComputedStyle(node)
        if ([style.overflowX, style.overflowY].every((value) => value === 'visible')) continue
        const rect = node.getBoundingClientRect()
        if (
          line.rect.right > rect.right + TOLERANCE ||
          line.rect.bottom > rect.bottom + TOLERANCE ||
          line.rect.left < rect.left - TOLERANCE ||
          line.rect.top < rect.top - TOLERANCE
        ) {
          return true
        }
      }
      return false
    }
    const shown = visibleLines.filter((line) => !clippedAway(line))
    const sorted = [...shown].sort((a, b) => a.rect.top - b.rect.top)
    const seenPairs = new Set<string>()
    for (let i = 0; i < sorted.length; i += 1) {
      const a = sorted[i] as Line
      for (let j = i + 1; j < sorted.length; j += 1) {
        const b = sorted[j] as Line
        if (b.rect.top >= a.rect.bottom - TOLERANCE) break
        if (a.el === b.el || a.el.contains(b.el) || b.el.contains(a.el)) continue
        if (!intersects(a.rect, b.rect)) continue
        const key = `${describe(a.el)}|${describe(b.el)}`
        if (seenPairs.has(key)) continue
        seenPairs.add(key)
        issues.push({
          check: 'G2',
          selector: describe(a.el),
          detail: `текст «${a.text.slice(0, 40)}» накладывается на «${b.text.slice(0, 40)}» (${describe(b.el)})`,
        })
      }
    }

    // G2: текст поверх чужого элемента управления.
    const controls = Array.from(
      scope.querySelectorAll(
        'input, textarea, select, button, [role="combobox"], [role="switch"], [role="checkbox"], [role="radio"]',
      ),
    ).filter((el) => !isHidden(el) && !exempt(el))
    for (const control of controls) {
      const box = control.getBoundingClientRect()
      if (box.width < 1 || box.height < 1) continue
      for (const line of shown) {
        if (control.contains(line.el) || line.el.contains(control)) continue
        // Подпись, вложенная в <label> вместе с полем, и содержимое самого поля — не наложение.
        if (line.el.closest('label')?.contains(control)) continue
        if (!intersects(line.rect, box)) continue
        issues.push({
          check: 'G2',
          selector: describe(line.el),
          detail: `текст «${line.text.slice(0, 40)}» лежит поверх элемента управления ${describe(control)}`,
        })
      }
    }

    return issues
  })
}

/** G4, G5, G17: структура и «сырой» текст. */
export async function checkStructure(page: Page, options: { primaryLimit?: number } = {}): Promise<Issue[]> {
  const limit = options.primaryLimit ?? 1
  return page.evaluate((primaryLimit) => {
    const issues: { check: string; selector: string; detail: string }[] = []
    const h1 = document.querySelectorAll('h1').length
    if (h1 !== 1) issues.push({ check: 'G4', selector: 'h1', detail: `заголовков h1: ${h1}, должен быть один` })
    if (!document.title.trim()) issues.push({ check: 'G4', selector: 'title', detail: 'пустой document.title' })
    if (document.documentElement.lang !== 'ru') {
      issues.push({ check: 'G4', selector: 'html', detail: `lang="${document.documentElement.lang}", ожидался "ru"` })
    }
    const primary = document.querySelectorAll('main [data-variant="primary"]').length
    if (primary > primaryLimit) {
      issues.push({
        check: 'G5',
        selector: 'main [data-variant="primary"]',
        detail: `основных кнопок в main: ${primary}`,
      })
    }
    const text = document.body.innerText
    for (const pattern of [/\bundefined\b/, /\bNaN\b/, /\[object Object\]/, /\{[a-z_]+\}/, /\bnull\b/]) {
      const match = pattern.exec(text)
      if (match) issues.push({ check: 'G17', selector: 'body', detail: `в тексте страницы есть «${match[0]}»` })
    }
    return issues
  }, limit)
}

/**
 * G13. Область нажатия не меньше 44 × 44 px. Учитывается невидимое расширение области (`.tap-target::after`).
 * Ссылки внутри текста исключены (исключение WCAG 2.5.8 для инлайновых целей).
 */
export async function checkTapTargets(page: Page, minSize = 44): Promise<Issue[]> {
  return page.evaluate((min) => {
    const issues: { check: string; selector: string; detail: string }[] = []
    const selector =
      'a[href], button, input:not([type="hidden"]), select, textarea, [role="button"], [role="checkbox"], [role="radio"], [role="switch"], [role="tab"], [role="combobox"]'
    for (const el of Array.from(document.querySelectorAll<HTMLElement>(selector))) {
      const style = getComputedStyle(el)
      if (style.display === 'none' || style.visibility === 'hidden' || el.closest('[aria-hidden="true"]')) continue
      const rect = el.getBoundingClientRect()
      if (rect.width < 1 || rect.height < 1) continue
      if (style.position === 'absolute' && el.clientWidth <= 1 && el.clientHeight <= 1) continue
      if (el.tagName === 'A' && style.display.startsWith('inline') && el.closest('p, li, dd, label, figcaption'))
        continue
      const after = getComputedStyle(el, '::after')
      const afterWidth =
        after.content !== 'none' && after.position === 'absolute' ? Number.parseFloat(after.width) || 0 : 0
      const afterHeight =
        after.content !== 'none' && after.position === 'absolute' ? Number.parseFloat(after.height) || 0 : 0
      // Поле внутри подписи или обёртки, которая передаёт ему нажатие ([data-tap-area]): считается вся обёртка.
      const label = el.closest('label, [data-tap-area]')?.getBoundingClientRect()
      const width = Math.max(rect.width, afterWidth, label?.width ?? 0)
      const height = Math.max(rect.height, afterHeight, label?.height ?? 0)
      if (width < min - 0.5 || height < min - 0.5) {
        const name = (el.getAttribute('aria-label') || el.textContent || el.tagName).trim().slice(0, 40)
        issues.push({
          check: 'G13',
          selector: `${el.tagName.toLowerCase()}${el.id ? `#${el.id}` : ''}`,
          detail: `область нажатия ${Math.round(width)} × ${Math.round(height)} px: «${name}»`,
        })
      }
    }
    return issues
  }, minSize)
}

/**
 * G14. Элемент в фокусе не перекрыт липкой шапкой и панелью действий: после фокуса (браузер сам прокручивает
 * страницу с учётом scroll-padding) центр элемента должен принадлежать ему самому.
 */
export async function checkFocusNotCovered(page: Page, limit = 200): Promise<Issue[]> {
  return page.evaluate(async (max) => {
    const issues: { check: string; selector: string; detail: string }[] = []
    const focusable = Array.from(
      document.querySelectorAll<HTMLElement>(
        'main a[href], main button:not([disabled]), main input:not([disabled]):not([type="hidden"]), main select, main textarea, main [tabindex="0"]',
      ),
    ).filter((el) => {
      const style = getComputedStyle(el)
      return (
        style.display !== 'none' && style.visibility !== 'hidden' && !el.closest('[data-sticky], [aria-hidden="true"]')
      )
    })
    for (const el of focusable.slice(0, max)) {
      el.focus()
      await new Promise((resolve) => requestAnimationFrame(() => resolve(null)))
      const rect = el.getBoundingClientRect()
      if (rect.width < 1 || rect.height < 1) continue
      const x = Math.min(window.innerWidth - 1, Math.max(0, rect.left + rect.width / 2))
      const y = Math.min(window.innerHeight - 1, Math.max(0, rect.top + rect.height / 2))
      const top = document.elementFromPoint(x, y)
      if (!top) continue
      const sticky = top.closest('[data-sticky]')
      if (sticky && !sticky.contains(el)) {
        const name = (el.getAttribute('aria-label') || el.textContent || el.tagName).trim().slice(0, 40)
        issues.push({
          check: 'G14',
          selector: `${el.tagName.toLowerCase()}${el.id ? `#${el.id}` : ''}`,
          detail: `элемент в фокусе перекрыт липкой панелью: «${name}»`,
        })
      }
    }
    ;(document.activeElement as HTMLElement | null)?.blur()
    window.scrollTo(0, 0)
    return issues
  }, limit)
}

/** G9. axe: контраст, имена полей, кнопок и ссылок, корректность ARIA (WCAG 2.2 AA). */
export async function checkAxe(page: Page): Promise<Issue[]> {
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
    .analyze()
  return results.violations.flatMap((violation) =>
    violation.nodes.map((node) => ({
      check: `G9 ${violation.id}`,
      selector: node.target.join(' '),
      detail: `${violation.help}${node.failureSummary ? ` — ${node.failureSummary.replace(/\s+/g, ' ').slice(0, 200)}` : ''}`,
    })),
  )
}

export type LayoutChecks = {
  /** Сколько кнопок primary допустимо в main (по умолчанию одна). */
  primaryLimit?: number
  /** Проверять область нажатия (G13) — на ширине 375. */
  tapTargets?: boolean
  /** Проверять перекрытие фокуса липкими панелями (G14). */
  focus?: boolean
  /** Запускать axe (G9). */
  axe?: boolean
}

/** Все проверки страницы разом; возвращает список замечаний. */
export async function collectLayoutIssues(page: Page, checks: LayoutChecks = {}): Promise<Issue[]> {
  await settle(page)
  const issues: Issue[] = []
  issues.push(...(await checkNoHorizontalScroll(page)))
  issues.push(...(await checkText(page)))
  issues.push(...(await checkStructure(page, { primaryLimit: checks.primaryLimit })))
  if (checks.tapTargets) issues.push(...(await checkTapTargets(page)))
  if (checks.axe ?? true) issues.push(...(await checkAxe(page)))
  if (checks.focus) issues.push(...(await checkFocusNotCovered(page)))
  return issues
}

/** Проверить страницу и упасть со списком замечаний в формате чек-листа (E §9.4). */
export async function expectCleanLayout(page: Page, checks: LayoutChecks = {}): Promise<void> {
  const issues = await collectLayoutIssues(page, checks)
  const report = issues.map((issue) => `${issue.check} · ${issue.selector} · ${issue.detail}`).join('\n')
  expect(issues.length, `Замечания к вёрстке (${page.url()}, ширина ${page.viewportSize()?.width}):\n${report}\n`).toBe(
    0,
  )
}
