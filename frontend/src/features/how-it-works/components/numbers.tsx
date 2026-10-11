import { BarChart3, FlaskConical, type LucideIcon, ScanSearch, Users } from 'lucide-react'
import type * as React from 'react'
import type { ExpertStatus } from '@/client'
import { CHART, IconTile, SoftPill, StatTile, type TileTone } from '@/components/app'
import { formatDecimal, formatNumber } from '@/lib/format'
import { cn } from '@/lib/utils'
import { HOW } from '../content'

export type Metric = {
  label: string
  value: number | null | undefined
  kind?: 'share' | 'plain'
  icon: LucideIcon
  tone?: TileTone
}

function show(m: Metric): string | null {
  if (m.value == null) return null
  if (m.kind === 'plain') return formatDecimal(m.value)
  return `${formatDecimal(Math.round(m.value * 1000) / 10)} %`
}

type Row = { m: Metric; v: string }

type Props = {
  title: string
  metrics: Metric[]
  /** Сколько прогонов в выборке: показывается рядом с числами. */
  n?: number | null
  expert?: ExpertStatus | null
  note?: string
  /** Доли рисуются полосами для сравнения: первая — наш результат (цвет бренда), остальные — бейзлайны. */
  bars?: boolean
}

/** Полоса доли: подпись, значение и пропорциональная заливка; `own` выделяет наш порядок среди бейзлайнов. */
function ShareBar({ row, own, index }: { row: Row; own: boolean; index: number }) {
  const width = Math.min(100, Math.max(0, (row.m.value ?? 0) * 100))
  return (
    <li className="flex min-w-0 items-center gap-3">
      <IconTile icon={row.m.icon} tone={own ? 'solid' : 'neutral'} />
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <div className="flex min-w-0 items-baseline justify-between gap-3">
          <span
            className={
              own ? 'type-sm min-w-0 font-semibold break-words text-ink' : 'type-sm min-w-0 break-words text-ink-muted'
            }
          >
            {row.m.label}
          </span>
          <span className="num shrink-0 text-xl leading-6 font-semibold text-ink">{row.v}</span>
        </div>
        <span aria-hidden="true" className="block h-3 overflow-hidden rounded-full bg-fill">
          <span
            className="stagger block h-full origin-left animate-grow-x rounded-full"
            style={
              {
                width: `${width}%`,
                backgroundColor: own ? CHART.brand : CHART.brandSoft,
                '--i': index * 2,
              } as React.CSSProperties
            }
          />
        </span>
      </div>
    </li>
  )
}

/** Блок чисел отчёта: строки без значения скрываются без пустого места; пустой блок не рисуется. */
export function Numbers({ title, metrics, n, expert, note, bars = false }: Props) {
  const rows = metrics.map((m) => ({ m, v: show(m) })).filter((r): r is Row => r.v !== null)
  if (rows.length === 0) return null
  const barRows = bars ? rows.filter((r) => r.m.kind !== 'plain') : []
  const tileRows = bars ? rows.filter((r) => r.m.kind === 'plain') : rows
  return (
    <section className="brand-band surface-row flex min-w-0 flex-col gap-5 p-4 md:p-6" aria-label={title}>
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <h3 className="type-eyebrow flex min-w-0 items-center gap-2">
          <BarChart3 aria-hidden="true" className="size-4 shrink-0 text-brand-700" />
          {title}
        </h3>
        <p className="flex min-w-0 flex-wrap items-center gap-1.5">
          <SoftPill size="sm" tone="brand" icon={FlaskConical}>
            {HOW.sim}
          </SoftPill>
          {n ? (
            <SoftPill size="sm" icon={Users}>
              <span className="num">{HOW.sample(n).replace(String(n), formatNumber(n))}</span>
            </SoftPill>
          ) : null}
          {expert ? (
            <SoftPill size="sm" icon={ScanSearch} className="h-auto min-h-6 shrink py-0.5">
              {HOW.expertLabel(HOW.expert[expert.e1] ?? expert.e1)}
            </SoftPill>
          ) : null}
        </p>
      </div>
      {barRows.length > 0 ? (
        <ul className="flex min-w-0 flex-col gap-4">
          {barRows.map((r, i) => (
            <ShareBar key={r.m.label} row={r} own={i === 0} index={i} />
          ))}
        </ul>
      ) : null}
      {tileRows.length > 0 ? (
        <ul
          className={cn(
            'grid min-w-0 gap-x-6 gap-y-5 sm:grid-cols-2',
            tileRows.length % 3 === 0 ? 'lg:grid-cols-3' : 'lg:grid-cols-4',
          )}
        >
          {tileRows.map(({ m, v }) => (
            <li key={m.label} className="min-w-0">
              <StatTile icon={m.icon} tone={m.tone ?? 'brand'} value={v} label={m.label} className="shrink" />
            </li>
          ))}
        </ul>
      ) : null}
      {note ? <p className="type-caption min-w-0 break-words text-ink-muted">{note}</p> : null}
    </section>
  )
}
