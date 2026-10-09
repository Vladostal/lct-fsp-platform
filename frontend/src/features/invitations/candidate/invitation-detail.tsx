import { useMutation, useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useEffect, useRef, useState } from 'react'
import type { DeclineReason, DiscloseField, InvitationCandidateView, WorkFormat } from '@/client'
import {
  contactAcceptCandidateInvitationMutation,
  contactDeclineCandidateInvitationMutation,
  contactGetCandidateInvitationOptions,
  contactViewCandidateInvitationMutation,
  profileGetConditionsOptions,
} from '@/client/@tanstack/react-query.gen'
import { CopyButton, ErrorState, PageHeader, SalaryRange, StatusBadge, StickyActionBar } from '@/components/app'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { WORK_FORMAT_LABELS } from '@/content/common'
import { errorMessage, hasCode } from '@/lib/api'
import { formatDate, formatDeadline, formatMoney } from '@/lib/format'
import { polling } from '@/lib/query'
import { CONTACT_KIND_LABELS, FIELD_LABELS, InvitationTimeline, tidy, useCatalogLimits } from '../shared'
import { useRefreshCandidateInvitations } from './hooks'
import { WhyInvited } from './why-invited'

const CHANNELS: DiscloseField[] = ['email', 'phone', 'telegram', 'link']

const REASONS: { value: DeclineReason; label: string }[] = [
  { value: 'salary', label: 'Зарплата' },
  { value: 'stack', label: 'Задачи или стек' },
  { value: 'format', label: 'Формат работы' },
  { value: 'company', label: 'Компания' },
  { value: 'not_looking', label: 'Сейчас не ищу' },
  { value: 'other', label: 'Другое' },
]

function AcceptDialog({
  inv,
  open,
  onOpenChange,
}: {
  inv: InvitationCandidateView
  open: boolean
  onOpenChange: (v: boolean) => void
}) {
  const refresh = useRefreshCandidateInvitations()
  const [picked, setPicked] = useState<Set<DiscloseField>>(
    () => new Set(inv.disclose_options.filter((o) => o.available && o.default).map((o) => o.field)),
  )
  const mutation = useMutation(contactAcceptCandidateInvitationMutation())
  const hasChannel = CHANNELS.some((c) => picked.has(c))
  const toggle = (field: DiscloseField, on: boolean) =>
    setPicked((prev) => {
      const next = new Set(prev)
      if (on) next.add(field)
      else next.delete(field)
      return next
    })
  const submit = () =>
    mutation.mutate(
      { path: { invitation_id: inv.id }, body: { disclose: [...picked] } },
      {
        onSuccess: async () => {
          await refresh()
          onOpenChange(false)
        },
        onError: (e) => {
          if (hasCode(e, 'invitation_not_actionable')) {
            void refresh()
            onOpenChange(false)
          }
        },
      },
    )
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Принять приглашение?</DialogTitle>
          <DialogDescription>
            Работодатель «{inv.company.name}» увидит ваши имя и фамилию и выбранные способы связи. Отменить это нельзя.
            {inv.is_demo ? ' Демо-компания получит только пометку о принятии: данные не передаются.' : ''}
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-3">
          {inv.disclose_options.map((option) => (
            <div key={option.field} className="flex min-w-0 items-start gap-3">
              <Checkbox
                id={`disclose-${option.field}`}
                checked={picked.has(option.field)}
                disabled={!option.available}
                onCheckedChange={(v) => toggle(option.field, v === true)}
              />
              <Label htmlFor={`disclose-${option.field}`} className="min-w-0 flex-col items-start gap-0">
                <span>{option.label}</span>
                {!option.available ? <span className="type-sm text-ink-muted">Укажите в профиле</span> : null}
              </Label>
            </div>
          ))}
          {!hasChannel ? <p className="type-sm text-danger">Выберите хотя бы один способ связи</p> : null}
          <p className="type-sm text-ink-muted">Выбор действует только для этого приглашения</p>
          {mutation.isError ? (
            <Alert variant="destructive">
              <AlertDescription>{errorMessage(mutation.error)}</AlertDescription>
            </Alert>
          ) : null}
        </DialogBody>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Отмена
          </Button>
          <Button variant="primary" disabled={!hasChannel} loading={mutation.isPending} onClick={submit}>
            Принять и открыть контакты
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function DeclineDialog({
  inv,
  open,
  onOpenChange,
}: {
  inv: InvitationCandidateView
  open: boolean
  onOpenChange: (v: boolean) => void
}) {
  const refresh = useRefreshCandidateInvitations()
  const limits = useCatalogLimits()
  const conditions = useQuery({ ...profileGetConditionsOptions(), enabled: open })
  const [reason, setReason] = useState<DeclineReason | ''>('')
  const [salary, setSalary] = useState('')
  const [format, setFormat] = useState<WorkFormat | ''>('')
  const [comment, setComment] = useState('')
  const mutation = useMutation(contactDeclineCandidateInvitationMutation())

  const amount = salary.trim() === '' ? null : Number.parseInt(salary.replace(/\D/g, ''), 10)
  let salaryError: string | null = null
  if (reason === 'salary' && amount !== null) {
    if (!Number.isFinite(amount) || amount % limits.declineStep !== 0)
      salaryError = `Сумма кратна ${formatMoney(limits.declineStep)}`
    else if (amount <= inv.salary_from)
      salaryError = `Больше нижней границы предложения: ${formatMoney(inv.salary_from)}`
    else if (amount > limits.salary_max) salaryError = `Не больше ${formatMoney(limits.salary_max)}`
  }
  const ownFormats = (conditions.data?.work_formats ?? []).filter((f) => f !== inv.work_format)
  const valid = reason !== '' && !salaryError

  const submit = () => {
    if (reason === '') return
    const condition =
      reason === 'salary' && amount !== null
        ? { kind: 'salary_from' as const, value: amount }
        : reason === 'format' && format !== ''
          ? { kind: 'work_format' as const, value: format }
          : undefined
    mutation.mutate(
      {
        path: { invitation_id: inv.id },
        body: { reason_code: reason, condition, comment: !inv.is_demo && comment.trim() ? comment.trim() : undefined },
      },
      {
        onSuccess: async () => {
          await refresh()
          onOpenChange(false)
        },
        onError: (e) => {
          if (hasCode(e, 'invitation_not_actionable')) {
            void refresh()
            onOpenChange(false)
          }
        },
      },
    )
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Отклонить приглашение</DialogTitle>
          <DialogDescription>
            Работодатель узнает причину отказа. Компании «{inv.company.name}» ваш скрытый минимум не раскрывается.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-4">
          <RadioGroup value={reason} onValueChange={(v) => setReason(v as DeclineReason)} aria-label="Причина отказа">
            {REASONS.map((r) => (
              <div key={r.value} className="flex min-h-11 items-center gap-3">
                <RadioGroupItem id={`reason-${r.value}`} value={r.value} />
                <Label htmlFor={`reason-${r.value}`}>{r.label}</Label>
              </div>
            ))}
          </RadioGroup>
          {reason === 'salary' ? (
            <div className="flex flex-col gap-2">
              <Label htmlFor="decline-salary">Готов(а) рассмотреть от, ₽ (необязательно)</Label>
              <Input
                id="decline-salary"
                inputMode="numeric"
                value={salary}
                onChange={(e) => setSalary(e.target.value)}
                aria-invalid={salaryError !== null}
              />
              {salaryError ? <p className="type-sm text-danger">{salaryError}</p> : null}
              <p className="type-sm text-ink-muted">
                Работодатель увидит эту сумму и сможет один раз прислать пересмотренное приглашение. Ваш скрытый минимум
                при этом не раскрывается.
              </p>
            </div>
          ) : null}
          {reason === 'format' && ownFormats.length > 0 ? (
            <div className="flex flex-col gap-2">
              <p className="type-sm text-ink">Рассмотрите формат (необязательно)</p>
              <RadioGroup value={format} onValueChange={(v) => setFormat(v as WorkFormat)} aria-label="Формат работы">
                {ownFormats.map((f) => (
                  <div key={f} className="flex min-h-11 items-center gap-3">
                    <RadioGroupItem id={`format-${f}`} value={f} />
                    <Label htmlFor={`format-${f}`}>{WORK_FORMAT_LABELS[f]}</Label>
                  </div>
                ))}
              </RadioGroup>
            </div>
          ) : null}
          {inv.is_demo ? (
            <p className="type-sm text-ink-muted">Демо-компания комментарий не получит</p>
          ) : (
            <div className="flex flex-col gap-2">
              <Label htmlFor="decline-comment">Комментарий (необязательно)</Label>
              <Textarea
                id="decline-comment"
                maxLength={300}
                value={comment}
                onChange={(e) => setComment(e.target.value)}
              />
              <p className="type-sm text-ink-muted">Его увидит работодатель · {comment.length} из 300</p>
            </div>
          )}
          {mutation.isError ? (
            <Alert variant="destructive">
              <AlertDescription>{errorMessage(mutation.error)}</AlertDescription>
            </Alert>
          ) : null}
        </DialogBody>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Отмена
          </Button>
          <Button variant="destructive" disabled={!valid} loading={mutation.isPending} onClick={submit}>
            Отклонить
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ResultAlert({ inv }: { inv: InvitationCandidateView }) {
  const limits = useCatalogLimits()
  let variant: 'success' | 'info' | 'warning' = 'info'
  let text = ''
  if (inv.status === 'accepted') {
    variant = 'success'
    const given = (inv.disclosed ?? []).map((f) => FIELD_LABELS[f]).join(', ') || 'имя и фамилию'
    text = `Вы приняли приглашение. Работодатель получил: ${given}. Способ связи с ним: ${CONTACT_KIND_LABELS[inv.contact_method.kind]}, ${inv.contact_method.value}.`
    if (inv.contact_sla_until) text += ` Работодатель обязуется связаться до ${formatDate(inv.contact_sla_until)}.`
  } else if (inv.status === 'declined') {
    const c = inv.decline?.condition
    text = `Вы отклонили приглашение: ${inv.decline?.reason_label ?? 'причина не указана'}.`
    if (c)
      text +=
        c.kind === 'salary_from'
          ? ` Названное условие: от ${formatMoney(Number(c.value))}.`
          : ` Названное условие: формат — ${WORK_FORMAT_LABELS[c.value as WorkFormat]}.`
  } else if (inv.status === 'expired') {
    variant = 'warning'
    text = `Срок ответа истёк ${formatDate(inv.expires_at)}.`
    if (inv.strikes)
      text += ` Пропущено ${inv.strikes.count} из ${inv.strikes.limit}: ещё одно приглашение без ответа скроет профиль на ${limits.autoPauseDays} дней.`
  } else if (inv.status === 'withdrawn') {
    text = `Работодатель отозвал приглашение ${formatDate(inv.timeline.at(-1)?.at ?? inv.expires_at)}.`
  } else return null
  return (
    <Alert variant={variant} live>
      <AlertDescription>{tidy(text)}</AlertDescription>
    </Alert>
  )
}

function CompanyAside({ inv }: { inv: InvitationCandidateView }) {
  const [full, setFull] = useState(false)
  const c = inv.company
  return (
    <section className="surface-card flex min-w-0 flex-col gap-3" aria-label="О компании">
      <h2 className="type-h3 text-ink">О компании</h2>
      <p className="type-body font-medium [overflow-wrap:anywhere] text-ink">{c.name}</p>
      <p className="type-sm text-ink-muted">{c.sphere}</p>
      <p className={`type-sm whitespace-pre-line text-ink [overflow-wrap:anywhere] ${full ? '' : 'line-clamp-6'}`}>
        {c.description}
      </p>
      {c.description.length > 280 ? (
        <Button variant="link" size="sm" className="self-start" onClick={() => setFull((v) => !v)}>
          {full ? 'Свернуть' : 'Показать полностью'}
        </Button>
      ) : null}
      {c.site ? (
        <a
          className="type-sm text-link min-w-0 [overflow-wrap:anywhere] underline"
          href={c.site}
          target="_blank"
          rel="noreferrer noopener"
        >
          {c.site}
        </a>
      ) : null}
      <p className="type-sm text-ink-muted">На платформе с {formatDate(c.on_platform_since)}</p>
      <p className="type-caption text-ink-muted">{c.trust_label}</p>
    </section>
  )
}

/** C9. Приглашение: условия, причина, способ связи, ответ. Просмотр отмечается эффектом, а не загрузкой маршрута. */
export function CandidateInvitationDetail({ id }: { id: string }) {
  const query = useQuery({ ...contactGetCandidateInvitationOptions({ path: { invitation_id: id } }), ...polling })
  const view = useMutation(contactViewCandidateInvitationMutation())
  const refresh = useRefreshCandidateInvitations()
  const refreshRef = useRef(refresh)
  refreshRef.current = refresh
  const { mutate: markViewed } = view
  const marked = useRef<string | null>(null)
  const [accepting, setAccepting] = useState(false)
  const [declining, setDeclining] = useState(false)
  const status = query.data?.status

  useEffect(() => {
    if (status === 'sent' && marked.current !== id) {
      marked.current = id
      markViewed({ path: { invitation_id: id } }, { onSuccess: () => void refreshRef.current() })
    }
  }, [status, id, markViewed])

  if (query.isPending)
    return (
      <div className="flex flex-col gap-4" aria-busy="true">
        <Skeleton className="h-10 w-2/3" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  if (query.isError)
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} retrying={query.isFetching} />

  const inv = query.data
  const actionable = inv.status === 'sent' || inv.status === 'viewed'
  return (
    <div className={`flex min-w-0 flex-col gap-6 ${actionable ? 'pb-20' : ''}`}>
      <PageHeader
        back={{ label: 'Приглашения', href: '/candidate/invitations' }}
        eyebrow={inv.company.name}
        title={inv.title}
        meta={
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <StatusBadge status={inv.status} label={inv.status_label} live />
            {actionable ? <span className="type-sm text-ink-muted">{formatDeadline(inv.expires_at)}</span> : null}
            {inv.is_demo ? <Badge variant="info">демо</Badge> : null}
          </div>
        }
      />
      {inv.revision_of ? (
        <Alert variant="info">
          <AlertDescription>
            Пересмотренное приглашение: работодатель изменил условия после вашего ответа.{' '}
            <Link
              to="/candidate/invitations/$invitationId"
              params={{ invitationId: inv.revision_of }}
              className="text-link underline"
            >
              Прежнее приглашение
            </Link>
          </AlertDescription>
        </Alert>
      ) : null}
      <ResultAlert inv={inv} />
      <div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="flex min-w-0 flex-col gap-4">
          <section className="surface-card flex min-w-0 flex-col gap-3" aria-label="Условия">
            <h2 className="type-h3 text-ink">Условия</h2>
            <SalaryRange from={inv.salary_from} to={inv.salary_to} size="lg" />
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <Badge variant="neutral">{WORK_FORMAT_LABELS[inv.work_format]}</Badge>
              {inv.city ? <Badge variant="neutral">{inv.city}</Badge> : null}
              {inv.below_my_min ? <Badge variant="warning">ниже вашего минимума</Badge> : null}
            </div>
          </section>
          <section className="surface-card flex min-w-0 flex-col gap-2" aria-label="Описание предложения">
            <h2 className="type-h3 text-ink">Описание предложения</h2>
            <p className="type-body max-w-[72ch] whitespace-pre-line [overflow-wrap:anywhere] text-ink">
              {inv.description}
            </p>
          </section>
          {inv.message ? (
            <section className="surface-card flex min-w-0 flex-col gap-2" aria-label="Сообщение от работодателя">
              <h2 className="type-h3 text-ink">Сообщение от работодателя</h2>
              <p className="type-body max-w-[72ch] whitespace-pre-line [overflow-wrap:anywhere] text-ink">
                {inv.message}
              </p>
            </section>
          ) : null}
          <section className="surface-card flex min-w-0 flex-col gap-3" aria-label="Почему вас пригласили">
            <h2 className="type-h3 text-ink">Почему вас пригласили</h2>
            <WhyInvited why={inv.why} />
          </section>
          <section className="surface-card flex min-w-0 flex-col gap-2" aria-label="Способ связи">
            <h2 className="type-h3 text-ink">Способ связи</h2>
            <p className="type-body flex min-w-0 items-center gap-2 text-ink">
              <span className="min-w-0 [overflow-wrap:anywhere]">
                {CONTACT_KIND_LABELS[inv.contact_method.kind]}: <span className="num">{inv.contact_method.value}</span>
              </span>
              <CopyButton value={inv.contact_method.value} label="Скопировать способ связи" />
            </p>
          </section>
        </div>
        <aside className="flex min-w-0 flex-col gap-4">
          <CompanyAside inv={inv} />
          <section className="surface-card flex min-w-0 flex-col gap-3" aria-label="Ход приглашения">
            <h2 className="type-h3 text-ink">Ход приглашения</h2>
            <InvitationTimeline events={inv.timeline} />
          </section>
        </aside>
      </div>
      {actionable ? (
        <StickyActionBar
          width="page"
          secondary={
            <Button variant="secondary" onClick={() => setDeclining(true)}>
              Отклонить
            </Button>
          }
        >
          <Button variant="primary" onClick={() => setAccepting(true)}>
            Принять
          </Button>
        </StickyActionBar>
      ) : null}
      {accepting ? <AcceptDialog inv={inv} open onOpenChange={setAccepting} /> : null}
      {declining ? <DeclineDialog inv={inv} open onOpenChange={setDeclining} /> : null}
    </div>
  )
}
