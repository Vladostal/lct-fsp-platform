import type { TimelineEvent } from '@/client'
import { formatDateTime } from '@/lib/format'
import { cn } from '@/lib/utils'

export type InvitationTimelineProps = {
  events: readonly TimelineEvent[]
  className?: string
}

/** «Ход приглашения»: события по порядку, у каждого время и необязательная пометка. */
export function InvitationTimeline({ events, className }: InvitationTimelineProps) {
  if (events.length === 0) return null
  return (
    <ol data-slot="invitation-timeline" className={cn('flex min-w-0 flex-col gap-2', className)}>
      {events.map((event, index) => (
        <li key={`${event.code}-${event.at}-${event.label}`} className="flex min-w-0 gap-3">
          <span
            aria-hidden="true"
            className={cn(
              'mt-1.5 size-2 shrink-0 rounded-full',
              index === events.length - 1 ? 'bg-brand-600' : 'bg-line-strong',
            )}
          />
          <div className="min-w-0">
            <p className="type-sm text-ink [overflow-wrap:anywhere]">
              {event.label} <span className="num text-ink-muted">· {formatDateTime(event.at)}</span>
            </p>
            {event.note ? <p className="type-sm text-ink-muted [overflow-wrap:anywhere]">{event.note}</p> : null}
          </div>
        </li>
      ))}
    </ol>
  )
}
