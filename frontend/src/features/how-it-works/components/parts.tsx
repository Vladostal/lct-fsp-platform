import { ArrowRight, type LucideIcon } from 'lucide-react'
import type * as React from 'react'
import { IconTile, type TileTone } from '@/components/app'
import { cn } from '@/lib/utils'

/* Стрелки между шагами слегка «подталкивают» вперёд, как на лендинге; без анимации (reduce) стоят на месте. */
const FLOW_CSS = `
@media (prefers-reduced-motion: no-preference){
  .hw-x{animation:hw-x 1.8s ease-in-out infinite}
}
@keyframes hw-x{0%,100%{transform:none}50%{transform:translateX(3px)}}
`

export type FlowStep = {
  icon: LucideIcon
  title: string
  text?: string
  tone?: TileTone
  extra?: React.ReactNode
}

const ROW = {
  md: { grid: 'md:grid-cols-3 md:gap-7', arrow: 'md:flex' },
  lg5: { grid: 'lg:grid-cols-5 lg:gap-7', arrow: 'lg:flex' },
  lg6: { grid: 'lg:grid-cols-6 lg:gap-7', arrow: 'lg:flex' },
} as const

/**
 * Нумерованный поток карточек-шагов: плитка со значком, номер, заголовок и короткая подпись. Когда шаги
 * встают в один ряд (`row`), между ними появляются стрелки; на узком экране порядок несёт номер.
 */
export function Flow({
  label,
  steps,
  row,
  compact = false,
}: {
  label: string
  steps: readonly FlowStep[]
  row: keyof typeof ROW
  /** Шаги без подписи: низкая карточка в одну строку (плитка, номер, название), две колонки уже на телефоне. */
  compact?: boolean
}) {
  return (
    <>
      <style>{FLOW_CSS}</style>
      <ol
        aria-label={label}
        className={cn('grid min-w-0 gap-3', compact ? 'grid-cols-2 sm:grid-cols-3' : 'sm:grid-cols-2', ROW[row].grid)}
      >
        {steps.map((step, index) => (
          <li
            key={step.title}
            style={{ '--i': index } as React.CSSProperties}
            className={cn(
              'surface-row stagger relative flex min-w-0 animate-rise-in flex-col',
              compact ? 'gap-2 p-3 sm:flex-row sm:items-center sm:gap-2.5' : 'gap-2.5 p-4',
            )}
          >
            {compact ? (
              <>
                <IconTile icon={step.icon} tone={step.tone ?? 'brand'} />
                <p className="flex min-w-0 flex-col">
                  <span aria-hidden="true" className="num text-sm leading-5 font-semibold text-brand-700">
                    {String(index + 1).padStart(2, '0')}
                  </span>
                  <span className="type-sm min-w-0 font-semibold break-words text-ink">{step.title}</span>
                </p>
              </>
            ) : (
              <>
                <div className="flex items-center justify-between gap-2">
                  <IconTile icon={step.icon} tone={step.tone ?? 'brand'} />
                  <span aria-hidden="true" className="num text-2xl leading-none font-semibold text-brand-600">
                    {String(index + 1).padStart(2, '0')}
                  </span>
                </div>
                <p className="type-sm min-w-0 font-semibold break-words text-ink">{step.title}</p>
                {step.text ? <p className="type-sm min-w-0 break-words text-ink-muted">{step.text}</p> : null}
                {step.extra}
              </>
            )}
            {index < steps.length - 1 ? (
              <span
                aria-hidden="true"
                className={cn(
                  'absolute top-1/2 -right-[23px] hidden size-[18px] -translate-y-1/2 items-center justify-center text-brand-600',
                  ROW[row].arrow,
                )}
              >
                <ArrowRight className="hw-x size-[18px]" />
              </span>
            ) : null}
          </li>
        ))}
      </ol>
    </>
  )
}

/** Шапка раздела: крупная плитка, заголовок-якорь и один абзац сути. */
export function SectionHead({ id, icon, title, lead }: { id: string; icon: LucideIcon; title: string; lead: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-3">
      <div className="flex min-w-0 items-center gap-3 md:gap-4">
        <IconTile icon={icon} tone="solid" size="xl" />
        <h2 id={id} className="type-h1 min-w-0 scroll-mt-24 text-ink">
          {title}
        </h2>
      </div>
      <p className="type-body max-w-[76ch] min-w-0 break-words text-ink-muted">{lead}</p>
    </div>
  )
}

/** Белая карточка-факт: плитка, заголовок (или крупное число с подписью) и содержимое. */
export function FactCard({
  icon,
  tone = 'brand',
  title,
  value,
  label,
  children,
  className,
}: {
  icon: LucideIcon
  tone?: TileTone
  title?: string
  value?: string
  label?: string
  children?: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn('surface-row flex min-w-0 flex-col gap-3 p-4', className)}>
      <div className="flex min-w-0 items-center gap-3">
        <IconTile icon={icon} tone={tone} />
        {value ? (
          <p className="flex min-w-0 flex-col">
            <span className="num text-2xl leading-7 font-semibold text-ink">{value}</span>
            {label ? <span className="type-caption text-ink-muted">{label}</span> : null}
          </p>
        ) : (
          <p className="type-h3 min-w-0 break-words text-ink">{title}</p>
        )}
      </div>
      {children}
    </div>
  )
}
