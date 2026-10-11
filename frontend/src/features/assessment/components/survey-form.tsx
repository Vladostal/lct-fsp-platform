// biome-ignore-all lint/a11y/useSemanticElements: группа чекбокс-карточек с заголовком вопроса
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import {
  BadgeCheck,
  Braces,
  Briefcase,
  Building2,
  Check,
  CircleHelp,
  Code,
  Compass,
  FileText,
  Hourglass,
  ListChecks,
  type LucideIcon,
  PencilLine,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { SurveyQuestion, SurveySchema } from '@/client'
import { ErrorState, IconTile, PageHeader, SoftPill, StickyActionBar } from '@/components/app'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Skeleton } from '@/components/ui/skeleton'
import { errorMessage, hasCode, isApiError } from '@/lib/api'
import { invalidateGuardData } from '@/lib/guards'
import { assessmentStateQuery, candidateProfileQuery, catalogQuery } from '@/lib/query'
import { cn } from '@/lib/utils'
import { draft, putSurvey, surveyQuery } from '../api'
import { ASSESSMENT } from '../content'
import { RuleList, specIcon } from './parts'

type Answers = Record<string, string | string[]>

/** Карточка-вариант: белая с границей; выбранная — граница бренда и заливка brand-50. */
const OPTION =
  'flex min-h-14 min-w-0 cursor-pointer items-center gap-3 rounded-md border border-line bg-surface p-3 font-normal transition-colors'
const OPTION_ON = 'border-brand-600 bg-brand-50'

const QUESTION_ICONS: Record<string, LucideIcon> = {
  direction: Compass,
  specialization: Code,
  main_language: Braces,
  experience_band: Briefcase,
  industry_domains: Building2,
}
/** Значки строк `ASSESSMENT.survey.facts` — по порядку. */
const FACT_ICONS: readonly LucideIcon[] = [ListChecks, BadgeCheck, PencilLine]

const GRID = 'grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(min(100%,200px),1fr))]'

function parentAnswer(question: SurveyQuestion, answers: Answers): string | null {
  if (!question.depends_on) return null
  const value = answers[question.depends_on]
  return typeof value === 'string' ? value : null
}

function isVisible(question: SurveyQuestion, answers: Answers): boolean {
  return !question.depends_on || parentAnswer(question, answers) != null
}

/** Варианты вопроса с учётом родителя: вариант без `parent` показывается всегда. */
function optionsFor(question: SurveyQuestion, answers: Answers) {
  const parent = parentAnswer(question, answers)
  return question.options.filter((o) => !o.parent || !question.depends_on || o.parent === parent)
}

/** Оставляет только ответы, которые есть в схеме; зависимые от изменённого родителя сбрасываются отдельно. */
function sanitize(schema: SurveySchema, answers: Answers): Answers {
  const result: Answers = {}
  for (const q of schema.questions) {
    const value = answers[q.id]
    if (value == null) continue
    const codes = new Set(optionsFor(q, { ...result, ...answers }).map((o) => o.code))
    if (q.kind === 'single' && typeof value === 'string' && codes.has(value)) result[q.id] = value
    if (q.kind === 'multi' && Array.isArray(value)) {
      const kept = value.filter((v) => codes.has(v))
      if (kept.length > 0) result[q.id] = kept
    }
  }
  return result
}

function dependents(schema: SurveySchema, id: string): string[] {
  const out: string[] = []
  for (const q of schema.questions) {
    if (q.depends_on === id) out.push(q.id, ...dependents(schema, q.id))
  }
  return out
}

export function SurveyForm({ userId }: { userId: string }) {
  const query = useQuery(surveyQuery)
  const profile = useQuery(candidateProfileQuery)
  if (query.isPending) {
    return (
      <div className="flex flex-col gap-4" aria-busy="true">
        <PageHeader title={ASSESSMENT.survey.title} />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }
  if (query.isError) {
    return (
      <>
        <PageHeader title={ASSESSMENT.survey.title} />
        <ErrorState error={query.error} onRetry={() => query.refetch()} homeHref="/candidate" />
      </>
    )
  }
  return (
    <SurveyFormBody
      schema={query.data}
      userId={userId}
      specializationHint={profile.data?.hints.specialization_hint ?? null}
      refetch={() => query.refetch()}
    />
  )
}

function SurveyFormBody({
  schema,
  userId,
  specializationHint,
  refetch,
}: {
  schema: SurveySchema
  userId: string
  specializationHint: string | null
  refetch: () => Promise<unknown>
}) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const storageKey = `onboarding:survey:${userId}`
  const fromResume = useRef<Set<string>>(new Set())

  const [answers, setAnswers] = useState<Answers>(() => {
    let base: Answers = { ...(schema.answers ?? {}) }
    const saved = draft.read(storageKey)
    if (saved) {
      try {
        base = { ...base, ...(JSON.parse(saved) as Answers) }
      } catch {
        /* повреждённый черновик игнорируется */
      }
    }
    if (specializationHint && !base.specialization) {
      const spec = schema.questions.flatMap((q) => q.options).find((o) => o.code === specializationHint && o.available)
      const specQuestion = schema.questions.find((q) => q.options.includes(spec as never))
      if (spec && specQuestion) {
        base[specQuestion.id] = spec.code
        fromResume.current.add(specQuestion.id)
        if (spec.parent && specQuestion.depends_on) {
          base[specQuestion.depends_on] = spec.parent
          fromResume.current.add(specQuestion.depends_on)
        }
      }
    }
    return sanitize(schema, base)
  })
  const [resetNote, setResetNote] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<{ message: string; questionId?: string } | null>(null)
  // Сервер просит подтвердить смену специализации (409): текст зависит от того, что будет заменено.
  const [confirm, setConfirm] = useState<string | null>(null)
  const catalog = useQuery(catalogQuery).data
  const changeDays = Number(catalog?.limits.assessment_specialization_change_cooldown_days ?? 90)
  // Категория или тест уже есть: опрос открыт из «Категории и тестов» (смена специализации), туда же и «Назад».
  const state = useQuery(assessmentStateQuery).data
  const returning = state != null && (state.category != null || state.last_session != null)

  useEffect(() => {
    draft.write(storageKey, JSON.stringify(answers))
  }, [answers, storageKey])

  const visible = useMemo(() => schema.questions.filter((q) => isVisible(q, answers)), [schema, answers])
  const ready = visible.every((q) => !q.required || (answers[q.id] != null && answers[q.id]?.length !== 0))

  const setAnswer = (question: SurveyQuestion, value: string | string[]) => {
    const next: Answers = { ...answers, [question.id]: value }
    const reset = dependents(schema, question.id).filter((id) => next[id] != null)
    for (const id of reset) delete next[id]
    setResetNote(reset.length > 0)
    fromResume.current.delete(question.id)
    setError(null)
    setConfirm(null)
    setAnswers(next)
  }

  const toggle = (question: SurveyQuestion, code: string) => {
    const current = Array.isArray(answers[question.id]) ? (answers[question.id] as string[]) : []
    if (current.includes(code)) {
      const rest = current.filter((c) => c !== code)
      const next = { ...answers }
      if (rest.length === 0) delete next[question.id]
      else next[question.id] = rest
      setAnswers(next)
    } else if (!question.max || current.length < question.max) {
      setAnswer(question, [...current, code])
    }
  }

  const submit = async () => {
    setSaving(true)
    setError(null)
    try {
      await putSurvey({ version: schema.version, answers, confirm_specialization_change: confirm != null })
      draft.clear(storageKey)
      await invalidateGuardData(queryClient)
      await navigate({ to: '/candidate/onboarding/grade' })
    } catch (e) {
      if (hasCode(e, 'survey_version_mismatch')) {
        await refetch()
        setError({ message: ASSESSMENT.survey.changed })
      } else if (hasCode(e, 'session_active') && isApiError(e) && e.params.session_id) {
        await navigate({ to: '/candidate/test/$sessionId', params: { sessionId: String(e.params.session_id) } })
      } else if (hasCode(e, 'specialization_change_requires_confirm')) {
        setConfirm(
          isApiError(e) && (e.params as Record<string, unknown>).replaces_confirmed_category === true
            ? ASSESSMENT.survey.confirmReplace(changeDays)
            : ASSESSMENT.survey.confirmReset(changeDays),
        )
      } else if (hasCode(e, 'specialization_unavailable')) {
        setError({ message: errorMessage(e), questionId: 'specialization' })
      } else {
        setError({ message: errorMessage(e) })
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <PageHeader title={ASSESSMENT.survey.title} />
      <section className="surface-card brand-band min-w-0 animate-rise-in" aria-label={ASSESSMENT.survey.factsTitle}>
        <RuleList
          columns={3}
          items={ASSESSMENT.survey.facts.map((text, i) => ({ icon: FACT_ICONS[i] ?? ListChecks, tone: 'plain', text }))}
        />
      </section>
      {resetNote ? (
        <Alert variant="info" live>
          {ASSESSMENT.survey.resetNote}
        </Alert>
      ) : null}
      {visible.map((question) => {
        const options = optionsFor(question, answers)
        const value = answers[question.id]
        const titleId = `q-${question.id}`
        const title = question.id === 'industry_domains' ? ASSESSMENT.survey.industryTitle : question.title
        const count = Array.isArray(value) ? value.length : 0
        const answered = typeof value === 'string' ? value !== '' : count > 0
        const withIcons = question.id === 'direction' || question.id === 'specialization'
        return (
          <section key={question.id} aria-labelledby={titleId} className="surface-card flex min-w-0 flex-col gap-3">
            <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
              <IconTile icon={QUESTION_ICONS[question.id] ?? CircleHelp} tone={answered ? 'solid' : 'brand'} />
              <h2 id={titleId} className="type-h3 min-w-0 flex-1">
                {title}
                {question.required ? <span aria-hidden="true"> *</span> : null}
              </h2>
              {fromResume.current.has(question.id) ? (
                <SoftPill tone="brand" size="sm" icon={FileText}>
                  {ASSESSMENT.survey.fromResume}
                </SoftPill>
              ) : null}
              {question.kind === 'multi' && question.max ? (
                <SoftPill size="sm" tone={count > 0 ? 'brand' : 'neutral'}>
                  <span className="num">{ASSESSMENT.survey.chosen(count, question.max)}</span>
                </SoftPill>
              ) : null}
            </div>
            {question.kind === 'single' ? (
              <RadioGroup
                aria-labelledby={titleId}
                value={typeof value === 'string' ? value : ''}
                onValueChange={(code) => setAnswer(question, code)}
                className={GRID}
              >
                {options.map((option) => (
                  <Label
                    key={option.code}
                    className={cn(
                      OPTION,
                      value === option.code ? OPTION_ON : 'hover:border-brand-200',
                      !option.available && value !== option.code && 'border-dashed border-line-strong',
                      !option.available && 'flex-wrap gap-y-1.5',
                    )}
                  >
                    {/* `available === false` — теста нет: вариант выбирается, грейд по нему будет заявленным. */}
                    <RadioGroupItem value={option.code} />
                    {withIcons ? (
                      <IconTile
                        icon={specIcon(option.code)}
                        size="sm"
                        tone={value === option.code ? 'solid' : option.available ? 'brand' : 'neutral'}
                      />
                    ) : null}
                    <span className="min-w-0 flex-1 break-words">{option.title}</span>
                    {!option.available ? (
                      // Пилюля — отдельной строкой во всю ширину карточки: рядом с названием она не помещается.
                      <span className="flex min-w-0 basis-full pl-8">
                        <SoftPill
                          size="sm"
                          icon={Hourglass}
                          className="border border-dashed border-line-strong bg-transparent"
                        >
                          <span className="min-w-0 truncate" title={ASSESSMENT.survey.notReady}>
                            {ASSESSMENT.grade.notReady}
                          </span>
                        </SoftPill>
                      </span>
                    ) : null}
                  </Label>
                ))}
              </RadioGroup>
            ) : (
              <div role="group" aria-labelledby={titleId} className={GRID}>
                {options.map((option) => {
                  const checked = Array.isArray(value) && value.includes(option.code)
                  const blocked = !checked && question.max != null && count >= question.max
                  return (
                    <Label
                      key={option.code}
                      className={cn(
                        OPTION,
                        checked ? OPTION_ON : 'hover:border-brand-200',
                        (!option.available || blocked) && 'cursor-not-allowed opacity-60 hover:border-line',
                      )}
                    >
                      <Checkbox
                        checked={checked}
                        disabled={!option.available || blocked}
                        onCheckedChange={() => toggle(question, option.code)}
                      />
                      <span className="min-w-0 break-words">{option.title}</span>
                      {checked ? <Check className="ml-auto size-4 shrink-0 text-brand-700" aria-hidden="true" /> : null}
                    </Label>
                  )
                })}
              </div>
            )}
            {error?.questionId === question.id ? (
              <p role="alert" className="type-sm text-danger">
                {error.message}
              </p>
            ) : null}
          </section>
        )
      })}
      {error && !error.questionId ? <Alert variant="destructive">{error.message}</Alert> : null}
      {confirm ? (
        <Alert variant="warning" live>
          {confirm}
        </Alert>
      ) : null}
      <StickyActionBar
        note={ready ? undefined : ASSESSMENT.survey.pickHint}
        secondary={
          <Button variant="ghost" asChild>
            <Link to={returning ? '/candidate/category' : '/candidate/onboarding/profile'}>Назад</Link>
          </Button>
        }
      >
        <Button variant="primary" loading={saving} disabled={!ready || saving} onClick={submit}>
          {confirm ? ASSESSMENT.survey.confirmNext : ASSESSMENT.survey.next}
        </Button>
      </StickyActionBar>
    </div>
  )
}
