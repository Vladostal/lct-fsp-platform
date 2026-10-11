import {
  Building2,
  CalendarDays,
  Circle,
  CircleCheck,
  CircleX,
  Clock,
  Eye,
  FlaskConical,
  type LucideIcon,
  MailOpen,
  MapPin,
  TrendingDown,
  Undo2,
} from 'lucide-react'
import type { InvitationStatus, TimelineEvent, WorkFormat } from '@/client'
import { FormatPill, IconTile, SalaryRange, SoftPill, type TileTone } from '@/components/app'
import { formatDateTime, initials } from '@/lib/format'
import { cn } from '@/lib/utils'

/*
 * Общие части экранов кандидата (обзор, список, приглашение): плитка компании, ряд условий, срок и ход
 * приглашения. Тона те же, что в списке приглашений работодателя.
 */

const TILE_TONES: Record<InvitationStatus, TileTone> = {
  sent: 'solid',
  viewed: 'solid',
  accepted: 'success',
  declined: 'danger',
  expired: 'warning',
  bounced: 'dashed',
  withdrawn: 'neutral',
}

/**
 * Код статуса для плашки кандидата: просмотренное приглашение у него «ждёт ответа» — песочные часы и янтарный
 * тон, как в сводке; глаз остаётся только у «Просмотрено» работодателя.
 */
export const candidateStatusCode = (status: InvitationStatus): string => (status === 'viewed' ? 'awaiting' : status)

/** Плитка компании: инициалы названия, цвет повторяет тон статуса приглашения. */
export function CompanyTile({
  name,
  status,
  size = 'lg',
}: {
  name: string
  status?: InvitationStatus
  size?: 'md' | 'lg' | 'xl'
}) {
  const text = initials(name)
  return (
    <IconTile tone={status ? TILE_TONES[status] : 'brand'} size={size} icon={text ? undefined : Building2}>
      {text || null}
    </IconTile>
  )
}

export type OfferFacts = {
  salary_from: number
  salary_to: number
  work_format: WorkFormat
  city?: string | null
  is_demo: boolean
  below_my_min: boolean
}

/** Условия предложения плашками: вилка (если не вынесена крупно), формат, город, пометки «демо» и «ниже минимума». */
export function OfferPills({
  offer,
  salary = true,
  className,
}: {
  offer: OfferFacts
  salary?: boolean
  className?: string
}) {
  return (
    <div className={cn('flex min-w-0 flex-wrap items-center gap-2', className)}>
      {salary ? (
        <SoftPill tone="success">
          <SalaryRange from={offer.salary_from} to={offer.salary_to} size="sm" className="text-success" />
        </SoftPill>
      ) : null}
      <FormatPill format={offer.work_format} />
      {offer.city ? (
        <SoftPill icon={MapPin} title={offer.city}>
          <span className="min-w-0 truncate">{offer.city}</span>
        </SoftPill>
      ) : null}
      {offer.is_demo ? <SoftPill icon={FlaskConical}>демо</SoftPill> : null}
      {offer.below_my_min ? (
        <SoftPill tone="warning" icon={TrendingDown}>
          ниже вашего минимума
        </SoftPill>
      ) : null}
    </div>
  )
}

const EVENT_VIEW: Record<string, { icon: LucideIcon; tone: TileTone }> = {
  sent: { icon: MailOpen, tone: 'brand' },
  viewed: { icon: Eye, tone: 'brand' },
  accepted: { icon: CircleCheck, tone: 'success' },
  declined: { icon: CircleX, tone: 'danger' },
  expired: { icon: Clock, tone: 'warning' },
  withdrawn: { icon: Undo2, tone: 'neutral' },
}

/** «Ход приглашения» глазами кандидата: событие — плитка по тону, подпись и время; последнее выделено. */
export function CandidateTimeline({ events }: { events: readonly TimelineEvent[] }) {
  if (events.length === 0) return null
  return (
    <ol data-slot="invitation-timeline" className="flex min-w-0 flex-col">
      {events.map((event, index) => {
        const view = EVENT_VIEW[event.code] ?? { icon: Circle, tone: 'neutral' as const }
        const last = index === events.length - 1
        return (
          <li key={`${event.code}-${event.at}-${event.label}`} className="relative flex min-w-0 gap-3 pb-4 last:pb-0">
            {last ? null : <span aria-hidden="true" className="absolute top-7 bottom-0 left-3.5 w-px bg-line" />}
            <IconTile icon={view.icon} tone={last ? view.tone : 'neutral'} size="xs" />
            <div className="flex min-w-0 flex-col gap-0.5 pt-0.5">
              <p className={cn('type-sm [overflow-wrap:anywhere] text-ink', last && 'font-medium')}>{event.label}</p>
              <p className="num type-caption flex items-center gap-1 text-ink-muted">
                <CalendarDays aria-hidden="true" className="size-3" />
                {formatDateTime(event.at)}
              </p>
              {event.note ? <p className="type-sm text-ink-muted [overflow-wrap:anywhere]">{event.note}</p> : null}
            </div>
          </li>
        )
      })}
    </ol>
  )
}
