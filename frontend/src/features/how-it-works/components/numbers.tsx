import type { ExpertStatus } from '@/client'
import { formatDecimal } from '@/lib/format'
import { HOW } from '../content'

export type Metric = { label: string; value: number | null | undefined; kind?: 'share' | 'plain' }

function show(m: Metric): string | null {
  if (m.value == null) return null
  if (m.kind === 'plain') return formatDecimal(m.value)
  return `${formatDecimal(Math.round(m.value * 1000) / 10)} %`
}

type Props = {
  title: string
  metrics: Metric[]
  /** Сколько прогонов в выборке: показывается рядом с числами. */
  n?: number | null
  expert?: ExpertStatus | null
  note?: string
}

/** Блок чисел отчёта: строки без значения скрываются без пустого места; пустой блок не рисуется. */
export function Numbers({ title, metrics, n, expert, note }: Props) {
  const rows = metrics.map((m) => ({ m, v: show(m) })).filter((r): r is { m: Metric; v: string } => r.v !== null)
  if (rows.length === 0) return null
  return (
    <section className="surface-card flex min-w-0 flex-col gap-3 p-5" aria-label={title}>
      <h3 className="type-h3">{title}</h3>
      <dl className="grid min-w-0 gap-x-6 gap-y-3 sm:grid-cols-2">
        {rows.map(({ m, v }) => (
          <div key={m.label} className="min-w-0">
            <dt className="type-sm min-w-0 break-words text-ink-muted">{m.label}</dt>
            <dd className="type-h2 num">{v}</dd>
          </div>
        ))}
      </dl>
      <p className="type-caption min-w-0 break-words text-ink-muted">
        {expert ? HOW.simNote(HOW.expert[expert.e1] ?? expert.e1) : 'получено симуляцией'}
        {n ? ` · выборка: ${n}` : ''}
        {note ? ` · ${note}` : ''}
      </p>
    </section>
  )
}
