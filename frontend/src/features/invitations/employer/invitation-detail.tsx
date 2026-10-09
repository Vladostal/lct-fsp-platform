import { useMutation, useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { FileDown } from 'lucide-react'
import { useState } from 'react'
import type { WorkFormat } from '@/client'
import {
  contactGetEmployerInvitationOptions,
  contactWithdrawEmployerInvitationMutation,
  profileGetContactsOptions,
} from '@/client/@tanstack/react-query.gen'
import { CopyButton, ErrorState, PageHeader, StatusBadge } from '@/components/app'
import { Alert, AlertDescription } from '@/components/ui/alert'
import {
  AlertDialog,
  AlertDialogBody,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { WORK_FORMAT_LABELS } from '@/content/common'
import { errorMessage, hasCode } from '@/lib/api'
import { candidateTitle, formatDate, formatDateTime, formatMoney } from '@/lib/format'
import { polling } from '@/lib/query'
import { InvitationPreview, InvitationTimeline, tidy, useCatalogLimits } from '../shared'
import { useRefreshEmployerInvitations } from './hooks'
import { slotLine } from './slot-line'

function Contacts({ candidateId, until }: { candidateId: string; until?: string | null }) {
  const contacts = useQuery(profileGetContactsOptions({ path: { candidate_id: candidateId } }))
  if (contacts.isPending) return <Skeleton className="h-24 w-full" />
  if (contacts.isError)
    return <ErrorState compact headingLevel={3} error={contacts.error} onRetry={() => void contacts.refetch()} />
  const c = contacts.data
  if (c.masked)
    return (
      <Alert variant="info">
        <AlertDescription>
          <strong>Скрыто в демо-режиме.</strong> Контакты настоящего кандидата не передаются демо-компании.
          Зарегистрируйте свою компанию, чтобы получать контакты.
        </AlertDescription>
      </Alert>
    )
  const rows = [
    ['Имя', [c.last_name, c.first_name, c.middle_name].filter(Boolean).join(' ')],
    ['Почта', c.email],
    ['Телефон', c.phone],
    ['Telegram', c.telegram],
    ['Ссылка', c.link],
  ].filter((r): r is [string, string] => !!r[1])
  return (
    <div className="flex min-w-0 flex-col gap-3">
      <ul className="flex min-w-0 flex-col gap-2">
        {rows.map(([label, value]) => (
          <li key={label} className="flex min-w-0 items-center justify-between gap-2">
            <span className="type-sm shrink-0 text-ink-muted">{label}</span>
            <span className="flex min-w-0 items-center gap-1">
              <span className="type-body min-w-0 [overflow-wrap:anywhere] text-ink">{value}</span>
              <CopyButton value={value} label={`Скопировать: ${label}`} />
            </span>
          </li>
        ))}
      </ul>
      {until ? <p className="type-sm text-ink-muted">Свяжитесь с кандидатом до {formatDate(until)}</p> : null}
      <Button asChild variant="secondary" size="sm" className="self-start">
        <a href={`/api/v1/employer/candidates/${candidateId}/pdf`}>
          <FileDown aria-hidden="true" /> Скачать PDF-профиль
        </a>
      </Button>
    </div>
  )
}

/** E7. Экран приглашения: слот, срок, исход, действие по статусу. */
export function EmployerInvitationDetail({ id }: { id: string }) {
  const query = useQuery({ ...contactGetEmployerInvitationOptions({ path: { invitation_id: id } }), ...polling })
  const withdraw = useMutation(contactWithdrawEmployerInvitationMutation())
  const refresh = useRefreshEmployerInvitations()
  const limits = useCatalogLimits()
  const [confirm, setConfirm] = useState(false)

  if (query.isPending)
    return (
      <div className="flex flex-col gap-4" aria-busy="true">
        <Skeleton className="h-10 w-1/2" />
        <Skeleton className="h-48 w-full" />
      </div>
    )
  if (query.isError)
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} retrying={query.isFetching} />
  const inv = query.data
  const name = candidateTitle(inv.candidate.display_name, inv.candidate.public_code)
  const cond = inv.decline?.condition

  const doWithdraw = () =>
    withdraw.mutate(
      { path: { invitation_id: id } },
      {
        onSuccess: async () => {
          await refresh()
          setConfirm(false)
        },
        onError: (e) => {
          if (hasCode(e, 'invitation_not_actionable')) {
            void refresh()
            setConfirm(false)
          }
        },
      },
    )

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <PageHeader
        back={{ label: 'Приглашения', href: '/employer/invitations' }}
        eyebrow="Приглашение"
        title={inv.title}
        meta={
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <Link
              to="/employer/candidates/$candidateId"
              params={{ candidateId: inv.candidate.candidate_id }}
              className="type-body text-link num underline"
            >
              {name}
            </Link>
            <StatusBadge status={inv.status} label={inv.status_label} live />
            {inv.is_demo ? <Badge variant="info">демо</Badge> : null}
            <span className="type-sm text-ink-muted [overflow-wrap:anywhere]">{slotLine(inv)}</span>
          </div>
        }
      />
      <div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="flex min-w-0 flex-col gap-4">
          <section className="surface-card flex min-w-0 flex-col gap-3" aria-label="Статус">
            <h2 className="type-h3 text-ink">Статус</h2>
            {(inv.status === 'sent' || inv.status === 'viewed') && inv.can_withdraw ? (
              <div>
                <Button variant="secondary" onClick={() => setConfirm(true)}>
                  Отозвать
                </Button>
              </div>
            ) : null}
            {inv.status === 'accepted' ? (
              <Contacts candidateId={inv.candidate.candidate_id} until={inv.contact_sla_until} />
            ) : null}
            {inv.status === 'declined' ? (
              <div className="flex min-w-0 flex-col gap-3">
                <p className="type-body text-ink">Причина: {inv.decline?.reason_label ?? 'не указана'}</p>
                {cond ? (
                  <p className="type-body text-ink">
                    {cond.kind === 'salary_from'
                      ? `Готов(а) рассмотреть от ${formatMoney(Number(cond.value))}`
                      : `Рассмотрит формат: ${WORK_FORMAT_LABELS[cond.value as WorkFormat]}`}
                  </p>
                ) : null}
                {inv.decline?.comment ? (
                  <p className="type-body [overflow-wrap:anywhere] text-ink-muted">{inv.decline.comment}</p>
                ) : null}
                {inv.can_revise ? (
                  <div>
                    <Button asChild variant="primary">
                      <Link
                        to="/employer/candidates/$candidateId"
                        params={{ candidateId: inv.candidate.candidate_id }}
                        search={{ invite: 1, revises: inv.id } as never}
                      >
                        Отправить пересмотренное
                      </Link>
                    </Button>
                  </div>
                ) : (
                  <p className="type-sm text-ink-muted">
                    Новое приглашение — с{' '}
                    {inv.pair_block_until ? formatDate(inv.pair_block_until) : `через ${limits.pairRetryDays} дней`}
                  </p>
                )}
              </div>
            ) : null}
            {inv.status === 'expired' ? (
              <p className="type-body text-ink">
                Кандидат не ответил. Новое приглашение — с{' '}
                {inv.pair_block_until ? formatDate(inv.pair_block_until) : 'позже'}
              </p>
            ) : null}
            {inv.status === 'bounced' ? (
              <p className="type-body text-ink">
                Условия не совпали с ожиданиями кандидата. Повтор — с{' '}
                {inv.pair_block_until ? formatDate(inv.pair_block_until) : 'позже'}
              </p>
            ) : null}
            {inv.status === 'withdrawn' ? (
              <p className="type-body text-ink">{tidy(`Вы отозвали приглашение ${formatDate(inv.updated_at)}.`)}</p>
            ) : null}
          </section>
          <section className="flex min-w-0 flex-col gap-3" aria-label="Что видит кандидат">
            <h2 className="type-h3 text-ink">Что видит кандидат</h2>
            <InvitationPreview
              companyName="Ваша компания"
              title={inv.title}
              salaryFrom={inv.salary_from}
              salaryTo={inv.salary_to}
              workFormat={inv.work_format}
              city={inv.city}
              description={inv.description}
              contactMethod={inv.contact_method}
              message={inv.message}
            />
          </section>
        </div>
        <aside className="flex min-w-0 flex-col gap-4">
          <section className="surface-card flex min-w-0 flex-col gap-3" aria-label="Ход приглашения">
            <h2 className="type-h3 text-ink">Ход приглашения</h2>
            <InvitationTimeline events={inv.timeline} />
            <p className="type-caption text-ink-muted">Отправлено {formatDateTime(inv.sent_at)}</p>
          </section>
          <section className="surface-card flex min-w-0 flex-col gap-2" aria-label="Связанное">
            <h2 className="type-h3 text-ink">Связанное</h2>
            {inv.need ? (
              <Link
                to="/employer/needs/$needId"
                params={{ needId: inv.need.id }}
                className="type-body text-link [overflow-wrap:anywhere] underline"
              >
                Потребность: {inv.need.title}
              </Link>
            ) : (
              <p className="type-sm text-ink-muted">Из банка кандидатов, без потребности</p>
            )}
            {inv.revises_id ? (
              <Link
                to="/employer/invitations/$invitationId"
                params={{ invitationId: inv.revises_id }}
                className="type-body text-link underline"
              >
                Исходное приглашение
              </Link>
            ) : null}
            {inv.revision_id ? (
              <Link
                to="/employer/invitations/$invitationId"
                params={{ invitationId: inv.revision_id }}
                className="type-body text-link underline"
              >
                Пересмотренное приглашение
              </Link>
            ) : null}
          </section>
        </aside>
      </div>
      <AlertDialog open={confirm} onOpenChange={setConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Отозвать приглашение?</AlertDialogTitle>
            <AlertDialogDescription>
              Слот останется занят до {formatDate(inv.expires_at)}, новое приглашение этому кандидату — через{' '}
              {limits.pairRetryDays} дней.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogBody>
            {withdraw.isError ? (
              <Alert variant="destructive">
                <AlertDescription>{errorMessage(withdraw.error)}</AlertDescription>
              </Alert>
            ) : null}
          </AlertDialogBody>
          <AlertDialogFooter>
            <AlertDialogCancel>Оставить</AlertDialogCancel>
            <Button variant="destructive" loading={withdraw.isPending} onClick={doWithdraw}>
              Отозвать
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
