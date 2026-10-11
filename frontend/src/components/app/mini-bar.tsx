import { ArrowDown, type LucideIcon } from 'lucide-react'
import type * as React from 'react'
import { cn } from '@/lib/utils'
import { IconTile } from './icon-tile'
import { CHART, type ChartColor, ICON_TONE, type TileTone, type Tone } from './tone'

/** Заливка строки легенды по тону; у brand — самая светлая ступень, чтобы строка не спорила с кнопками. */
const ROW_TONE: Record<Tone, string> = {
  brand: 'bg-brand-50',
  success: 'bg-success-bg',
  warning: 'bg-warning-bg',
  danger: 'bg-danger-bg',
  neutral: 'bg-fill',
}

export type MiniBarProps = {
  label: string
  value: number
  /** Значение, принятое за полную ширину; по умолчанию полоса заполнена целиком. */
  max?: number
  /** Цвет полосы из набора графики. */
  color?: ChartColor
  /** `sm` — полоса 6 px и число 14 px (перечни причин), `lg` — полоса 12 px и число 20 px (ступени воронки). */
  size?: 'sm' | 'lg'
  /** Порядок появления (stagger). */
  index?: number
  className?: string
}

/** Мини-полоса: подпись, число и пропорциональная полоса под ними. Для коротких распределений в карточке. */
export function MiniBar({ label, value, max, color = 'brand', size = 'sm', index = 0, className }: MiniBarProps) {
  const width = max === undefined ? 100 : Math.min(100, (value / Math.max(max, 1)) * 100)
  const lg = size === 'lg'
  return (
    <div data-slot="mini-bar" className={cn('flex min-w-0 flex-col', lg ? 'gap-1.5' : 'gap-1', className)}>
      <div className="flex min-w-0 items-baseline justify-between gap-3">
        <span title={label} className={cn('type-sm min-w-0 truncate', lg ? 'text-ink-muted' : 'text-ink')}>
          {label}
        </span>
        <span className={cn('num font-semibold text-ink', lg ? 'text-xl leading-6' : 'type-sm')}>{value}</span>
      </div>
      <span aria-hidden="true" className={cn('block overflow-hidden rounded-full bg-fill', lg ? 'h-3' : 'h-1.5')}>
        <span
          className="stagger block h-full origin-left animate-grow-x rounded-full"
          style={{ width: `${width}%`, backgroundColor: CHART[color], '--i': index * 2 } as React.CSSProperties}
        />
      </span>
    </div>
  )
}

export type FunnelBarsStep = {
  key: string
  label: string
  value: number
  icon: LucideIcon
  tone?: TileTone
  color?: ChartColor
}

export type FunnelBarsProps = {
  /** Имя воронки для скринридера. */
  label: string
  /** Ступени сверху вниз; ширина полосы — доля от первой ступени. */
  steps: readonly FunnelBarsStep[]
  /** Слово перед процентом для скринридера («конверсия»). */
  conversionLabel?: string
  className?: string
}

/**
 * Вертикальная воронка: у каждой ступени плитка со значком, подпись, число и полоса; между ступенями —
 * плашка с конверсией из предыдущей. Без знаменателя плашки нет.
 */
export function FunnelBars({ label, steps, conversionLabel, className }: FunnelBarsProps) {
  const base = Math.max(steps[0]?.value ?? 0, 1)
  return (
    <ol data-slot="funnel-bars" className={cn('flex min-w-0 flex-col', className)} aria-label={label}>
      {steps.map((step, i) => {
        const prev = steps[i - 1]
        return (
          <li key={step.key} className="flex min-w-0 flex-col">
            {prev ? (
              <div className="flex h-9 items-center gap-3">
                <span aria-hidden="true" className="flex w-10 shrink-0 justify-center self-stretch">
                  <span className="w-px bg-line-strong/40" />
                </span>
                {prev.value > 0 ? (
                  <span className="num type-caption inline-flex items-center gap-1 rounded-full bg-fill px-2 py-0.5 font-medium text-ink">
                    <ArrowDown aria-hidden="true" className="size-3 text-ink-muted" />
                    {conversionLabel ? <span className="sr-only">{conversionLabel} </span> : null}
                    {Math.round((Math.min(step.value, prev.value) / prev.value) * 100)} %
                  </span>
                ) : null}
              </div>
            ) : null}
            <div className="flex min-w-0 items-center gap-3">
              <IconTile icon={step.icon} tone={step.tone ?? 'brand'} />
              <MiniBar
                size="lg"
                label={step.label}
                value={step.value}
                max={base}
                color={step.color ?? 'brand'}
                index={i}
                className="flex-1"
              />
            </div>
          </li>
        )
      })}
    </ol>
  )
}

export type LegendItem = {
  key: string
  label: string
  value: number
  icon: LucideIcon
  /** Тон строки; `dashed` — вне графика («не дошло», «ещё нет»): пунктир без заливки и без маркера. */
  tone: Tone | 'dashed'
  /** Цвет маркера — тот же, что у сегмента графика. По умолчанию — цвет тона. */
  color?: ChartColor
}

export type LegendListProps = {
  items: readonly LegendItem[]
  className?: string
}

/** Легенда графика строками-плашками: маркер цвета сегмента, значок, подпись, число. Нулевая строка гаснет. */
export function LegendList({ items, className }: LegendListProps) {
  return (
    <ul data-slot="legend-list" className={cn('flex min-w-40 flex-1 flex-col gap-1.5', className)}>
      {items.map((o) => {
        const dashed = o.tone === 'dashed'
        const zero = o.value === 0
        return (
          <li
            key={o.key}
            className={cn(
              'flex h-8 min-w-0 items-center gap-2 rounded-md border border-transparent px-2.5',
              dashed ? 'border-dashed border-line-strong' : zero ? 'bg-fill' : ROW_TONE[o.tone as Tone],
            )}
          >
            {dashed ? null : (
              <span
                aria-hidden="true"
                className={cn('h-4 w-1 shrink-0 rounded-full', zero && 'opacity-40')}
                style={{ backgroundColor: CHART[o.color ?? (o.tone as Tone)] }}
              />
            )}
            <o.icon
              aria-hidden="true"
              className={cn('size-4 shrink-0', zero || dashed ? 'text-ink-muted' : ICON_TONE[o.tone as Tone])}
            />
            <span title={o.label} className="type-sm min-w-0 flex-1 truncate text-ink">
              {o.label}
            </span>
            <span className={cn('num type-sm font-semibold', zero ? 'text-ink-muted' : 'text-ink')}>{o.value}</span>
          </li>
        )
      })}
    </ul>
  )
}
