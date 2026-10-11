import { useMutation, useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import {
  ArrowRight,
  Ban,
  Banknote,
  CircleCheckBig,
  CircleX,
  Clock,
  Eye,
  FileDown,
  FileText,
  FlaskConical,
  History,
  Hourglass,
  Link2,
  type LucideIcon,
  MailX,
  MessageSquareText,
  Send,
  Server,
  Undo2,
  UserRound,
} from 'lucide-react'
import { useState } from 'react'
import type { InvitationEmployerView, WorkFormat } from '@/client'
import {
  companyGetCompanyOptions,
  contactGetEmployerInvitationOptions,
  contactWithdrawEmployerInvitationMutation,
  profileGetContactsOptions,
} from '@/client/@tanstack/react-query.gen'
import {
  CandidateCategoryChip,
  CopyButton,
  DeadlinePill,
  ErrorState,
  GoChevron,
  IconTile,
  PageHeader,
  RevealOnce,
  SalaryRange,
  SoftPill,
  StatusBadge,
  type TileTone,
} from '@/components/app'
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
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { WORK_FORMAT_LABELS } from '@/content/common'
import { errorMessage, hasCode } from '@/lib/api'
import { candidateTitle, formatDate, formatDateTime, formatMoney } from '@/lib/format'
import { polling } from '@/lib/query'
import { cn } from '@/lib/utils'
import { InvitationPreview, tidy, useCatalogLimits } from '../shared'
import { useRefreshEmployerInvitations } from './hooks'
import { statusLine } from './status-line'

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
    <RevealOnce storageKey={`contacts-revealed:${candidateId}`} className="flex min-w-0 flex-col gap-3 p-3 -m-3">
      <ul className="flex min-w-0 flex-col gap-2">
        {rows.map(([label, value]) => (
          <li key={label} className="flex min-w-0 items-center justify-between gap-2 rounded-md bg-fill py-1 pr-1 pl-3">
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
    </RevealOnce>
  )
}

type Step = { key: string; label: string; at?: string | null; icon: LucideIcon; tone: TileTone; reached: boolean }

const FINAL: Record<string, { icon: LucideIcon; tone: TileTone }> = {
  accepted: { icon: CircleCheckBig, tone: 'success' },
  declined: { icon: CircleX, tone: 'danger' },
  expired: { icon: Clock, tone: 'warning' },
  withdrawn: { icon: Undo2, tone: 'neutral' },
}

/** Три шага приглашения по его статусу: отправлено → просмотрено → исход. Недостигнутый шаг — пунктир. */
function statusSteps(inv: InvitationEmployerView): Step[] {
  const viewedAt = inv.timeline.find((e) => e.code === 'viewed')?.at
  const bounced = inv.status === 'bounced'
  const final = FINAL[inv.status]
  const viewed = Boolean(viewedAt) || inv.status === 'viewed' || inv.status === 'accepted' || inv.status === 'declined'
  return [
    bounced
      ? { key: 'sent', label: 'Не доставлено', at: inv.sent_at, icon: MailX, tone: 'dashed', reached: true }
      : { key: 'sent', label: 'Отправлено', at: inv.sent_at, icon: Send, tone: 'solid', reached: true },
    {
      key: 'viewed',
      label: 'Просмотрено',
      at: viewedAt,
      icon: Eye,
      tone: viewed ? 'brand' : 'dashed',
      reached: viewed,
    },
    final
      ? { key: 'final', label: inv.status_label, at: inv.updated_at, icon: final.icon, tone: final.tone, reached: true }
      : { key: 'final', label: 'Ответ', icon: Hourglass, tone: 'dashed', reached: false },
  ]
}

function StatusSteps({ inv }: { inv: InvitationEmployerView }) {
  const steps = statusSteps(inv)
  return (
    <ol aria-label="Этапы приглашения" className="flex min-w-0 items-start">
      {steps.map((s, i) => (
        <li
          key={s.key}
          aria-current={i === steps.findLastIndex((x) => x.reached) ? 'step' : undefined}
          style={{ '--i': i } as React.CSSProperties}
          className="stagger animate-rise-in relative flex min-w-0 flex-1 flex-col items-center gap-1.5 text-center"
        >
          {i > 0 ? (
            <span
              aria-hidden="true"
              className={cn(
                'absolute top-5 right-1/2 -z-0 mr-6 h-0.5 w-[calc(100%-3rem)] rounded-full',
                s.reached ? 'bg-brand-600' : 'border-t-2 border-dashed border-line-strong',
              )}
            />
          ) : null}
          <IconTile icon={s.icon} tone={s.tone} className="relative rounded-full" />
          <span
            className={cn(
              'type-sm min-w-0 [overflow-wrap:anywhere]',
              s.reached ? 'font-medium text-ink' : 'text-ink-muted',
            )}
          >
            {s.label}
            {s.reached ? null : <span className="sr-only"> — ещё нет</span>}
          </span>
          {s.at ? (
            <span className="num type-caption whitespace-normal text-ink-muted">{formatDateTime(s.at)}</span>
          ) : null}
        </li>
      ))}
    </ol>
  )
}

function PanelTitle({
  icon,
  tone = 'soft',
  children,
}: {
  icon: LucideIcon
  tone?: TileTone
  children: React.ReactNode
}) {
  return (
    <h2 className="type-h3 flex min-w-0 items-center gap-3">
      <IconTile icon={icon} tone={tone} size="sm" />
      <span className="min-w-0">{children}</span>
    </h2>
  )
}

const PANEL = 'surface-row flex min-w-0 flex-col gap-4 p-4 md:p-5'
const RELATED =
  'lift-card surface-row group flex min-h-14 min-w-0 items-center gap-3 p-3 text-sm font-medium text-ink hover:text-brand-700'

/** E7. Экран приглашения: срок, исход, действие по статусу. */
export function EmployerInvitationDetail({ id }: { id: string }) {
  const query = useQuery({ ...contactGetEmployerInvitationOptions({ path: { invitation_id: id } }), ...polling })
  const withdraw = useMutation(contactWithdrawEmployerInvitationMutation())
  const refresh = useRefreshEmployerInvitations()
  const limits = useCatalogLimits()
  // Название компании для предпросмотра: тот же запрос, что в мастере приглашения.
  const company = useQuery(companyGetCompanyOptions())
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
        documentTitle={inv.title}
        title={
          <span className="flex min-w-0 items-start gap-3">
            <IconTile icon={Send} tone="solid" size="lg" className="mt-0.5" />
            <span className="min-w-0 [overflow-wrap:anywhere]">{inv.title}</span>
          </span>
        }
        meta={
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <StatusBadge
              status={inv.status}
              label={inv.status_label}
              // Отказ красный, как в списке и сводке приглашений.
              tone={inv.status === 'declined' ? 'danger' : undefined}
              live
            />
            <SoftPill tone="success">
              <SalaryRange from={inv.salary_from} to={inv.salary_to} size="sm" className="text-success" />
            </SoftPill>
            {inv.is_demo ? <SoftPill icon={FlaskConical}>демо</SoftPill> : null}
            {/* Срок — той же пилюлей, что у кандидата; «просмотрено» уже есть в шагах статуса. */}
            {inv.status === 'sent' || inv.status === 'viewed' ? (
              <DeadlinePill until={inv.expires_at} />
            ) : (
              <SoftPill icon={History} className="h-auto min-h-7 shrink py-0.5 [&>svg]:shrink-0">
                <span className="min-w-0 [overflow-wrap:anywhere]">{statusLine(inv)}</span>
              </SoftPill>
            )}
          </div>
        }
      />
      <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="flex min-w-0 flex-col gap-4">
          <section className={cn(PANEL, 'accent-card')} aria-labelledby="inv-status">
            <h2 id="inv-status" className="sr-only">
              Статус
            </h2>
            <StatusSteps inv={inv} />
            {(inv.status === 'sent' || inv.status === 'viewed') && inv.can_withdraw ? (
              <div className="relative flex justify-end border-t border-line pt-4">
                <Button variant="secondary" onClick={() => setConfirm(true)}>
                  <Ban aria-hidden="true" />
                  Отозвать
                </Button>
              </div>
            ) : null}
            {inv.status === 'accepted' ? (
              <div className="relative border-t border-line pt-4">
                <Contacts candidateId={inv.candidate.candidate_id} until={inv.contact_sla_until} />
              </div>
            ) : null}
            {inv.status === 'declined' ? (
              <div className="relative flex min-w-0 flex-col gap-3 border-t border-line pt-4">
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <SoftPill tone="danger" icon={CircleX} className="h-auto min-h-7 shrink py-0.5 [&>svg]:shrink-0">
                    <span className="min-w-0 [overflow-wrap:anywhere]">
                      Причина: {inv.decline?.reason_label ?? 'не указана'}
                    </span>
                  </SoftPill>
                  {cond ? (
                    <SoftPill
                      tone="success"
                      icon={cond.kind === 'salary_from' ? Banknote : undefined}
                      className="h-auto min-h-7 shrink py-0.5 [&>svg]:shrink-0"
                    >
                      <span className="min-w-0 [overflow-wrap:anywhere]">
                        {cond.kind === 'salary_from'
                          ? `Готов(а) рассмотреть от ${formatMoney(Number(cond.value))}`
                          : `Рассмотрит формат: ${WORK_FORMAT_LABELS[cond.value as WorkFormat]}`}
                      </span>
                    </SoftPill>
                  ) : null}
                </div>
                {inv.decline?.comment ? (
                  <p className="type-body flex min-w-0 items-start gap-2 rounded-md bg-fill p-3 [overflow-wrap:anywhere] text-ink-muted">
                    <MessageSquareText className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
                    <span className="min-w-0">{inv.decline.comment}</span>
                  </p>
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
              <p className="type-body relative border-t border-line pt-4 text-ink">
                Кандидат не ответил. Новое приглашение — с{' '}
                {inv.pair_block_until ? formatDate(inv.pair_block_until) : 'позже'}
              </p>
            ) : null}
            {inv.status === 'bounced' ? (
              <p className="type-body relative border-t border-line pt-4 text-ink">
                Условия не совпали с ожиданиями кандидата. Повтор — с{' '}
                {inv.pair_block_until ? formatDate(inv.pair_block_until) : 'позже'}
              </p>
            ) : null}
            {inv.status === 'withdrawn' ? (
              <p className="type-body relative border-t border-line pt-4 text-ink">
                {tidy(`Вы отозвали приглашение ${formatDate(inv.updated_at)}.`)}
              </p>
            ) : null}
          </section>
          <section className={PANEL} aria-labelledby="inv-preview">
            <div id="inv-preview">
              <PanelTitle icon={Eye}>Что видит кандидат</PanelTitle>
            </div>
            <InvitationPreview
              companyName={company.data?.name?.trim() || 'Ваша компания'}
              isDemo={inv.is_demo}
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
          <Link
            to="/employer/candidates/$candidateId"
            params={{ candidateId: inv.candidate.candidate_id }}
            className={RELATED}
          >
            <IconTile icon={inv.candidate.display_name?.trim() ? undefined : UserRound} tone="soft">
              {inv.candidate.display_name
                ?.trim()
                .split(/\s+/)
                .slice(0, 2)
                .map((p) => p[0]?.toUpperCase())
                .join('')}
            </IconTile>
            <span className="flex min-w-0 flex-1 flex-col gap-0.5">
              <span className="num type-body min-w-0 truncate font-medium">{name}</span>
              <CandidateCategoryChip category={inv.candidate.category} className="font-normal text-ink-muted" />
            </span>
            <GoChevron />
          </Link>
          <section className="flex min-w-0 flex-col gap-2" aria-labelledby="inv-related">
            <h2 id="inv-related" className="type-eyebrow flex items-center gap-1.5">
              <Link2 aria-hidden="true" className="size-3.5" />
              Связанное
            </h2>
            {inv.need ? (
              <Link to="/employer/needs/$needId" params={{ needId: inv.need.id }} className={RELATED}>
                <IconTile icon={Server} tone="brand" size="sm" />
                <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">Потребность: {inv.need.title}</span>
                <GoChevron />
              </Link>
            ) : (
              <p className="type-sm rounded-md border border-dashed border-line-strong p-3 text-ink-muted">
                Из банка кандидатов, без потребности
              </p>
            )}
            {inv.revises_id ? (
              <Link
                to="/employer/invitations/$invitationId"
                params={{ invitationId: inv.revises_id }}
                className={RELATED}
              >
                <IconTile icon={FileText} tone="neutral" size="sm" />
                <span className="min-w-0 flex-1">Исходное приглашение</span>
                <GoChevron />
              </Link>
            ) : null}
            {inv.revision_id ? (
              <Link
                to="/employer/invitations/$invitationId"
                params={{ invitationId: inv.revision_id }}
                className={RELATED}
              >
                <IconTile icon={ArrowRight} tone="brand" size="sm" />
                <span className="min-w-0 flex-1">Пересмотренное приглашение</span>
                <GoChevron />
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
              Кандидат больше не сможет ответить. Новое приглашение этому кандидату — через {limits.pairRetryDays} дней.
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
