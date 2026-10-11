import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import {
  CalendarClock,
  ChevronsDown,
  ChevronsUp,
  ClipboardList,
  FileText,
  Hourglass,
  ListChecks,
  type LucideIcon,
  PencilLine,
  ShieldCheck,
  Timer,
} from 'lucide-react'
import { useState } from 'react'
import type { Catalog, TestBlueprintView } from '@/client'
import { ErrorState, IconTile, PageHeader, SoftPill, StickyActionBar } from '@/components/app'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Skeleton } from '@/components/ui/skeleton'
import { errorMessage, hasCode } from '@/lib/api'
import { hasTest } from '@/lib/category'
import { invalidateGuardData } from '@/lib/guards'
import { assessmentStateQuery, candidateProfileQuery } from '@/lib/query'
import { cn } from '@/lib/utils'
import { blueprintsQuery, putClaim, surveyQuery } from '../api'
import { ASSESSMENT } from '../content'
import { blueprintLine } from './briefing-parts'
import { gradeIcon, RuleList } from './parts'

/** Значки правил грейда — по порядку строк `ASSESSMENT.grade.ruleItems`. */
const GRADE_RULE_ICONS: readonly LucideIcon[] = [ShieldCheck, ChevronsDown, ChevronsUp, CalendarClock]

const BAND_GRADE: Record<string, string> = { lt1: 'junior', '1_2': 'junior', '2_4': 'middle', '4_plus': 'senior' }

export function GradePicker({ catalog }: { catalog: Catalog | null }) {
  const state = useQuery(assessmentStateQuery)
  const blueprints = useQuery(blueprintsQuery)
  const profile = useQuery(candidateProfileQuery)
  const survey = useQuery(surveyQuery)
  // Специализация без теста: грейд заявляется, состав теста не нужен — его запрос экран не ждёт.
  const specialization = state.data?.specialization ?? null
  const declared = specialization != null && !hasTest(catalog, specialization.code)
  const failure = state.error ?? (declared ? null : blueprints.error)
  if (failure) {
    return (
      <>
        <PageHeader title={ASSESSMENT.grade.title} />
        <ErrorState
          error={failure}
          onRetry={() => {
            void state.refetch()
            void blueprints.refetch()
          }}
          homeHref="/candidate"
        />
      </>
    )
  }
  if (!state.data || (!declared && !blueprints.data) || profile.isPending || survey.isPending) {
    return (
      <div className="flex flex-col gap-4" aria-busy="true">
        <PageHeader title={ASSESSMENT.grade.title} />
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-28 w-full" />
      </div>
    )
  }
  const band = survey.data?.answers?.experience_band
  return (
    <GradePickerBody
      catalog={catalog}
      blueprints={declared ? [] : (blueprints.data ?? [])}
      declaredFor={declared ? (specialization?.title ?? '') : null}
      claimed={state.data.claimed_grade?.code ?? null}
      resumeHint={profile.data?.hints.grade_hint ?? null}
      surveyHint={typeof band === 'string' ? (BAND_GRADE[band] ?? null) : null}
    />
  )
}

function GradePickerBody({
  catalog,
  blueprints,
  declaredFor,
  claimed,
  resumeHint,
  surveyHint,
}: {
  catalog: Catalog | null
  blueprints: TestBlueprintView[]
  /** Название специализации без теста: грейд заявляется, тест пропускается. null — обычный путь через тест. */
  declaredFor: string | null
  claimed: string | null
  resumeHint: string | null
  surveyHint: string | null
}) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const byGrade = new Map(blueprints.map((b) => [b.grade.code, b]))
  const grades = [...(catalog?.grades ?? [])].sort((a, b) => a.order - b.order)
  const declared = declaredFor != null
  const usable = (code: string) =>
    declared || (grades.find((g) => g.code === code)?.available !== false && byGrade.get(code)?.available !== false)

  const initial = (): { code: string | null; source: 'resume' | 'survey' | null } => {
    if (claimed && usable(claimed)) return { code: claimed, source: null }
    if (resumeHint && usable(resumeHint)) return { code: resumeHint, source: 'resume' }
    if (surveyHint && usable(surveyHint)) return { code: surveyHint, source: 'survey' }
    return { code: null, source: null }
  }
  const [start] = useState(initial)
  const [selected, setSelected] = useState<string | null>(start.code)
  const [source, setSource] = useState(start.source)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const days = Number(catalog?.limits.assessment_grade_change_cooldown_days ?? 90)

  const submit = async () => {
    if (!selected) return
    setSaving(true)
    setError(null)
    try {
      await putClaim(selected)
      await invalidateGuardData(queryClient)
      // Заявленный грейд сразу даёт категорию: тест пропускается, дальше — экран категории с публикацией.
      await navigate({ to: declared ? '/candidate/category' : '/candidate/test/new' })
    } catch (e) {
      if (hasCode(e, 'claim_locked')) await navigate({ to: '/candidate/category' })
      else if (hasCode(e, 'survey_required')) await navigate({ to: '/candidate/onboarding/survey' })
      else {
        if (hasCode(e, 'grade_unavailable')) void queryClient.invalidateQueries({ queryKey: ['catalog'] })
        setError(errorMessage(e))
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <PageHeader
        title={declared ? ASSESSMENT.grade.declared.title : ASSESSMENT.grade.title}
        description={declared ? ASSESSMENT.grade.declared.text(declaredFor, days) : ASSESSMENT.grade.description}
      />
      <RadioGroup
        aria-label={declared ? ASSESSMENT.grade.declared.title : ASSESSMENT.grade.title}
        value={selected ?? ''}
        onValueChange={(code) => {
          setSelected(code)
          setSource(null)
          setError(null)
        }}
        className="gap-3"
      >
        {grades.map((grade, index) => {
          const bp = byGrade.get(grade.code)
          const ok = usable(grade.code)
          const active = selected === grade.code
          return (
            <Label
              key={grade.code}
              className={cn(
                'surface-row flex min-w-0 cursor-pointer items-start gap-3 p-4 font-normal',
                active ? 'accent-card border-brand-600' : ok && 'lift-card',
                !ok && 'cursor-not-allowed border-dashed border-line-strong',
              )}
            >
              <RadioGroupItem value={grade.code} disabled={!ok} className="mt-3" />
              <IconTile icon={gradeIcon(index)} tone={!ok ? 'neutral' : active ? 'solid' : 'brand'} size="lg" />
              <span className="flex min-w-0 flex-1 flex-col gap-1.5">
                <span className="flex min-w-0 flex-wrap items-center gap-2">
                  <span className={cn('type-h3 min-w-0', !ok && 'text-ink-muted')}>{grade.title}</span>
                  {active && source ? (
                    <SoftPill tone="brand" size="sm" icon={source === 'resume' ? FileText : ClipboardList}>
                      {source === 'resume' ? ASSESSMENT.grade.fromResume : ASSESSMENT.grade.fromSurvey}
                    </SoftPill>
                  ) : null}
                </span>
                <span className="type-sm min-w-0 break-words text-ink-muted">{grade.description}</span>
                {declared ? (
                  <span className="type-caption flex min-w-0 items-center gap-1.5 text-ink-muted">
                    <PencilLine aria-hidden="true" className="size-3.5 shrink-0" />
                    <span className="min-w-0">{ASSESSMENT.grade.declared.option}</span>
                  </span>
                ) : ok && bp ? (
                  <span className="flex min-w-0 flex-wrap items-center gap-2" title={blueprintLine(bp)}>
                    <SoftPill size="sm" icon={ListChecks}>
                      <span className="num">{ASSESSMENT.grade.items(bp.items_min, bp.items_max)}</span>
                    </SoftPill>
                    <SoftPill size="sm" icon={Timer}>
                      <span className="num">{ASSESSMENT.grade.minutes(bp.time_limit_min, bp.time_limit_max_min)}</span>
                    </SoftPill>
                    <span className="sr-only">{blueprintLine(bp)}</span>
                  </span>
                ) : (
                  <SoftPill size="sm" icon={Hourglass} className="self-start">
                    {ASSESSMENT.grade.notReady}
                  </SoftPill>
                )}
              </span>
            </Label>
          )
        })}
      </RadioGroup>
      {declared ? null : (
        <section className="surface-card min-w-0" aria-label={ASSESSMENT.grade.rulesTitle}>
          <RuleList
            columns={2}
            items={ASSESSMENT.grade.ruleItems(days).map((text, i) => ({
              icon: GRADE_RULE_ICONS[i] ?? ShieldCheck,
              tone: i === 0 ? 'success' : 'soft',
              text,
            }))}
          />
        </section>
      )}
      {error ? <Alert variant="destructive">{error}</Alert> : null}
      <StickyActionBar
        note={selected ? undefined : ASSESSMENT.grade.pick}
        secondary={
          <Button variant="ghost" asChild>
            <Link to="/candidate/onboarding/survey">Назад</Link>
          </Button>
        }
      >
        <Button variant="primary" loading={saving} disabled={!selected || saving} onClick={submit}>
          {declared ? ASSESSMENT.grade.declared.next : ASSESSMENT.grade.next}
        </Button>
      </StickyActionBar>
    </div>
  )
}
