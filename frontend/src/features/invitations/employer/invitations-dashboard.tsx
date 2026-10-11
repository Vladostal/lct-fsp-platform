import {
  ArrowDown,
  CircleCheck,
  CircleX,
  Clock,
  Eye,
  Hourglass,
  type LucideIcon,
  MailX,
  Send,
  Timer,
  Undo2,
} from 'lucide-react'
import type { InvitationStatsView } from '@/client'
import { cn } from '@/lib/utils'
import { DASHBOARD as T } from './content'

/*
 * Цвета графики — только из токенов. Светлый фирменный и янтарный получены смешиванием: у токенов нет средней
 * ступени, а brand-200 и warning-bg на белом почти не видны. Текст этими цветами не красится.
 */
const C = {
  delivered: 'color-mix(in srgb, var(--color-brand-600) 45%, var(--color-surface))',
  viewed: 'var(--color-brand-600)',
  accepted: 'var(--color-success)',
  declined: 'var(--color-danger)',
  expired: 'color-mix(in srgb, var(--color-warning) 55%, var(--color-warning-bg))',
  withdrawn: 'var(--color-line-strong)',
} as const

/** Доля в процентах; при нулевом знаменателе — null (вместо NaN показывается прочерк). */
function percent(part: number, whole: number): number | null {
  if (whole <= 0) return null
  return Math.round((Math.min(part, whole) / whole) * 100)
}

function percentText(value: number | null): string {
  return value == null ? T.none : `${value} %`
}

type Step = { key: string; label: string; value: number; icon: LucideIcon; color: string; tile: string }

function Funnel({ steps }: { steps: Step[] }) {
  const base = Math.max(steps[0]?.value ?? 0, 1)
  return (
    <ol className="flex min-w-0 flex-col" aria-label={T.funnel}>
      {steps.map((step, i) => {
        const prev = steps[i - 1]
        const width = Math.min(100, (step.value / base) * 100)
        return (
          <li key={step.key} className="flex min-w-0 flex-col">
            {prev ? (
              <div className="flex h-9 items-center gap-3">
                <span aria-hidden="true" className="flex w-10 shrink-0 justify-center self-stretch">
                  <span className="w-px bg-line-strong/40" />
                </span>
                {/* Без знаменателя доли нет: плашка не показывается. */}
                <span
                  className={cn(
                    'num type-caption inline-flex items-center gap-1 rounded-full bg-fill px-2 py-0.5 font-medium text-ink',
                    prev.value <= 0 && 'hidden',
                  )}
                >
                  <ArrowDown aria-hidden="true" className="size-3 text-ink-muted" />
                  <span className="sr-only">{T.conversion} </span>
                  {percentText(percent(step.value, prev.value))}
                </span>
              </div>
            ) : null}
            <div className="flex min-w-0 items-center gap-3">
              <span
                aria-hidden="true"
                className={cn('flex size-10 shrink-0 items-center justify-center rounded-lg', step.tile)}
              >
                <step.icon className="size-5" />
              </span>
              <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                <div className="flex min-w-0 items-baseline justify-between gap-3">
                  <span className="type-sm min-w-0 truncate text-ink-muted">{step.label}</span>
                  <span className="num text-xl leading-6 font-semibold text-ink">{step.value}</span>
                </div>
                <span aria-hidden="true" className="block h-3 overflow-hidden rounded-full bg-fill">
                  <span
                    className="stagger block h-full origin-left animate-grow-x rounded-full"
                    style={{ width: `${width}%`, backgroundColor: step.color, ['--i' as string]: i * 2 }}
                  />
                </span>
              </div>
            </div>
          </li>
        )
      })}
    </ol>
  )
}

type Slice = { key: string; label: string; value: number; color: string }

/** Кольцо исходов: доли доставленных приглашений, между сегментами зазор. В центре — принято из доставленных. */
function OutcomeRing({ slices, accepted, delivered }: { slices: Slice[]; accepted: number; delivered: number }) {
  const total = slices.reduce((sum, s) => sum + s.value, 0)
  const visible = slices.filter((s) => s.value > 0)
  // Окружность нормирована к 100 через pathLength: длина сегмента равна его проценту.
  const gap = visible.length > 1 ? 1.5 : 0
  let offset = 0
  const arcs = visible.map((s) => {
    const length = (s.value / total) * 100
    const arc = { ...s, start: offset, length: Math.max(length - gap, 0.5) }
    offset += length
    return arc
  })
  const summary = slices
    .map((s) => `${s.label.toLowerCase()} ${s.value}${s.key === 'accepted' ? ` ${T.of} ${delivered}` : ''}`)
    .join(', ')
  return (
    <div className="relative size-32 shrink-0 animate-pop-in">
      <svg viewBox="0 0 120 120" className="size-full -rotate-90" role="img" aria-label={`${T.outcomes}: ${summary}`}>
        <circle cx="60" cy="60" r="50" fill="none" strokeWidth="12" stroke="var(--color-fill)" />
        {arcs.map((a) => (
          <circle
            key={a.key}
            cx="60"
            cy="60"
            r="50"
            fill="none"
            strokeWidth="12"
            pathLength={100}
            stroke={a.color}
            strokeDasharray={`${a.length} ${100 - a.length}`}
            strokeDashoffset={-a.start}
          />
        ))}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="num inline-flex items-center gap-1 text-2xl leading-7 font-semibold text-ink">
          <CircleCheck aria-hidden="true" className="size-4 text-success" />
          {accepted}
        </span>
        <span className="num type-caption text-ink-muted">
          {T.of} {delivered}
        </span>
      </div>
    </div>
  )
}

/** `color` — точный цвет сегмента кольца; у строки вне кольца его нет. */
type Outcome = {
  key: string
  label: string
  value: number
  icon: LucideIcon
  row: string
  iconColor: string
  color?: string
}

function OutcomeList({ items }: { items: Outcome[] }) {
  return (
    <ul className="flex min-w-40 flex-1 flex-col gap-1.5">
      {items.map((o) => (
        <li
          key={o.key}
          className={cn(
            'flex h-8 min-w-0 items-center gap-2 rounded-md border border-transparent px-2.5',
            o.row,
            // Нулевой исход не должен кричать цветом.
            o.value === 0 && o.color && 'bg-fill',
          )}
        >
          {o.color ? (
            <span
              aria-hidden="true"
              className={cn('h-4 w-1 shrink-0 rounded-full', o.value === 0 && 'opacity-40')}
              style={{ backgroundColor: o.color }}
            />
          ) : null}
          <o.icon
            aria-hidden="true"
            className={cn('size-4 shrink-0', o.value === 0 ? 'text-ink-muted' : o.iconColor)}
          />
          <span className="type-sm min-w-0 flex-1 truncate text-ink">{o.label}</span>
          <span className={cn('num type-sm font-semibold', o.value === 0 ? 'text-ink-muted' : 'text-ink')}>
            {o.value}
          </span>
        </li>
      ))}
    </ul>
  )
}

function Reasons({ reasons }: { reasons: InvitationStatsView['reasons'] }) {
  if (reasons.length === 0) return null
  const sorted = [...reasons].sort((a, b) => b.count - a.count)
  const max = Math.max(...sorted.map((r) => r.count), 1)
  return (
    <div className="flex min-w-0 flex-col gap-2.5">
      <h3 className="type-eyebrow flex items-center gap-1.5">
        <CircleX aria-hidden="true" className="size-3.5 text-danger" />
        {T.reasons}
      </h3>
      <ul className="flex min-w-0 flex-col gap-2.5">
        {sorted.map((r, i) => (
          <li key={r.reason_code} className="flex min-w-0 flex-col gap-1">
            <div className="flex min-w-0 items-baseline justify-between gap-3">
              <span className="type-sm min-w-0 truncate text-ink">{r.reason_label}</span>
              <span className="num type-sm font-semibold text-ink">{r.count}</span>
            </div>
            <span aria-hidden="true" className="block h-1.5 overflow-hidden rounded-full bg-fill">
              <span
                className="stagger block h-full origin-left animate-grow-x rounded-full"
                style={{ width: `${(r.count / max) * 100}%`, backgroundColor: C.declined, ['--i' as string]: i * 2 }}
              />
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Сводка приглашений: воронка, кольцо исходов, время ответа и причины отказов. Подписи — одно-два слова. */
export function InvitationsDashboard({ stats }: { stats: InvitationStatsView }) {
  const t = stats.total
  const delivered = t.delivered ?? 0
  const viewed = t.viewed ?? 0
  const accepted = t.accepted ?? 0
  const declined = t.declined ?? 0
  const expired = t.expired ?? 0
  const withdrawn = t.withdrawn ?? 0
  const notDelivered = t.not_delivered ?? 0
  // Ждут ответа: доставленные без исхода.
  const waiting = Math.max(0, delivered - accepted - declined - expired - withdrawn)
  const median = stats.median_response_hours

  const steps: Step[] = [
    {
      key: 'delivered',
      label: T.delivered,
      value: delivered,
      icon: Send,
      color: C.delivered,
      tile: 'bg-brand-50 text-brand-700',
    },
    { key: 'viewed', label: T.viewed, value: viewed, icon: Eye, color: C.viewed, tile: 'bg-brand-100 text-brand-700' },
    {
      key: 'accepted',
      label: T.accepted,
      value: accepted,
      icon: CircleCheck,
      color: C.accepted,
      tile: 'bg-success-bg text-success',
    },
  ]
  const slices: Slice[] = [
    { key: 'accepted', label: T.accepted, value: accepted, color: C.accepted },
    { key: 'waiting', label: T.waiting, value: waiting, color: C.delivered },
    { key: 'declined', label: T.declined, value: declined, color: C.declined },
    { key: 'expired', label: T.expired, value: expired, color: C.expired },
    { key: 'withdrawn', label: T.withdrawn, value: withdrawn, color: C.withdrawn },
  ]
  const outcomes: Outcome[] = [
    {
      key: 'accepted',
      label: T.accepted,
      value: accepted,
      icon: CircleCheck,
      row: 'bg-success-bg',
      iconColor: 'text-success',
      color: C.accepted,
    },
    {
      key: 'waiting',
      label: T.waiting,
      value: waiting,
      icon: Hourglass,
      row: 'bg-brand-50',
      iconColor: 'text-brand-700',
      color: C.delivered,
    },
    {
      key: 'declined',
      label: T.declined,
      value: declined,
      icon: CircleX,
      row: 'bg-danger-bg',
      iconColor: 'text-danger',
      color: C.declined,
    },
    {
      key: 'expired',
      label: T.expired,
      value: expired,
      icon: Clock,
      row: 'bg-warning-bg',
      iconColor: 'text-warning',
      color: C.expired,
    },
    {
      key: 'withdrawn',
      label: T.withdrawn,
      value: withdrawn,
      icon: Undo2,
      row: 'bg-fill',
      iconColor: 'text-ink-muted',
      color: C.withdrawn,
    },
    // Вне кольца: до кандидата не дошло, поэтому строка без заливки, с пунктиром.
    {
      key: 'not_delivered',
      label: T.notDelivered,
      value: notDelivered,
      icon: MailX,
      row: 'border-dashed border-line-strong',
      iconColor: 'text-ink-muted',
    },
  ]

  return (
    <div className="grid min-w-0 gap-6 md:grid-cols-2 md:gap-8 lg:grid-cols-[1.25fr_1fr_0.85fr]">
      {/* На планшете воронка во всю ширину, исходы и время ответа — парой под ней. */}
      <div className="min-w-0 md:max-lg:col-span-2">
        <Funnel steps={steps} />
      </div>
      <div className="flex min-w-0 flex-wrap items-center justify-center gap-5 border-line max-lg:border-t max-lg:pt-6 lg:border-l lg:pl-8">
        <OutcomeRing slices={slices} accepted={accepted} delivered={delivered} />
        <OutcomeList items={outcomes} />
      </div>
      <div className="flex min-w-0 flex-col gap-5 border-line max-lg:border-t max-lg:pt-6 lg:border-l lg:pl-8">
        <div className="flex min-w-0 shrink-0 items-center gap-3">
          <span
            aria-hidden="true"
            className="flex size-12 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-700"
          >
            <Timer className="size-6" />
          </span>
          <p className="flex min-w-0 flex-col">
            <span className="num text-3xl leading-9 font-semibold text-ink">
              {median == null ? T.none : `${Math.round(median)} ${T.hours}`}
            </span>
            <span className="type-caption text-ink-muted">{T.median}</span>
          </p>
        </div>
        <div className="min-w-0 flex-1">
          <Reasons reasons={stats.reasons} />
        </div>
      </div>
    </div>
  )
}
