import { CircleCheck, CircleX, Clock, Eye, Hourglass, MailX, Send, Timer, Undo2 } from 'lucide-react'
import type { InvitationStatsView } from '@/client'
import {
  FunnelBars,
  type FunnelBarsStep,
  type LegendItem,
  LegendList,
  MiniBar,
  ProgressRing,
  type RingSegment,
  Section,
  StatTile,
} from '@/components/app'
import { DASHBOARD as T } from './content'

function Reasons({ reasons }: { reasons: InvitationStatsView['reasons'] }) {
  if (reasons.length === 0) return null
  const sorted = [...reasons].sort((a, b) => b.count - a.count)
  const max = Math.max(...sorted.map((r) => r.count), 1)
  return (
    <Section as="h3" title={T.reasons} icon={CircleX} iconTone="danger" className="gap-2.5">
      <ul className="flex min-w-0 flex-col gap-2.5">
        {sorted.map((r, i) => (
          <li key={r.reason_code} className="min-w-0">
            <MiniBar label={r.reason_label} value={r.count} max={max} color="danger" index={i} />
          </li>
        ))}
      </ul>
    </Section>
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

  const steps: FunnelBarsStep[] = [
    { key: 'delivered', label: T.delivered, value: delivered, icon: Send, tone: 'soft', color: 'brandSoft' },
    { key: 'viewed', label: T.viewed, value: viewed, icon: Eye, tone: 'brand', color: 'brand' },
    { key: 'accepted', label: T.accepted, value: accepted, icon: CircleCheck, tone: 'success', color: 'success' },
  ]
  // Кольцо исходов: доли доставленных приглашений. В центре — принято из доставленных.
  const slices: (RingSegment & { label: string })[] = [
    { key: 'accepted', label: T.accepted, value: accepted, color: 'success' },
    { key: 'waiting', label: T.waiting, value: waiting, color: 'brandSoft' },
    { key: 'declined', label: T.declined, value: declined, color: 'danger' },
    { key: 'expired', label: T.expired, value: expired, color: 'warning' },
    { key: 'withdrawn', label: T.withdrawn, value: withdrawn, color: 'neutral' },
  ]
  const ringLabel = slices
    .map((s) => `${s.label.toLowerCase()} ${s.value}${s.key === 'accepted' ? ` ${T.of} ${delivered}` : ''}`)
    .join(', ')
  const outcomes: LegendItem[] = [
    { key: 'accepted', label: T.accepted, value: accepted, icon: CircleCheck, tone: 'success' },
    { key: 'waiting', label: T.waiting, value: waiting, icon: Hourglass, tone: 'warning', color: 'brandSoft' },
    { key: 'declined', label: T.declined, value: declined, icon: CircleX, tone: 'danger' },
    { key: 'expired', label: T.expired, value: expired, icon: Clock, tone: 'warning' },
    { key: 'withdrawn', label: T.withdrawn, value: withdrawn, icon: Undo2, tone: 'neutral' },
    // Вне кольца: до кандидата не дошло, поэтому строка без заливки, с пунктиром.
    { key: 'not_delivered', label: T.notDelivered, value: notDelivered, icon: MailX, tone: 'dashed' },
  ]

  return (
    <div className="grid min-w-0 gap-6 md:grid-cols-2 md:gap-8 lg:grid-cols-[1.25fr_1fr_0.85fr]">
      {/* На планшете воронка во всю ширину, исходы и время ответа — парой под ней. */}
      <div className="min-w-0 md:max-lg:col-span-2">
        <FunnelBars label={T.funnel} steps={steps} conversionLabel={T.conversion} />
      </div>
      <div className="flex min-w-0 flex-wrap items-center justify-center gap-5 border-line max-lg:border-t max-lg:pt-6 lg:border-l lg:pl-8">
        <ProgressRing label={`${T.outcomes}: ${ringLabel}`} segments={slices} className="size-32 animate-pop-in">
          <span className="num inline-flex items-center gap-1 text-2xl leading-7 font-semibold text-ink">
            <CircleCheck aria-hidden="true" className="size-4 text-success" />
            {accepted}
          </span>
          <span className="num type-caption text-ink-muted">
            {T.of} {delivered}
          </span>
        </ProgressRing>
        <LegendList items={outcomes} />
      </div>
      <div className="flex min-w-0 flex-col gap-5 border-line max-lg:border-t max-lg:pt-6 lg:border-l lg:pl-8">
        <StatTile
          icon={Timer}
          tone="soft"
          size="lg"
          value={median == null ? T.none : `${Math.round(median)} ${T.hours}`}
          label={T.median}
        />
        <div className="min-w-0 flex-1">
          <Reasons reasons={stats.reasons} />
        </div>
      </div>
    </div>
  )
}
