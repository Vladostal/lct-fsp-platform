import { Link } from '@tanstack/react-router'
import { CalendarDays, TimerOff } from 'lucide-react'
import type { InvitationCandidateBrief } from '@/client'
import { DeadlinePill, GoChevron, SoftPill, StatusBadge } from '@/components/app'
import { formatDate } from '@/lib/format'
import { cn } from '@/lib/utils'
import { CompanyTile, candidateStatusCode, OfferPills } from './parts'

export type InvitationCardProps = { item: InvitationCandidateBrief; index?: number }

/** Карточка входящего приглашения: целиком ссылка на C9. Плитка компании, условия плашками, статус и срок. */
export function InvitationCard({ item, index = 0 }: InvitationCardProps) {
  const waiting = item.status === 'sent' || item.status === 'viewed'
  const live = waiting || item.status === 'accepted'
  return (
    <Link
      to="/candidate/invitations/$invitationId"
      params={{ invitationId: item.id }}
      style={{ '--i': index } as React.CSSProperties}
      className={cn(
        'lift-card surface-row stagger flex h-full min-w-0 animate-rise-in flex-col gap-4 p-4 focus-visible:outline-2 focus-visible:outline-offset-2 md:p-5',
        live && 'accent-card',
      )}
    >
      <div className="flex min-w-0 items-start gap-3">
        <CompanyTile name={item.company_name} status={item.status} />
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <p className="type-eyebrow flex min-w-0 items-center gap-2 text-ink-muted">
            <span className="truncate">{item.company_name}</span>
            {item.is_new ? (
              <SoftPill tone="solid" size="sm" className="h-5 px-2 text-xs tracking-normal normal-case">
                новое
              </SoftPill>
            ) : null}
          </p>
          <h3 className="type-h3 line-clamp-2 [overflow-wrap:anywhere] text-ink">{item.title}</h3>
        </div>
        <GoChevron className="mt-1" />
      </div>
      <OfferPills offer={item} />
      <div className="mt-auto flex min-w-0 flex-wrap items-center gap-2 border-t border-line pt-3">
        <StatusBadge status={candidateStatusCode(item.status)} label={item.status_label} size="sm" />
        {waiting ? (
          <DeadlinePill until={item.expires_at} size="sm" />
        ) : item.status === 'expired' && item.strikes ? (
          <>
            <span className="type-sm inline-flex items-center gap-1.5 text-ink-muted">
              <CalendarDays aria-hidden="true" className="size-3.5" />
              <span className="num">
                <span className="sr-only">Срок истёк </span>
                {formatDate(item.expires_at)}
              </span>
            </span>
            <SoftPill tone="warning" size="sm" icon={TimerOff}>
              <span className="num">
                пропущено {item.strikes.count} из {item.strikes.limit}
              </span>
            </SoftPill>
          </>
        ) : (
          <span className="type-sm inline-flex items-center gap-1.5 text-ink-muted">
            <CalendarDays aria-hidden="true" className="size-3.5" />
            <span className="num">
              <span className="sr-only">Обновлено </span>
              {formatDate(item.updated_at)}
            </span>
          </span>
        )}
      </div>
    </Link>
  )
}
