import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ArrowLeft, Download } from 'lucide-react'
import { toast } from 'sonner'
import type { CandidateContactsView } from '@/client'
import { CategoryChip, CopyButton, EmptyState, ErrorState, StatusBadge } from '@/components/app'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { api, hasCode, hasStatus } from '@/lib/api'
import { formatDate } from '@/lib/format'
import { polling } from '@/lib/query'
import { cardQuery, matchingKeys, pinCandidate, unpinCandidate } from '../api'
import { MATCHING } from '../content'
import { usePairStates } from '../hooks'
import { MatchCardDetailed } from './match-card-detailed'

const T = MATCHING.card

const STATUS_LABELS: Record<string, string> = {
  sent: 'Отправлено',
  viewed: 'Просмотрено',
  accepted: 'Принято',
  declined: 'Отклонено',
  expired: 'Срок истёк',
  withdrawn: 'Отозвано',
  bounced: 'Условия не совпали',
}

export type InviteRenderProps = {
  candidateId: string
  candidateCode: string
  categoryTitle: string
  needId?: string
  onBack: () => void
}

export type CandidateViewProps = {
  candidateId: string
  needId?: string
  snapshotId?: string
  invite: boolean
  onInvite: () => void
  onBackFromInvite: () => void
  onClose?: () => void
  /**
   * Что показать вместо карточки при `invite`: форма отправки приглашения (`InviteFlow` домена `invitations`).
   * Её передаёт маршрут: домен `matching` не импортирует домен `invitations`. У формы своя кнопка «К карточке»
   * и своя мини-шапка с кодом и категорией — для них сюда передаются `candidateCode` и `categoryTitle`.
   */
  renderInvite?: (props: InviteRenderProps) => React.ReactNode
  layout: 'sheet' | 'page'
}

function Contacts({ candidateId }: { candidateId: string }) {
  const q = useQuery({
    queryKey: ['employer', 'candidate-contacts', candidateId],
    queryFn: ({ signal }) => api.get<CandidateContactsView>(`/employer/candidates/${candidateId}/contacts`, { signal }),
  })
  if (q.isPending) return <Skeleton className="h-16 w-full" />
  if (q.isError) return <p className="type-sm text-ink-muted">Контакты пока недоступны.</p>
  const c = q.data
  if (c.masked) {
    return (
      <Alert variant="info">
        <AlertDescription>
          Скрыто в демо-режиме: контакты настоящих пользователей демо-компании не передаются.
        </AlertDescription>
      </Alert>
    )
  }
  const rows = [
    ['E-mail', c.email],
    ['Телефон', c.phone],
    ['Telegram', c.telegram],
    ['Ссылка', c.link],
  ].filter((r): r is [string, string] => Boolean(r[1]))
  return (
    <div className="flex min-w-0 flex-col gap-3">
      <p className="type-body font-medium">
        {c.first_name} {c.last_name}
      </p>
      <ul className="flex min-w-0 flex-col gap-1">
        {rows.map(([label, value]) => (
          <li key={label} className="flex min-w-0 items-center gap-2">
            <span className="type-sm w-20 shrink-0 text-ink-muted">{label}</span>
            <span className="num min-w-0 break-all">{value}</span>
            <CopyButton value={value} label={`Скопировать: ${label}`} />
          </li>
        ))}
      </ul>
      <Button asChild variant="secondary" size="sm" className="self-start">
        <a href={`/api/v1/employer/candidates/${candidateId}/pdf`} target="_blank" rel="noopener noreferrer">
          <Download aria-hidden="true" />
          {T.pdf}
        </a>
      </Button>
    </div>
  )
}

/** Содержимое E5: карточка и липкая панель действий. Форма показа (Sheet или страница) — у родителя. */
export function CandidateView({
  candidateId,
  needId,
  snapshotId,
  invite,
  onInvite,
  onBackFromInvite,
  onClose,
  renderInvite,
  layout,
}: CandidateViewProps) {
  const queryClient = useQueryClient()
  const query = useQuery({ ...cardQuery(candidateId, needId, snapshotId), ...polling })
  const pair = usePairStates([candidateId]).get(candidateId) ?? null
  const pin = useMutation({
    mutationFn: (pinned: boolean) =>
      pinned ? unpinCandidate(needId ?? '', candidateId) : pinCandidate(needId ?? '', candidateId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: matchingKeys.card(candidateId, needId, snapshotId) })
      if (snapshotId) void queryClient.invalidateQueries({ queryKey: matchingKeys.snapshot(snapshotId) })
    },
    onError: (error) =>
      toast.error(hasCode(error, 'pin_limit') ? MATCHING.shortlist.pinLimit : 'Не удалось изменить закрепление'),
  })

  if (query.isPending) {
    return (
      <div className="flex min-w-0 flex-col gap-4" aria-busy="true">
        <span role="status" className="sr-only">
          Загружаем карточку…
        </span>
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }
  if (query.isError) {
    const e = query.error
    if (hasStatus(e, 404)) {
      return (
        <EmptyState
          title={T.unavailableTitle}
          text={T.unavailableText}
          action={
            onClose ? (
              <Button type="button" variant="secondary" onClick={onClose}>
                {T.close}
              </Button>
            ) : undefined
          }
        />
      )
    }
    if (hasCode(e, 'card_open_limit'))
      return (
        <Alert variant="warning">
          <AlertDescription>{T.limit}</AlertDescription>
        </Alert>
      )
    return <ErrorState error={e} onRetry={() => query.refetch()} compact />
  }

  const card = query.data
  const inv = pair?.invitation
  const block = pair?.pair_block

  if (invite && renderInvite) {
    return renderInvite({
      candidateId,
      candidateCode: card.public_code,
      categoryTitle: card.category.title,
      needId,
      onBack: onBackFromInvite,
    })
  }
  if (invite) {
    // Запасной вид: маршрут не передал форму приглашения.
    return (
      <div className="flex min-w-0 flex-col gap-4">
        <Button type="button" variant="ghost" size="sm" className="self-start" onClick={onBackFromInvite}>
          <ArrowLeft aria-hidden="true" />
          {T.back}
        </Button>
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="type-body num font-medium">{card.public_code}</span>
          <CategoryChip title={card.category.title} />
        </div>
        <Alert variant="info">
          <AlertDescription>{T.inviteSoon}</AlertDescription>
        </Alert>
      </div>
    )
  }

  let action: React.ReactNode
  if (!card.available) action = <p className="type-sm">{T.hiddenProfile}</p>
  else if (block?.code === 'conditions_mismatch')
    action = (
      <p className="type-sm">
        {T.mismatch} · {T.cooldown.toLowerCase()} {formatDate(block.until)}
      </p>
    )
  else if (block?.code === 'pair_cooldown' && inv?.status === 'declined')
    action = (
      <>
        <StatusBadge status="declined" label={T.declined} />
        <OpenInvitation id={inv.id} />
      </>
    )
  else if (block?.code === 'pair_cooldown')
    action = (
      <p className="type-sm">
        {T.cooldown} {formatDate(block.until)}
      </p>
    )
  else if (inv && (inv.status === 'sent' || inv.status === 'viewed'))
    action = (
      <>
        <StatusBadge status={inv.status} label={STATUS_LABELS[inv.status] ?? inv.status} live />
        <OpenInvitation id={inv.id} />
      </>
    )
  else if (inv?.status === 'accepted')
    action = (
      <>
        <StatusBadge status="accepted" label="Принято" />
        <Button asChild variant="secondary">
          <a href="#candidate-contacts">{T.toContacts}</a>
        </Button>
      </>
    )
  else
    action = (
      <Button type="button" variant="primary" onClick={onInvite}>
        {T.invite}
      </Button>
    )

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <MatchCardDetailed
        card={card}
        pair={pair}
        needContext={needId ? { needId, snapshotId } : null}
        onPinToggle={needId ? () => pin.mutate(Boolean(card.pinned)) : undefined}
        contacts={card.disclosed ? <Contacts candidateId={candidateId} /> : undefined}
      />
      <div
        className={
          layout === 'sheet'
            ? 'sticky bottom-0 -mx-4 flex min-w-0 flex-wrap items-center justify-end gap-3 border-t border-line bg-surface px-4 py-3 md:-mx-6 md:px-6'
            : 'sticky bottom-0 flex min-w-0 flex-wrap items-center justify-end gap-3 border-t border-line bg-surface py-3'
        }
        aria-live="polite"
      >
        {action}
      </div>
    </div>
  )
}

function OpenInvitation({ id }: { id: string }) {
  return (
    <Button asChild variant="secondary">
      <Link to="/employer/invitations/$invitationId" params={{ invitationId: id }}>
        {T.openInvitation}
      </Link>
    </Button>
  )
}
