// biome-ignore-all lint/a11y/useSemanticElements: группа чекбокс-карточек с заголовком вопроса
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { Check } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { SurveyQuestion, SurveySchema } from '@/client'
import { ErrorState, PageHeader, StickyActionBar } from '@/components/app'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Skeleton } from '@/components/ui/skeleton'
import { errorMessage, hasCode, isApiError } from '@/lib/api'
import { invalidateGuardData } from '@/lib/guards'
import { candidateProfileQuery } from '@/lib/query'
import { cn } from '@/lib/utils'
import { draft, putSurvey, surveyQuery } from '../api'
import { ASSESSMENT } from '../content'

type Answers = Record<string, string | string[]>

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
    } else if (specializationHint && !base.specialization) {
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
      await putSurvey({ version: schema.version, answers })
      draft.clear(storageKey)
      await invalidateGuardData(queryClient)
      await navigate({ to: '/candidate/onboarding/grade' })
    } catch (e) {
      if (hasCode(e, 'survey_version_mismatch')) {
        await refetch()
        setError({ message: ASSESSMENT.survey.changed })
      } else if (hasCode(e, 'session_active') && isApiError(e) && e.params.session_id) {
        await navigate({ to: '/candidate/test/$sessionId', params: { sessionId: String(e.params.session_id) } })
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
      <PageHeader title={ASSESSMENT.survey.title} description={ASSESSMENT.survey.description} />
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
        return (
          <section
            key={question.id}
            aria-labelledby={titleId}
            className="surface-card flex min-w-0 flex-col gap-3 p-4 md:p-6"
          >
            <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
              <h2 id={titleId} className="type-h3 min-w-0">
                {title}
                {question.required ? <span aria-hidden="true"> *</span> : null}
              </h2>
              {fromResume.current.has(question.id) ? (
                <span className="type-caption rounded-full bg-brand-50 px-2 py-0.5 text-brand-700">
                  {ASSESSMENT.survey.fromResume}
                </span>
              ) : null}
              {question.kind === 'multi' && question.max ? (
                <span className="type-caption num text-ink-muted">{ASSESSMENT.survey.chosen(count, question.max)}</span>
              ) : null}
            </div>
            {question.kind === 'single' ? (
              <>
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
                        'surface-row flex min-h-14 min-w-0 cursor-pointer items-center gap-3 rounded-md border border-line p-3 font-normal',
                        value === option.code && 'border-brand-600 bg-brand-50',
                        !option.available && 'cursor-not-allowed opacity-60',
                      )}
                    >
                      <RadioGroupItem value={option.code} disabled={!option.available} />
                      <span className="min-w-0 break-words">
                        {option.title}
                        {!option.available ? (
                          <span className="type-caption block text-ink-muted">{ASSESSMENT.survey.notReady}</span>
                        ) : null}
                      </span>
                    </Label>
                  ))}
                </RadioGroup>
                {options.length > 0 && options.every((option) => !option.available) ? (
                  <Alert variant="info">
                    {ASSESSMENT.survey.allNotReady(
                      question.options.filter((option) => option.available).map((option) => option.title),
                    )}
                  </Alert>
                ) : null}
              </>
            ) : (
              <div role="group" aria-labelledby={titleId} className={GRID}>
                {options.map((option) => {
                  const checked = Array.isArray(value) && value.includes(option.code)
                  const blocked = !checked && question.max != null && count >= question.max
                  return (
                    <Label
                      key={option.code}
                      className={cn(
                        'surface-row flex min-h-14 min-w-0 cursor-pointer items-center gap-3 rounded-md border border-line p-3 font-normal',
                        checked && 'border-brand-600 bg-brand-50',
                        (!option.available || blocked) && 'cursor-not-allowed opacity-60',
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
      <StickyActionBar
        note={ready ? undefined : ASSESSMENT.survey.pickHint}
        secondary={
          <Button variant="ghost" asChild>
            <Link to="/candidate/onboarding/profile">Назад</Link>
          </Button>
        }
      >
        <Button variant="primary" loading={saving} disabled={!ready || saving} onClick={submit}>
          {ASSESSMENT.survey.next}
        </Button>
      </StickyActionBar>
    </div>
  )
}
