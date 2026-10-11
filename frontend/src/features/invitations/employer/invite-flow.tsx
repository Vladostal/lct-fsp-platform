import { useMutation, useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ArrowLeft, Eye, Hourglass, Lock, Send, UserRound } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import type {
  CategoryRef,
  ContactKind,
  InvitationEmployerView,
  InvitationPrecheckView,
  NeedView,
  WorkFormat,
} from '@/client'
import {
  companyGetCompanyOptions,
  contactCreateInvitationMutation,
  contactGetEmployerInvitationOptions,
  contactPrecheckInvitationOptions,
  matchingGetNeedOptions,
  matchingListNeedsOptions,
} from '@/client/@tanstack/react-query.gen'
import {
  CandidateCategoryChip,
  CategoryChip,
  ErrorState,
  FormatLabel,
  IconTile,
  SalaryRangeInput,
  SoftPill,
  validateSalaryRange,
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
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { WORK_FORMAT_LABELS } from '@/content/common'
import { errorMessage, errorText, isApiError } from '@/lib/api'
import { formatDate, formatDateTime, formatMoney, formatSalaryRange } from '@/lib/format'
import { cn } from '@/lib/utils'
import { CONTACT_KIND_LABELS, InvitationPreview, tidy, useCatalogLimits } from '../shared'
import { BlockerPanel } from './blocker-panel'
import { useRefreshEmployerInvitations } from './hooks'

export type InviteFlowProps = {
  candidateId: string
  /** Код кандидата для мини-шапки. */
  candidateCode: string
  categoryTitle: string
  /** Категория кандидата целиком: по ней ставится пометка «заявлен». */
  category?: CategoryRef
  needId?: string | null
  /** Пересмотренное приглашение: исходное, отклонённое с условием. */
  revisesId?: string | null
  /** «← К карточке». */
  onBack: () => void
}

type Form = {
  needId: string | null
  title: string
  description: string
  from: number | null
  to: number | null
  workFormat: WorkFormat | ''
  city: string
  contactKind: ContactKind
  contactValue: string
  message: string
}

type FieldErrors = Partial<
  Record<'title' | 'description' | 'salary' | 'workFormat' | 'city' | 'contact' | 'message', string>
>

const FORMATS: WorkFormat[] = ['office', 'hybrid', 'remote']
const CONTACT_KINDS: ContactKind[] = ['email', 'phone', 'telegram', 'other']

const draftKey = (candidateId: string, needId: string | null | undefined) => `invite:${candidateId}:${needId ?? 'bank'}`

function readDraft(key: string): Form | null {
  try {
    const raw = sessionStorage.getItem(key)
    return raw ? (JSON.parse(raw) as Form) : null
  } catch {
    return null
  }
}
function writeDraft(key: string, form: Form | null) {
  try {
    if (form) sessionStorage.setItem(key, JSON.stringify(form))
    else sessionStorage.removeItem(key)
  } catch {
    /* хранилище недоступно: черновик не сохраняется */
  }
}

function fromNeed(need: NeedView, candidateFormats: WorkFormat[], base: Form): Form {
  const format = need.work_formats.find((f) => candidateFormats.includes(f)) ?? candidateFormats[0] ?? ''
  return {
    ...base,
    needId: need.id,
    title: need.title,
    description: need.team_description,
    from: need.salary_from,
    to: need.salary_to,
    city: need.city ?? '',
    workFormat: format,
  }
}

function Field({
  label,
  htmlFor,
  error,
  hint,
  children,
}: {
  label: string
  htmlFor?: string
  error?: string
  hint?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
      {hint ? <p className="type-sm text-ink-muted">{hint}</p> : null}
      {error ? (
        <p className="type-sm text-danger" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  )
}

function Wizard({
  props,
  precheck,
  initial,
  pristine,
  revision,
  needs,
  contactProvided,
}: {
  props: InviteFlowProps
  precheck: InvitationPrecheckView
  initial: Form
  pristine: Form
  revision: InvitationEmployerView | null
  needs: NeedView[]
  contactProvided: boolean
}) {
  const limits = useCatalogLimits()
  const refresh = useRefreshEmployerInvitations()
  // Компания уже загружена родителем (тот же ключ): в предпросмотре — её настоящее название.
  const companyName = useQuery(companyGetCompanyOptions()).data?.name?.trim() || 'Ваша компания'
  const key = draftKey(props.candidateId, props.needId)
  const [form, setForm] = useState<Form>(initial)
  const [step, setStep] = useState<1 | 2>(1)
  const [errors, setErrors] = useState<FieldErrors>({})
  const [serverSalary, setServerSalary] = useState<string | null>(null)
  const [result, setResult] = useState<InvitationEmployerView | null>(null)
  const [blocker, setBlocker] = useState<{
    code: string
    message?: string | null
    params?: Record<string, string | number>
  } | null>(null)
  const [confirmClose, setConfirmClose] = useState(false)
  const idem = useRef<{ key: string; sig: string } | null>(null)
  const mutation = useMutation(contactCreateInvitationMutation())
  const initialSig = useMemo(() => JSON.stringify(pristine), [pristine])
  const sig = JSON.stringify(form)
  const dirty = sig !== initialSig
  const condition = revision?.decline?.condition ?? precheck.pair.condition ?? null

  useEffect(() => {
    if (!result) writeDraft(key, dirty ? form : null)
  }, [form, dirty, key, result])

  const set = <K extends keyof Form>(name: K, value: Form[K]) => {
    setForm((prev) => ({ ...prev, [name]: value }))
    setServerSalary(null)
  }

  const salaryLimits = useMemo(() => {
    const minFrom =
      revision && condition?.kind === 'salary_from'
        ? Math.max(revision.salary_from, Number(condition.value))
        : revision
          ? // После недоставки вилку нужно поднять: сервер ждёт «от» строго больше исходной.
            revision.salary_from + (revision.status === 'bounced' ? 1 : 0)
          : limits.salary_min
    return {
      salary_min: Math.max(limits.salary_min, minFrom),
      salary_max: limits.salary_max,
      salary_max_ratio: limits.salary_max_ratio,
    }
  }, [limits.salary_min, limits.salary_max, limits.salary_max_ratio, revision, condition])

  const formatLocked = revision && condition?.kind === 'work_format'

  const validate = (): boolean => {
    const next: FieldErrors = {}
    if (!form.title.trim()) next.title = 'Введите заголовок'
    else if (form.title.length > 100) next.title = 'Не больше 100 знаков'
    if (form.description.trim().length < 50) next.description = 'Опишите предложение: не меньше 50 знаков'
    else if (form.description.length > 3000) next.description = 'Не больше 3000 знаков'
    if (form.from === null || form.to === null) next.salary = 'Укажите вилку'
    else {
      const issue = validateSalaryRange({ from: form.from, to: form.to }, salaryLimits)
      if (issue) next.salary = errorText(issue.code, issue.params)
    }
    if (form.workFormat === '') next.workFormat = 'Выберите формат работы'
    else if (!precheck.candidate_formats.includes(form.workFormat))
      next.workFormat = 'Кандидат не рассматривает этот формат'
    if ((form.workFormat === 'office' || form.workFormat === 'hybrid') && !form.city.trim()) next.city = 'Укажите город'
    if (!form.contactValue.trim()) next.contact = 'Укажите способ связи'
    if (form.message.length > 1000) next.message = 'Не больше 1000 знаков'
    setErrors(next)
    return Object.keys(next).length === 0
  }

  const toReview = () => {
    if (!validate()) return
    if (!idem.current || idem.current.sig !== sig) idem.current = { key: crypto.randomUUID(), sig }
    mutation.reset()
    setStep(2)
  }

  const send = () => {
    if (form.workFormat === '' || form.from === null || form.to === null || !idem.current) return
    const snapshot = needs.find((n) => n.id === form.needId)?.latest_snapshot?.id
    mutation.mutate(
      {
        headers: { 'Idempotency-Key': idem.current.key },
        body: {
          candidate_id: props.candidateId,
          need_id: form.needId,
          snapshot_id: snapshot ?? null,
          revises_id: props.revisesId ?? null,
          title: form.title.trim(),
          description: form.description.trim(),
          salary_from: form.from,
          salary_to: form.to,
          work_format: form.workFormat,
          city: form.workFormat === 'remote' ? null : form.city.trim() || null,
          contact_method: { kind: form.contactKind, value: form.contactValue.trim() },
          message: form.message.trim() || null,
        },
      },
      {
        onSuccess: (data) => {
          writeDraft(key, null)
          setResult(data)
          void refresh()
        },
        onError: (error) => {
          if (!isApiError(error)) return
          if (error.status === 422) {
            const next: FieldErrors = {}
            const salaryCodes = ['salary_order', 'salary_out_of_bounds', 'salary_range_too_wide']
            if (salaryCodes.includes(error.code)) {
              setServerSalary(errorText(error.code, error.params))
            } else if (error.code === 'format_not_accepted') next.workFormat = errorText(error.code)
            else if (error.code === 'revision_below_condition') {
              if (formatLocked) next.workFormat = errorText(error.code)
              else setServerSalary(errorText(error.code))
            }
            for (const f of error.fields) {
              if (f.name.startsWith('salary')) setServerSalary(f.message)
              else if (f.name === 'title') next.title = f.message
              else if (f.name === 'description') next.description = f.message
              else if (f.name === 'city') next.city = f.message
              else if (f.name === 'work_format') next.workFormat = f.message
              else if (f.name.startsWith('contact')) next.contact = f.message
              else if (f.name === 'message') next.message = f.message
            }
            setErrors(next)
            setStep(1)
          } else if (
            error.status === 409 ||
            error.status === 403 ||
            error.status === 429 ||
            error.code === 'revision_not_allowed'
          ) {
            setBlocker({ code: error.code, message: error.serverMessage, params: error.params })
          }
        },
      },
    )
  }

  const back = () => (dirty && !result ? setConfirmClose(true) : props.onBack())
  const stepTitle = result
    ? 'Приглашение · результат'
    : step === 1
      ? 'Приглашение · шаг 1 из 2: условия'
      : 'Приглашение · шаг 2 из 2: проверка'
  const networkFailure = mutation.isError && isApiError(mutation.error) && mutation.error.status === 0

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <Button variant="ghost" size="sm" className="self-start" onClick={back}>
        <ArrowLeft aria-hidden="true" /> К карточке
      </Button>
      <div className="accent-card surface-row flex min-w-0 items-center gap-3 p-3 md:p-4">
        <IconTile icon={UserRound} tone="brand" />
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="num type-body font-medium text-ink">{props.candidateCode}</span>
          {props.category ? (
            <CandidateCategoryChip category={props.category} className="font-normal text-ink-muted" />
          ) : (
            <CategoryChip title={props.categoryTitle} className="font-normal text-ink-muted" />
          )}
        </div>
        {/* Два шага мастера: пройденный и текущий залиты, результат заливает оба. */}
        <span aria-hidden="true" className="flex shrink-0 items-center gap-1">
          {[1, 2].map((n) => (
            <span
              key={n}
              className={cn(
                'h-1.5 w-8 rounded-full transition-colors',
                result || step >= n ? 'bg-brand-600' : 'bg-line-strong',
              )}
            />
          ))}
        </span>
      </div>
      <h2 className="type-h2 text-ink">{stepTitle}</h2>

      {blocker ? (
        <BlockerPanel code={blocker.code} message={blocker.message} params={blocker.params} needId={props.needId} />
      ) : result ? (
        result.status === 'bounced' ? (
          <div className="flex min-w-0 flex-col gap-4">
            <Alert variant="warning" live>
              <AlertDescription>
                {tidy(
                  `Не доставлено: условия не совпали с ожиданиями кандидата. Повторить попытку можно с ${result.pair_block_until ? formatDate(result.pair_block_until) : 'позже'}.`,
                )}
              </AlertDescription>
            </Alert>
            <ResultActions needId={props.needId} />
          </div>
        ) : (
          <div className="flex min-w-0 flex-col gap-4">
            <Alert variant="success" live>
              <AlertDescription>
                Приглашение отправлено. Ответ не позже {formatDateTime(result.expires_at)}.
              </AlertDescription>
            </Alert>
            <ResultActions needId={props.needId} invitationId={result.id} />
          </div>
        )
      ) : step === 1 ? (
        <form
          className="flex min-w-0 flex-col gap-5"
          noValidate
          onSubmit={(e) => {
            e.preventDefault()
            toReview()
          }}
        >
          {revision && condition ? (
            <Alert variant="info">
              <AlertDescription>
                Кандидат отклонил и назвал условие:{' '}
                {condition.kind === 'salary_from'
                  ? `от ${formatMoney(Number(condition.value))}`
                  : `формат: ${WORK_FORMAT_LABELS[condition.value as WorkFormat]}`}
                . Пересмотреть можно один раз.
              </AlertDescription>
            </Alert>
          ) : null}
          {!props.needId && !revision && needs.length > 0 ? (
            <Field label="Заполнить из потребности (необязательно)" htmlFor="invite-need">
              <Select
                value={form.needId ?? ''}
                onValueChange={(id) => {
                  const need = needs.find((n) => n.id === id)
                  if (need)
                    setForm((prev) =>
                      fromNeed(need, precheck.candidate_formats, { ...prev, contactKind: prev.contactKind }),
                    )
                }}
              >
                <SelectTrigger id="invite-need">
                  <SelectValue placeholder="Выберите потребность" />
                </SelectTrigger>
                <SelectContent>
                  {needs.map((n) => (
                    <SelectItem key={n.id} value={n.id}>
                      {n.title}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
          ) : null}
          <Field label="Заголовок предложения" htmlFor="invite-title" error={errors.title}>
            <Input
              id="invite-title"
              maxLength={100}
              value={form.title}
              onChange={(e) => set('title', e.target.value)}
              aria-invalid={!!errors.title}
            />
          </Field>
          <Field
            label="Описание"
            htmlFor="invite-description"
            error={errors.description}
            hint={`${form.description.length} из 3000, не меньше 50`}
          >
            <Textarea
              id="invite-description"
              rows={6}
              maxLength={3000}
              value={form.description}
              onChange={(e) => set('description', e.target.value)}
              aria-invalid={!!errors.description}
            />
          </Field>
          <div className="flex min-w-0 flex-col gap-2">
            <SalaryRangeInput
              value={{ from: form.from, to: form.to }}
              onChange={(v) => {
                setForm((prev) => ({ ...prev, from: v.from, to: v.to }))
                setServerSalary(null)
                setErrors((prev) => ({ ...prev, salary: undefined }))
              }}
              limits={salaryLimits}
              serverError={serverSalary ?? errors.salary ?? null}
              legend="Зарплата, ₽ в месяц"
              required
            />
            {precheck.salary_hint ? (
              <p className="type-sm text-ink-muted">
                Справка, не рекомендация: медиана вилок принятых приглашений категории —{' '}
                {formatSalaryRange(precheck.salary_hint.from, precheck.salary_hint.to)}
              </p>
            ) : null}
          </div>
          <fieldset className="flex min-w-0 flex-col gap-2">
            <legend className="type-sm font-medium text-ink">Формат работы</legend>
            <RadioGroup
              value={form.workFormat}
              onValueChange={(v) => set('workFormat', v as WorkFormat)}
              aria-label="Формат работы"
            >
              {FORMATS.map((f) => {
                const unavailable = !precheck.candidate_formats.includes(f)
                const disabled = unavailable || (!!formatLocked && f !== form.workFormat)
                return (
                  <div key={f} className="flex min-h-11 min-w-0 items-center gap-3">
                    <RadioGroupItem id={`invite-format-${f}`} value={f} disabled={disabled} />
                    <Label htmlFor={`invite-format-${f}`} className="min-w-0">
                      <FormatLabel format={f} />
                      {unavailable ? (
                        <span className="type-sm text-ink-muted"> · кандидат не рассматривает</span>
                      ) : null}
                    </Label>
                  </div>
                )
              })}
            </RadioGroup>
            {errors.workFormat ? (
              <p className="type-sm text-danger" role="alert">
                {errors.workFormat}
              </p>
            ) : null}
          </fieldset>
          {form.workFormat !== 'remote' ? (
            <Field
              label={form.workFormat === '' ? 'Город' : 'Город (обязателен для офиса и гибрида)'}
              htmlFor="invite-city"
              error={errors.city}
            >
              <Input
                id="invite-city"
                value={form.city}
                onChange={(e) => set('city', e.target.value)}
                aria-invalid={!!errors.city}
              />
            </Field>
          ) : null}
          <div className="flex min-w-0 flex-col gap-2">
            <p className="type-sm font-medium text-ink">Способ связи с вами</p>
            <div className="flex min-w-0 flex-col gap-3 sm:flex-row">
              <Select value={form.contactKind} onValueChange={(v) => set('contactKind', v as ContactKind)}>
                <SelectTrigger aria-label="Вид связи" className="sm:w-48">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CONTACT_KINDS.map((k) => (
                    <SelectItem key={k} value={k}>
                      {CONTACT_KIND_LABELS[k]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Input
                aria-label="Контакт"
                className="min-w-0 flex-1"
                value={form.contactValue}
                onChange={(e) => set('contactValue', e.target.value)}
                aria-invalid={!!errors.contact}
              />
            </div>
            {errors.contact ? (
              <p className="type-sm text-danger" role="alert">
                {errors.contact}
              </p>
            ) : null}
            {!contactProvided ? (
              <p className="type-sm text-ink-muted">В профиле компании способ связи не указан</p>
            ) : null}
          </div>
          <Field
            label="Сообщение кандидату (необязательно)"
            htmlFor="invite-message"
            error={errors.message}
            hint={`${form.message.length} из 1000`}
          >
            <Textarea
              id="invite-message"
              rows={3}
              maxLength={1000}
              value={form.message}
              onChange={(e) => set('message', e.target.value)}
            />
          </Field>
          <div className="flex flex-wrap items-center justify-end gap-3">
            <Button type="button" variant="ghost" onClick={back}>
              Отмена
            </Button>
            <Button type="submit" variant="primary">
              <Eye aria-hidden="true" />
              Проверить и отправить
            </Button>
          </div>
        </form>
      ) : (
        <div className="flex min-w-0 flex-col gap-4">
          <h3 className="type-eyebrow flex items-center gap-1.5">
            <Eye aria-hidden="true" className="size-3.5 text-brand-700" />
            Так приглашение увидит кандидат
          </h3>
          <InvitationPreview
            companyName={companyName}
            title={form.title}
            salaryFrom={form.from ?? 0}
            salaryTo={form.to ?? 0}
            workFormat={form.workFormat === '' ? 'remote' : form.workFormat}
            city={form.workFormat === 'remote' ? null : form.city}
            description={form.description}
            contactMethod={{ kind: form.contactKind, value: form.contactValue }}
            message={form.message || null}
          />
          <ul className="flex min-w-0 flex-wrap gap-2">
            <li className="min-w-0 max-w-full">
              <SoftPill tone="warning" icon={Hourglass} className="h-auto min-h-7 shrink py-0.5 [&>svg]:shrink-0">
                <span className="min-w-0">
                  Ответ не позже <span className="num">{formatDateTime(precheck.expires_at_preview)}</span>
                </span>
              </SoftPill>
            </li>
            <li className="min-w-0 max-w-full">
              <SoftPill icon={Lock} className="h-auto min-h-7 shrink py-0.5 [&>svg]:shrink-0">
                <span className="min-w-0">Условия после отправки не изменить</span>
              </SoftPill>
            </li>
          </ul>
          <Alert variant="warning">
            <AlertDescription>
              Нижняя граница вилки сверяется с ожиданиями кандидата один раз — при отправке. Если условия не совпадут,
              приглашение не будет доставлено, а повторить попытку этому кандидату можно через {limits.pairRetryDays}{' '}
              дней.
            </AlertDescription>
          </Alert>
          {mutation.isError && !blocker ? (
            <Alert variant="destructive">
              <AlertDescription>
                {networkFailure ? 'Приглашение не отправлено: нет связи' : errorMessage(mutation.error)}
              </AlertDescription>
            </Alert>
          ) : null}
          <div className="flex flex-wrap items-center justify-end gap-3">
            <Button variant="ghost" onClick={() => setStep(1)}>
              Назад к условиям
            </Button>
            <Button variant="primary" loading={mutation.isPending} onClick={send}>
              <Send aria-hidden="true" />
              {networkFailure ? 'Повторить' : 'Отправить приглашение'}
            </Button>
          </div>
        </div>
      )}

      <AlertDialog open={confirmClose} onOpenChange={setConfirmClose}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Закрыть без отправки?</AlertDialogTitle>
            <AlertDialogDescription>Черновик сохранится.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogBody />
          <AlertDialogFooter>
            <AlertDialogCancel>Остаться</AlertDialogCancel>
            <Button variant="secondary" onClick={props.onBack}>
              Закрыть
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

function ResultActions({ needId, invitationId }: { needId?: string | null; invitationId?: string }) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <Button asChild variant="primary">
        {needId ? (
          <Link to="/employer/needs/$needId" params={{ needId }}>
            К подборке
          </Link>
        ) : (
          <Link to="/employer/needs">К подборке</Link>
        )}
      </Button>
      {invitationId ? (
        <Button asChild variant="secondary">
          <Link to="/employer/invitations/$invitationId" params={{ invitationId }}>
            Открыть приглашение
          </Link>
        </Button>
      ) : null}
    </div>
  )
}

const PAIR_BLOCK_CODES = ['pair_cooldown', 'conditions_mismatch']

/**
 * E6. Отправка приглашения: предпроверка, условия, проверка перед отправкой, результат.
 * Показывается вместо содержимого панели или страницы E5; идентификатор запроса отправки стабилен, пока форма не менялась.
 */
export function InviteFlow(props: InviteFlowProps) {
  const { candidateId, needId, revisesId } = props
  const precheck = useQuery(
    contactPrecheckInvitationOptions({ query: { candidate_id: candidateId, need_id: needId ?? null } }),
  )
  const company = useQuery(companyGetCompanyOptions())
  const need = useQuery({ ...matchingGetNeedOptions({ path: { need_id: needId ?? '' } }), enabled: !!needId })
  const needsList = useQuery({ ...matchingListNeedsOptions(), enabled: !needId })
  const revision = useQuery({
    ...contactGetEmployerInvitationOptions({ path: { invitation_id: revisesId ?? '' } }),
    enabled: !!revisesId,
  })
  // Предпроверка, с которой форма открылась. После отправки запрос предпроверки обновляется (у пары появилось
  // приглашение, `can_invite` становится false), и без этой отметки экран результата тут же сменялся бы
  // блокировкой «уже приглашён» — работодатель не видел бы, доставлено приглашение или нет.
  const opened = useRef<InvitationPrecheckView | null>(null)

  const queries = [precheck, company, ...(needId ? [need] : []), ...(revisesId ? [revision] : [])]
  const failed = queries.find((q) => q.isError)
  if (failed)
    return (
      <ErrorState
        compact
        headingLevel={2}
        error={failed.error}
        onRetry={() => queries.forEach((q) => void q.refetch())}
      />
    )
  if (queries.some((q) => q.isPending) || !precheck.data)
    return (
      <div className="flex flex-col gap-3" aria-busy="true">
        <Skeleton className="h-8 w-1/2" />
        <Skeleton className="h-48 w-full" />
      </div>
    )

  const pre = opened.current ?? precheck.data
  // Пересмотр после отказа или недоставки: блокировку пары сервер при отправке пропускает (Арх. 4.8),
  // а предпроверка о пересмотре не знает и возвращает её как блокер.
  const revising = !!revisesId && pre.pair.can_revise && pre.pair.revises_id === revisesId
  const blockers = revising ? pre.blockers.filter((b) => !PAIR_BLOCK_CODES.includes(b.code)) : pre.blockers
  if (blockers.length > 0 || (!pre.can_invite && !revising)) {
    const first = blockers[0]
    const params: Record<string, string | number> = {
      ...(pre.pair.block_until ? { until: pre.pair.block_until } : {}),
      ...(first?.params ?? {}),
    }
    return (
      <div className="flex min-w-0 flex-col gap-4">
        <Button variant="ghost" size="sm" className="self-start" onClick={props.onBack}>
          <ArrowLeft aria-hidden="true" /> К карточке
        </Button>
        <BlockerPanel
          code={first?.code ?? 'candidate_unavailable'}
          message={first?.message}
          params={params}
          needId={needId}
        />
      </div>
    )
  }

  opened.current = pre

  const contact = company.data?.contact_method
  const blank: Form = {
    needId: needId ?? null,
    title: '',
    description: '',
    from: null,
    to: null,
    workFormat: pre.candidate_formats[0] ?? '',
    city: '',
    contactKind: contact?.kind ?? 'email',
    contactValue: contact?.value ?? '',
    message: '',
  }
  let initial = blank
  const orig = revision.data ?? null
  if (orig) {
    initial = {
      ...blank,
      needId: orig.need?.id ?? needId ?? null,
      title: orig.title,
      description: orig.description,
      from: orig.salary_from,
      to: orig.salary_to,
      // Условие кандидата по формату: сервер примет пересмотр только с названным форматом.
      workFormat:
        orig.decline?.condition?.kind === 'work_format'
          ? (String(orig.decline.condition.value) as WorkFormat)
          : orig.work_format,
      city: orig.city ?? '',
      contactKind: orig.contact_method.kind,
      contactValue: orig.contact_method.value,
      message: orig.message ?? '',
    }
  } else if (need.data) {
    initial = fromNeed(need.data, pre.candidate_formats, blank)
  }
  const draft = orig ? null : readDraft(draftKey(candidateId, needId))
  const needs = needsList.data ?? (need.data ? [need.data] : [])
  return (
    <Wizard
      props={props}
      precheck={pre}
      initial={draft ?? initial}
      pristine={initial}
      revision={orig}
      needs={needs}
      contactProvided={!!contact}
    />
  )
}
