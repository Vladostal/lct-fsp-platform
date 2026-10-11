import { ChevronRight, type LucideIcon } from 'lucide-react'
import type * as React from 'react'
import { Children, Fragment } from 'react'
import { cn } from '@/lib/utils'

type StageTone = 'brand' | 'deep' | 'success' | 'warning' | 'danger' | 'neutral'

const STAGE: Record<StageTone, { cell: string; icon: string; bar: string }> = {
  brand: { cell: 'bg-brand-100', icon: 'text-brand-600', bar: 'bg-brand-600' },
  deep: { cell: 'bg-brand-100', icon: 'text-brand-900 dark:text-brand-700', bar: 'bg-(--chart-brand-deep)' },
  success: { cell: 'bg-success-bg', icon: 'text-success', bar: 'bg-success' },
  warning: { cell: 'bg-warning-bg', icon: 'text-warning', bar: 'bg-warning' },
  danger: { cell: 'bg-danger-bg', icon: 'text-danger', bar: 'bg-danger' },
  neutral: { cell: 'bg-fill', icon: 'text-ink-muted', bar: 'bg-line-strong' },
}

export type StageCellProps = {
  icon: LucideIcon
  /** Ноль рисуется прочерком в пунктирной ячейке без заливки: «ещё нет». */
  value: number
  /** Подпись в одно слово. */
  label: string
  /** Доля от предыдущей ступени (0…1): полоса по нижнему краю. У первой ступени не задаётся. */
  share?: number
  /** Текст доли для скринридера, например «12 % от предыдущей ступени». */
  shareText?: (percent: number) => string
  tone?: StageTone
  /** Порядок появления полосы (stagger). */
  index?: number
  className?: string
}

/**
 * Ступень пайплайна: цветная ячейка — значок, число, подпись в одно слово. Полоса по нижнему краю —
 * конверсия из предыдущей ступени; доля ограничена единицей.
 */
export function StageCell({
  icon: Icon,
  value,
  label,
  share,
  shareText,
  tone = 'brand',
  index = 0,
  className,
}: StageCellProps) {
  const on = value > 0
  const t = STAGE[tone]
  const pct = share === undefined ? null : Math.round(Math.min(1, Math.max(0, share)) * 100)
  return (
    <li
      data-slot="stage-cell"
      className={cn(
        'relative flex min-w-0 flex-1 flex-col gap-1 overflow-hidden rounded-md border px-2 pt-2.5 pb-3 sm:px-3',
        on ? `border-transparent ${t.cell}` : 'border-dashed border-line-strong',
        className,
      )}
    >
      <span className="flex min-w-0 items-center gap-1.5">
        <Icon aria-hidden="true" className={cn('size-4', on ? t.icon : 'text-ink-subtle')} />
        {on ? (
          <span className="num text-xl leading-6 font-semibold text-ink">{value}</span>
        ) : (
          <>
            <span aria-hidden="true" className="num text-xl leading-6 font-semibold text-ink-muted">
              –
            </span>
            <span className="sr-only">0</span>
          </>
        )}
      </span>
      <span className="text-[0.6875rem] leading-4 tracking-tight text-ink-muted sm:text-xs sm:tracking-normal">
        {label}
      </span>
      {on && pct !== null ? (
        <>
          {shareText ? <span className="sr-only">{shareText(pct)}</span> : null}
          <span aria-hidden="true" className="absolute inset-x-0 bottom-0 block h-1.5 bg-surface/70">
            <span
              className={cn('stagger block h-full origin-left animate-grow-x rounded-r-full', t.bar)}
              style={{ width: `${pct}%`, minWidth: 6, '--i': index + 2 } as React.CSSProperties}
            />
          </span>
        </>
      ) : null}
    </li>
  )
}

export type PipelineProps = {
  /** Имя списка ступеней для скринридера. */
  label: string
  /** Набор `StageCell`; стрелки между ними ставятся сами (видны от 640 px). */
  children: React.ReactNode
  className?: string
}

/** Пайплайн: ряд ячеек-ступеней слева направо со стрелками между ними. */
export function Pipeline({ label, children, className }: PipelineProps) {
  const cells = Children.toArray(children)
  return (
    <ol data-slot="pipeline" aria-label={label} className={cn('flex min-w-0 items-stretch gap-1.5', className)}>
      {cells.map((cell, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: порядок ступеней постоянен
        <Fragment key={i}>
          {i > 0 ? (
            <ChevronRight aria-hidden="true" className="hidden size-4 shrink-0 self-center text-line-strong sm:block" />
          ) : null}
          {cell}
        </Fragment>
      ))}
    </ol>
  )
}

export type DashedNoteProps = {
  icon?: LucideIcon
  children: React.ReactNode
  className?: string
}

/** Пунктирная заглушка «ещё нет» на месте визуального блока карточки: значок и два-три слова. */
export function DashedNote({ icon: Icon, children, className }: DashedNoteProps) {
  return (
    <p
      data-slot="dashed-note"
      className={cn(
        'flex min-h-[4.25rem] min-w-0 items-center justify-center gap-2 rounded-md border border-dashed border-line-strong px-3 text-sm text-ink-muted',
        className,
      )}
    >
      {Icon ? <Icon aria-hidden="true" className="size-4 shrink-0" /> : null}
      {children}
    </p>
  )
}
