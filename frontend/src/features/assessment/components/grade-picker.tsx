import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import type { Catalog, TestBlueprintView } from '@/client'
import { ErrorState, PageHeader, StickyActionBar } from '@/components/app'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Skeleton } from '@/components/ui/skeleton'
import { errorMessage, hasCode } from '@/lib/api'
import { invalidateGuardData } from '@/lib/guards'
import { assessmentStateQuery, candidateProfileQuery } from '@/lib/query'
import { cn } from '@/lib/utils'
import { blueprintsQuery, putClaim, surveyQuery } from '../api'
import { ASSESSMENT } from '../content'
import { blueprintLine } from './briefing-parts'

const BAND_GRADE: Record<string, string> = { lt1: 'junior', '1_2': 'junior', '2_4': 'middle', '4_plus': 'senior' }

export function GradePicker({ catalog }: { catalog: Catalog | null }) {
  const state = useQuery(assessmentStateQuery)
  const blueprints = useQuery(blueprintsQuery)
  const profile = useQuery(candidateProfileQuery)
  const survey = useQuery(surveyQuery)
  const failure = state.error ?? blueprints.error
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
  if (!state.data || !blueprints.data || profile.isPending || survey.isPending) {
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
      blueprints={blueprints.data}
      claimed={state.data.claimed_grade?.code ?? null}
      resumeHint={profile.data?.hints.grade_hint ?? null}
      surveyHint={typeof band === 'string' ? (BAND_GRADE[band] ?? null) : null}
    />
  )
}

function GradePickerBody({
  catalog,
  blueprints,
  claimed,
  resumeHint,
  surveyHint,
}: {
  catalog: Catalog | null
  blueprints: TestBlueprintView[]
  claimed: string | null
  resumeHint: string | null
  surveyHint: string | null
}) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const byGrade = new Map(blueprints.map((b) => [b.grade.code, b]))
  const grades = [...(catalog?.grades ?? [])].sort((a, b) => a.order - b.order)
  const usable = (code: string) =>
    grades.find((g) => g.code === code)?.available !== false && byGrade.get(code)?.available !== false

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
      await navigate({ to: '/candidate/test/new' })
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
      <PageHeader title={ASSESSMENT.grade.title} description={ASSESSMENT.grade.description} />
      <RadioGroup
        aria-label={ASSESSMENT.grade.title}
        value={selected ?? ''}
        onValueChange={(code) => {
          setSelected(code)
          setSource(null)
          setError(null)
        }}
        className="gap-3"
      >
        {grades.map((grade) => {
          const bp = byGrade.get(grade.code)
          const ok = usable(grade.code)
          return (
            <Label
              key={grade.code}
              className={cn(
                'surface-row flex min-w-0 cursor-pointer items-start gap-3 rounded-md border border-line p-4 font-normal',
                selected === grade.code && 'border-brand-600 bg-brand-50',
                !ok && 'cursor-not-allowed opacity-60',
              )}
            >
              <RadioGroupItem value={grade.code} disabled={!ok} className="mt-0.5" />
              <span className="flex min-w-0 flex-1 flex-col gap-1">
                <span className="flex min-w-0 flex-wrap items-center gap-2">
                  <span className="type-h3 min-w-0">{grade.title}</span>
                  {selected === grade.code && source ? (
                    <span className="type-caption rounded-full bg-brand-50 px-2 py-0.5 text-brand-700">
                      {source === 'resume' ? ASSESSMENT.grade.fromResume : ASSESSMENT.grade.fromSurvey}
                    </span>
                  ) : null}
                </span>
                <span className="type-sm min-w-0 break-words text-ink-muted">{grade.description}</span>
                {ok && bp ? (
                  <span className="font-mono type-caption min-w-0 break-words text-ink">{blueprintLine(bp)}</span>
                ) : (
                  <span className="type-caption text-ink-muted">{ASSESSMENT.grade.notReady}</span>
                )}
              </span>
            </Label>
          )
        })}
      </RadioGroup>
      <Alert variant="info">{ASSESSMENT.grade.rules(days)}</Alert>
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
          {ASSESSMENT.grade.next}
        </Button>
      </StickyActionBar>
    </div>
  )
}
