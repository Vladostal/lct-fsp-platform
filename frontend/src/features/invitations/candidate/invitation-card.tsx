import { Link } from '@tanstack/react-router'
import { Clock } from 'lucide-react'
import type { InvitationCandidateBrief } from '@/client'
import { SalaryRange, StatusBadge } from '@/components/app'
import { Badge } from '@/components/ui/badge'
import { WORK_FORMAT_LABELS } from '@/content/common'
import { formatDate, formatDeadline, formatRemaining } from '@/lib/format'
import { msUntil } from '@/lib/time'

export type InvitationCardProps = { item: InvitationCandidateBrief }

/** Карточка входящего приглашения: целиком ссылка на C9. */
export function InvitationCard({ item }: InvitationCardProps) {
  const waiting = item.status === 'sent' || item.status === 'viewed'
  const soon = waiting && msUntil(item.expires_at) < 24 * 3600_000 && formatRemaining(item.expires_at) !== null
  return (
    <Link
      to="/candidate/invitations/$invitationId"
      params={{ invitationId: item.id }}
      className="surface-row flex min-w-0 flex-col gap-3 p-4 transition-colors hover:border-line-strong focus-visible:outline-2 focus-visible:outline-offset-2"
    >
      <div className="flex min-w-0 items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="type-eyebrow flex min-w-0 items-center gap-2 text-ink-muted">
            {item.status === 'sent' ? (
              <span aria-hidden="true" className="size-2 shrink-0 rounded-full bg-brand-600" />
            ) : null}
            <span className="truncate">{item.company_name}</span>
          </p>
          <h3 className="type-h3 line-clamp-2 [overflow-wrap:anywhere] text-ink">{item.title}</h3>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <StatusBadge status={item.status} label={item.status_label} size="sm" />
        </div>
      </div>
      <SalaryRange from={item.salary_from} to={item.salary_to} size="md" />
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <Badge variant="neutral" size="sm">
          {WORK_FORMAT_LABELS[item.work_format]}
        </Badge>
        {item.city ? (
          <Badge variant="neutral" size="sm">
            {item.city}
          </Badge>
        ) : null}
        {item.is_demo ? (
          <Badge variant="info" size="sm">
            демо
          </Badge>
        ) : null}
        {item.below_my_min ? (
          <Badge variant="warning" size="sm">
            ниже вашего минимума
          </Badge>
        ) : null}
      </div>
      {waiting ? (
        <p className={`type-sm flex items-center gap-1.5 ${soon ? 'text-warning' : 'text-ink-muted'}`}>
          {soon ? <Clock className="size-4 shrink-0" aria-hidden="true" /> : null}
          <span className="min-w-0">{formatDeadline(item.expires_at)}</span>
        </p>
      ) : item.status === 'expired' && item.strikes ? (
        <p className="type-sm text-ink-muted">
          Срок истёк {formatDate(item.expires_at)} · пропущено {item.strikes.count} из {item.strikes.limit}
        </p>
      ) : (
        <p className="type-sm text-ink-muted">Обновлено {formatDate(item.updated_at)}</p>
      )}
    </Link>
  )
}
