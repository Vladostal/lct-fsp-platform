/**
 * Тона общих визуальных блоков. Смысл один на всех экранах:
 *  - brand   — платформа, основное действие, «в работе»;
 *  - success — принято, подтверждено, зарплата;
 *  - warning — ждёт ответа, истекает;
 *  - danger  — отклонено, не пройдено;
 *  - neutral — отозвано, неактивно.
 * Пустое («ещё нет») — не тон, а пунктирная рамка без заливки (`dashed`).
 */
export type Tone = 'brand' | 'success' | 'warning' | 'danger' | 'neutral'

/**
 * Тон плитки со значком: общие тона и оттенки бренда для категорий без статусного смысла.
 * `solid` — заливка brand-600, `soft` — brand-50, `deep` — brand-200, `ink` — brand-900,
 * `accent` — красный маркер ФСП, `plain` — белая на сером фоне, `dashed` — пунктир («ещё нет»).
 */
export type TileTone = Tone | 'solid' | 'soft' | 'deep' | 'ink' | 'accent' | 'plain' | 'dashed'

export const TILE_TONE: Record<TileTone, string> = {
  brand: 'bg-brand-100 text-brand-700',
  soft: 'bg-brand-50 text-brand-700',
  solid: 'bg-brand-600 text-on-brand',
  deep: 'bg-brand-200 text-brand-900 dark:text-brand-700',
  ink: 'bg-brand-900 text-on-brand',
  accent: 'bg-[color-mix(in_srgb,var(--color-fsp-red)_12%,var(--color-surface))] text-fsp-red',
  success: 'bg-success-bg text-success',
  warning: 'bg-warning-bg text-warning',
  danger: 'bg-danger-bg text-danger',
  neutral: 'bg-fill text-ink',
  plain: 'bg-surface text-ink-muted',
  dashed: 'border border-dashed border-line-strong bg-surface text-ink-muted',
}

/** Мягкая заливка с текстом тона: плашки, счётчики, строки легенды. */
export const SOFT_TONE: Record<Tone, string> = {
  brand: 'bg-brand-50 text-brand-700',
  success: 'bg-success-bg text-success',
  warning: 'bg-warning-bg text-warning',
  danger: 'bg-danger-bg text-danger',
  neutral: 'bg-fill text-ink-muted',
}

/** Цвет значка на белом или на мягкой заливке своего тона. */
export const ICON_TONE: Record<Tone, string> = {
  brand: 'text-brand-700',
  success: 'text-success',
  warning: 'text-warning',
  danger: 'text-danger',
  neutral: 'text-ink-muted',
}

/**
 * Цвета графики (полосы, сегменты кольца) — только из токенов. `brandSoft` и `warning` получены смешиванием:
 * у токенов нет средней ступени, а brand-200 и warning-bg на белом почти не видны. Текст ими не красится.
 */
export const CHART = {
  brand: 'var(--color-brand-600)',
  brandSoft: 'color-mix(in srgb, var(--color-brand-600) 45%, var(--color-surface))',
  brandDeep: 'var(--chart-brand-deep)',
  success: 'var(--color-success)',
  danger: 'var(--color-danger)',
  warning: 'color-mix(in srgb, var(--color-warning) 55%, var(--color-warning-bg))',
  neutral: 'var(--color-line-strong)',
} as const

export type ChartColor = keyof typeof CHART
