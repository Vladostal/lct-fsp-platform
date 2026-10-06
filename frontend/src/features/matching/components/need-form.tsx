import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useBlocker, useNavigate } from '@tanstack/react-router'
import { useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import type { Catalog, NeedDraft, NeedView, WorkFormat } from '@/client'
import {
  EmptyState,
  ErrorState,
  PageHeader,
  SalaryRangeInput,
  type SalaryRangeValue,
  Stepper,
  TagInput,
  type TagValue,
  validateSalaryRange,
} from '@/components/app'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { WIZARD_STEPS } from '@/content/common'
import { applyFieldErrors, errorMessage, errorText, hasCode, hasStatus, isApiError } from '@/lib/api'
import { formatMoney } from '@/lib/format'
import { invalidateGuardData } from '@/lib/guards'
import { needsQuery, queryKeys } from '@/lib/query'
import { createNeed, createShortlist, matchingKeys, needQuery, parseNeed, salaryHintQuery, updateNeed } from '../api'
import { MATCHING, WORK_FORMATS } from '../content'
import { NeedBlueprint } from './need-blueprint'
import { noticeKey } from './need-screen'
import { salaryLimits } from './refine-panel'
import { retryText } from './shortlist-tab'

const F = MATCHING.form

type Draft = {
  title: string
  spec: string
  grade: string
  must: TagValue[]
  nice: TagValue[]
  formats: WorkFormat[]
  city: string
  salary: SalaryRangeValue
  team: string
}

const EMPTY: Draft = {
  title: '',
  spec: '',
  grade: '',
  must: [],
  nice: [],
  formats: [],
  city: '',
  salary: { from: null, to: null },
  team: '',
}

type Meta = { fromText: string[]; low: string[] }

function toDraft(n: NeedView): Draft {
  return {
    title: n.title,
    spec: n.target.specialization.code,
    grade: n.target.grade.code,
    must: n.must_skills.map((s) => ({ code: s.code, title: s.title })),
    nice: n.nice_skills.map((s) => ({ code: s.code, title: s.title })),
    formats: n.work_formats,
    city: n.city ?? '',
    salary: { from: n.salary_from, to: n.salary_to },
    team: n.team_description,
  }
}

type Props = { needId?: string; catalog: Catalog | null | undefined; userId: string }

export function NeedFormScreen({ needId, catalog, userId }: Props) {
  const needs = useQuery(needsQuery)
  const existing = useQuery({ ...needQuery(needId ?? ''), enabled: Boolean(needId) })
  if (needId) {
    if (existing.isPending)
      return (
        <p role="status" className="type-sm text-ink-muted">
          Загружаем потребность…
        </p>
      )
    if (existing.isError) return <ErrorState error={existing.error} onRetry={() => existing.refetch()} />
  }
  if (needs.isPending)
    return (
      <p role="status" className="type-sm text-ink-muted">
        Загружаем…
      </p>
    )
  const first = !needId && (needs.data?.length ?? 0) === 0
  return <NeedForm need={existing.data} catalog={catalog} userId={userId} first={first} />
}

function NeedForm({
  need,
  catalog,
  userId,
  first,
}: {
  need?: NeedView
  catalog: Catalog | null | undefined
  userId: string
  first: boolean
}) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const storageKey = `need:${need?.id ?? 'new'}:${userId}`
  const base = useMemo(() => (need ? toDraft(need) : EMPTY), [need])
  const [draft, setDraft] = useState<Draft>(() => {
    try {
      const raw = sessionStorage.getItem(storageKey)
      if (raw) return { ...base, ...(JSON.parse(raw) as Partial<Draft>) }
    } catch {
      /* хранилище недоступно */
    }
    return base
  })
  const [text, setText] = useState(need?.source_text ?? '')
  const [textError, setTextError] = useState<string | null>(null)
  const [meta, setMeta] = useState<Meta>({ fromText: [], low: [] })
  const [parsed, setParsed] = useState<NeedDraft | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [salaryError, setSalaryError] = useState<string | null>(null)
  const [submitted, setSubmitted] = useState(false)
  const touched = useRef(new Set<string>())
  const savedRef = useRef(false)
  const archived = need?.status === 'archived'
  const limits = salaryLimits(catalog)
  const dirty = !savedRef.current && JSON.stringify(draft) !== JSON.stringify(base)

  useBlocker({
    shouldBlockFn: () => dirty && !window.confirm(F.leave),
    enableBeforeUnload: () => dirty,
  })
  useEffect(() => {
    try {
      if (dirty) sessionStorage.setItem(storageKey, JSON.stringify(draft))
    } catch {
      /* хранилище недоступно */
    }
  }, [draft, dirty, storageKey])

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => {
    touched.current.add(key)
    setDraft((d) => ({ ...d, [key]: value }))
    setErrors((e) => {
      const { [key]: _drop, ...rest } = e
      return rest
    })
    setMeta((m) => ({ ...m, fromText: m.fromText.filter((k) => k !== key), low: m.low.filter((k) => k !== key) }))
    if (key === 'salary') setSalaryError(null)
  }

  const skillOptions = (catalog?.skills ?? []).map((s) => ({ code: s.code, title: s.title, aliases: s.aliases }))
  const titleOf = (code: string) => catalog?.skills.find((s) => s.code === code)?.title ?? code

  const parse = useMutation({
    mutationFn: () => parseNeed(text),
    onSuccess: (d) => {
      setTextError(null)
      setParsed(d)
      const filled: string[] = []
      const low: string[] = []
      const patch: Partial<Draft> = {}
      const conf = d.confidence ?? {}
      const take = <K extends keyof Draft>(field: K, key: string, value: Draft[K] | null | undefined) => {
        if (value == null || touched.current.has(field)) return
        if (Array.isArray(value) && value.length === 0) return
        patch[field] = value
        filled.push(field)
        if (conf[key] === 'low') low.push(field)
      }
      take('title', 'title', d.title)
      take('spec', 'specialization_code', d.specialization_code)
      take('grade', 'grade_code', d.grade_code)
      take('team', 'team_description', d.team_description)
      take('city', 'city', d.city)
      take('formats', 'work_formats', d.work_formats as WorkFormat[] | undefined)
      take(
        'must',
        'must_skills',
        d.must_skills?.map((c) => ({ code: c, title: titleOf(c) })),
      )
      take(
        'nice',
        'nice_skills',
        d.nice_skills?.map((c) => ({ code: c, title: titleOf(c) })),
      )
      if (d.salary_from != null && d.salary_to != null && !touched.current.has('salary')) {
        patch.salary = { from: d.salary_from, to: d.salary_to }
        filled.push('salary')
      }
      setDraft((cur) => ({ ...cur, ...patch }))
      setMeta({ fromText: filled, low })
    },
    onError: (e) => {
      if (hasCode(e, 'text_too_short', 'text_too_long')) setTextError(errorText(e.code, e.params))
      else setTextError(errorMessage(e))
    },
  })

  const spec = catalog?.specializations.find((s) => s.code === draft.spec)
  const category = draft.spec && draft.grade ? `${draft.spec}:${draft.grade}` : ''
  const hint = useQuery({ ...salaryHintQuery(category), enabled: Boolean(category) })
  const unavailable = Boolean(spec && !spec.available)
  const needsCity = draft.formats.includes('office') || draft.formats.includes('hybrid')

  const validate = (): Record<string, string> => {
    const e: Record<string, string> = {}
    if (draft.title.trim().length < 3 || draft.title.trim().length > 100) e.title = F.titleLen
    if (!draft.spec) e.spec = F.specRequired
    else if (unavailable) e.spec = F.unavailableTitle
    if (!draft.grade) e.grade = F.gradeRequired
    if (draft.formats.length === 0) e.formats = F.formatRequired
    if (needsCity && !draft.city.trim()) e.city = F.cityRequired
    if (draft.team.trim().length < 10 || draft.team.trim().length > 1000) e.team = F.teamLen
    const issue = validateSalaryRange(draft.salary, limits)
    if (draft.salary.from == null || draft.salary.to == null) e.salary = 'Укажите вилку: «от» и «до»'
    else if (issue) e.salary = errorText(issue.code, issue.params)
    return e
  }

  const payload = () => ({
    title: draft.title.trim(),
    specialization_code: draft.spec,
    grade_code: draft.grade,
    must_skills: draft.must.map((t) => t.code).filter((c): c is string => Boolean(c)),
    nice_skills: draft.nice.map((t) => t.code).filter((c): c is string => Boolean(c)),
    work_formats: draft.formats,
    city: draft.city.trim() || null,
    salary_from: draft.salary.from ?? 0,
    salary_to: draft.salary.to ?? 0,
    team_description: draft.team.trim(),
    source_text: text.trim() || null,
    parse_meta: parsed
      ? {
          parser: parsed.parser,
          parser_version: parsed.parser_version,
          filled: meta.fromText,
          warnings: parsed.warnings,
        }
      : null,
  })

  const [mode, setMode] = useState<'create' | 'update' | 'only' | null>(null)
  const save = useMutation({
    mutationFn: async (m: 'create' | 'update' | 'only') => {
      setMode(m)
      const saved = need ? await updateNeed(need.id, payload()) : await createNeed(payload())
      let shortlistError: unknown = null
      if (m !== 'only') {
        try {
          await createShortlist(saved.id, {})
        } catch (e) {
          shortlistError = e
        }
      }
      return { saved, shortlistError, mode: m }
    },
    onSuccess: async ({ saved, shortlistError, mode: m }) => {
      savedRef.current = true
      try {
        sessionStorage.removeItem(storageKey)
      } catch {
        /* нет хранилища */
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.employer.needs }),
        queryClient.invalidateQueries({ queryKey: matchingKeys.shortlists(saved.id) }),
        invalidateGuardData(queryClient),
      ])
      if (shortlistError) {
        try {
          sessionStorage.setItem(noticeKey(saved.id), F.shortlistFailed(retryText(shortlistError)))
        } catch {
          /* нет хранилища */
        }
      }
      if (m === 'only') {
        toast.success(F.savedNoRefresh)
        navigate({ to: '/employer/needs/$needId', params: { needId: saved.id }, search: { tab: 'description' } })
      } else navigate({ to: '/employer/needs/$needId', params: { needId: saved.id } })
    },
    onError: (error) => {
      if (hasCode(error, 'company_profile_incomplete', 'company_profile_required')) {
        toast.error('Сначала заполните профиль компании')
        navigate({ to: '/employer/onboarding/company' })
        return
      }
      if (hasCode(error, 'salary_order', 'salary_out_of_bounds', 'salary_range_too_wide', 'salary_range_invalid')) {
        setSalaryError(errorText(error.code, error.params))
        return
      }
      if (hasCode(error, 'specialization_unavailable', 'specialization_without_test')) {
        setErrors((e) => ({ ...e, spec: F.unavailableTitle }))
        return
      }
      if (isApiError(error) && error.fields.length > 0) {
        const map: Record<string, string> = {
          specialization_code: 'spec',
          grade_code: 'grade',
          team_description: 'team',
        }
        const found: Record<string, string> = {}
        for (const f of error.fields) found[map[f.name] ?? f.name] = f.message
        setErrors((cur) => ({ ...cur, ...found }))
        applyFieldErrors(error, () => undefined, [] as never)
        return
      }
      if (hasStatus(error, 409)) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.employer.needs })
      }
      setFormError(errorMessage(error))
    },
  })

  const submit = (m: 'create' | 'update' | 'only') => (event?: React.SyntheticEvent) => {
    event?.preventDefault()
    setSubmitted(true)
    setFormError(null)
    const found = validate()
    setErrors(found)
    if (Object.keys(found).length > 0) {
      requestAnimationFrame(() => document.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus())
      return
    }
    save.mutate(m)
  }

  const chip = (field: string) =>
    meta.fromText.includes(field) ? (
      <span className="type-caption ml-2 rounded-full bg-brand-50 px-2 py-0.5 font-normal text-brand-700">
        {F.fromText}
        {meta.low.includes(field) ? ` · ${F.check}` : ''}
      </span>
    ) : null

  const err = (key: string) =>
    errors[key] ? (
      <p role="alert" className="type-sm text-danger">
        {errors[key]}
      </p>
    ) : null

  const mustCodes = draft.must.map((t) => t.code).filter((c): c is string => Boolean(c))
  const niceCodes = draft.nice.map((t) => t.code).filter((c): c is string => Boolean(c))

  const onMust = (v: TagValue[]) => {
    set('must', v)
    const codes = new Set(v.map((t) => t.code))
    if (draft.nice.some((t) => codes.has(t.code))) {
      setDraft((d) => ({ ...d, must: v, nice: d.nice.filter((t) => !codes.has(t.code)) }))
      toast.message(F.mustMoved)
    }
  }
  const onNice = (v: TagValue[]) => {
    const codes = new Set(draft.must.map((t) => t.code))
    const filtered = v.filter((t) => !codes.has(t.code))
    if (filtered.length !== v.length) toast.message(F.mustMoved)
    set('nice', filtered)
  }

  const availableSpecs = catalog?.specializations ?? []
  const grades = (catalog?.grades ?? []).filter((g) => g.available)
  const availableLinks = availableSpecs.filter((s) => s.available)
  const hintValue = hint.data

  const header = <PageHeader title={need ? F.editTitle : F.createTitle} description={F.description} />

  return (
    <div className="flex min-w-0 flex-col gap-6">
      {first ? <Stepper steps={WIZARD_STEPS.employer} current="need" /> : null}
      {header}
      {archived ? (
        <Alert variant="info">
          <AlertDescription>{F.archivedAlert}</AlertDescription>
        </Alert>
      ) : null}
      <div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
        <aside className="surface-card min-w-0 p-5 lg:order-2 lg:sticky lg:top-24 lg:h-fit">
          <h2 className="type-h3 mb-3">{F.help.title}</h2>
          <dl className="flex min-w-0 flex-col gap-3">
            {F.help.items.map(([k, v]) => (
              <div key={k} className="min-w-0">
                <dt className="type-sm font-medium">{k}</dt>
                <dd className="type-sm text-ink-muted">{v}</dd>
              </div>
            ))}
          </dl>
          <a href="/how-it-works#matching" className="text-link type-sm mt-3 inline-block">
            {F.help.link}
          </a>
        </aside>

        <form
          className="flex min-w-0 flex-col gap-6 lg:order-1"
          onSubmit={submit(need ? 'update' : 'create')}
          noValidate
        >
          {formError ? (
            <Alert variant="destructive">
              <AlertDescription>{formError}</AlertDescription>
            </Alert>
          ) : null}
          {meta.fromText.length > 0 ? (
            <Alert variant="info">
              <AlertDescription>{F.parsedAlert(meta.fromText.length)}</AlertDescription>
            </Alert>
          ) : null}
          {parsed ? <ParseNotes parsed={parsed} /> : null}

          {!need ? (
            <section className="surface-card flex min-w-0 flex-col gap-3 p-5" aria-labelledby="n-text">
              <h2 id="n-text" className="type-h3">
                {F.textLabel}
              </h2>
              <Textarea
                aria-labelledby="n-text"
                rows={5}
                value={text}
                aria-invalid={Boolean(textError)}
                onChange={(e) => {
                  setText(e.target.value)
                  setTextError(null)
                }}
              />
              <p className="type-sm text-ink-muted">{F.textHint}</p>
              {textError ? (
                <p role="alert" className="type-sm text-danger">
                  {textError}
                </p>
              ) : null}
              <Button
                type="button"
                variant="secondary"
                className="self-start"
                loading={parse.isPending}
                disabled={text.trim().length === 0}
                onClick={() => parse.mutate()}
              >
                {F.parse}
              </Button>
            </section>
          ) : null}

          <fieldset disabled={archived} className="contents">
            <section className="surface-card flex min-w-0 flex-col gap-4 p-5" aria-labelledby="n-whom">
              <h2 id="n-whom" className="type-h3">
                {F.whom}
              </h2>
              <div className="flex min-w-0 flex-col gap-1.5">
                <Label htmlFor="n-title">
                  {F.titleField} *{chip('title')}
                </Label>
                <Input
                  id="n-title"
                  value={draft.title}
                  maxLength={100}
                  aria-invalid={Boolean(errors.title)}
                  onChange={(e) => set('title', e.target.value)}
                />
                {err('title')}
              </div>
              <div className="flex min-w-0 flex-col gap-1.5">
                <Label htmlFor="n-spec">
                  {F.specialization} *{chip('spec')}
                </Label>
                <Select value={draft.spec} onValueChange={(v) => set('spec', v)}>
                  <SelectTrigger id="n-spec" aria-invalid={Boolean(errors.spec)}>
                    <SelectValue placeholder="Выберите специализацию" />
                  </SelectTrigger>
                  <SelectContent>
                    {availableSpecs.map((s) => (
                      <SelectItem key={s.code} value={s.code} disabled={!s.available}>
                        {s.title}
                        {s.available ? '' : ` — ${F.unavailable}`}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {err('spec')}
                {unavailable ? (
                  <Alert variant="info">
                    <AlertDescription className="flex min-w-0 flex-col gap-1">
                      <span className="font-medium">{F.unavailableTitle}</span>
                      <span>{F.unavailableText}</span>
                      <span>{availableLinks.map((s) => s.title).join(', ')}</span>
                    </AlertDescription>
                  </Alert>
                ) : null}
              </div>
              <div className="flex min-w-0 flex-col gap-1.5">
                <span id="n-grade-l" className="type-sm font-medium">
                  {F.grade} *{chip('grade')}
                </span>
                <ToggleGroup
                  type="single"
                  value={draft.grade}
                  aria-labelledby="n-grade-l"
                  onValueChange={(v) => v && set('grade', v)}
                >
                  {grades.map((g) => (
                    <ToggleGroupItem key={g.code} value={g.code}>
                      {g.title}
                    </ToggleGroupItem>
                  ))}
                </ToggleGroup>
                {err('grade')}
              </div>
            </section>

            <section className="surface-card flex min-w-0 flex-col gap-4 p-5" aria-labelledby="n-skills">
              <h2 id="n-skills" className="type-h3">
                {F.skills}
              </h2>
              <div className="flex min-w-0 flex-col gap-1">
                <TagInput label={F.must} value={draft.must} onChange={onMust} options={skillOptions} max={8} />
                {chip('must')}
              </div>
              <div className="flex min-w-0 flex-col gap-1">
                <TagInput label={F.nice} value={draft.nice} onChange={onNice} options={skillOptions} max={12} />
                {chip('nice')}
              </div>
            </section>

            <section className="surface-card flex min-w-0 flex-col gap-4 p-5" aria-labelledby="n-cond">
              <h2 id="n-cond" className="type-h3">
                {F.conditions}
              </h2>
              <fieldset className="flex min-w-0 flex-col gap-1">
                <legend className="type-sm mb-1 font-medium">
                  {F.formats} *{chip('formats')}
                </legend>
                <div className="flex min-w-0 flex-wrap gap-x-5 gap-y-1">
                  {WORK_FORMATS.map((f) => (
                    <Label key={f} className="tap-target flex items-center gap-2 font-normal">
                      <Checkbox
                        checked={draft.formats.includes(f)}
                        onCheckedChange={(on) =>
                          set('formats', on ? [...draft.formats, f] : draft.formats.filter((x) => x !== f))
                        }
                      />
                      {F.formats_[f]}
                    </Label>
                  ))}
                </div>
                {err('formats')}
              </fieldset>
              <div className="flex min-w-0 flex-col gap-1.5">
                <Label htmlFor="n-city">
                  {F.city}
                  {needsCity ? ' *' : ''}
                  {chip('city')}
                </Label>
                <Input
                  id="n-city"
                  value={draft.city}
                  maxLength={80}
                  aria-invalid={Boolean(errors.city)}
                  onChange={(e) => set('city', e.target.value)}
                />
                {err('city')}
              </div>
              <div className="flex min-w-0 flex-col gap-1.5">
                <SalaryRangeInput
                  required
                  legend={F.salary}
                  value={draft.salary}
                  onChange={(v) => set('salary', v)}
                  limits={limits}
                  serverError={salaryError}
                  showErrors={submitted}
                />
                {chip('salary')}
                {hintValue ? (
                  <p className="type-sm num text-ink-muted">
                    {F.marketHint(formatMoney(hintValue.from), formatMoney(hintValue.to))}
                  </p>
                ) : null}
                <p className="type-sm text-ink-muted">{F.salaryHint}</p>
                {err('salary')}
              </div>
            </section>

            <section className="surface-card flex min-w-0 flex-col gap-3 p-5" aria-labelledby="n-team">
              <h2 id="n-team" className="type-h3">
                {F.team}
              </h2>
              <div className="flex min-w-0 flex-col gap-1.5">
                <Label htmlFor="n-team-f">
                  {F.teamField} *{chip('team')}
                </Label>
                <Textarea
                  id="n-team-f"
                  rows={4}
                  maxLength={1000}
                  value={draft.team}
                  aria-invalid={Boolean(errors.team)}
                  onChange={(e) => set('team', e.target.value)}
                />
                <p className="type-sm text-ink-muted">{F.teamHint}</p>
                {err('team')}
              </div>
            </section>
          </fieldset>

          {draft.spec && draft.grade && mustCodes.length + niceCodes.length > 0 ? (
            <details className="surface-card min-w-0 p-5" open>
              <summary className="tap-target type-h3 cursor-pointer">{F.blueprint}</summary>
              <div className="mt-3">
                <NeedBlueprint specialization={draft.spec} grade={draft.grade} must={mustCodes} nice={niceCodes} />
              </div>
            </details>
          ) : null}

          {!archived ? (
            <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center">
              <Button
                type="submit"
                variant="primary"
                loading={save.isPending && mode !== 'only'}
                disabled={save.isPending && mode === 'only'}
              >
                {need ? F.saveUpdate : F.save}
              </Button>
              {need ? (
                <div className="flex min-w-0 flex-col gap-1">
                  <Button
                    type="button"
                    variant="secondary"
                    loading={save.isPending && mode === 'only'}
                    disabled={save.isPending && mode !== 'only'}
                    onClick={submit('only')}
                  >
                    {F.saveOnly}
                  </Button>
                  <span className="type-caption text-ink-muted">{F.saveOnlyHint}</span>
                </div>
              ) : null}
            </div>
          ) : (
            <EmptyState compact text={F.archivedAlert} />
          )}
        </form>
      </div>
    </div>
  )
}

function ParseNotes({ parsed }: { parsed: NeedDraft }) {
  const warnings = (parsed.warnings ?? []).map((w) => F.warnings[w]).filter(Boolean)
  const alternatives = parsed.grade_alternatives ?? []
  const unknown = parsed.unknown_terms ?? []
  if (warnings.length === 0 && alternatives.length === 0 && unknown.length === 0) return null
  return (
    <Alert variant="warning">
      <AlertDescription className="flex min-w-0 flex-col gap-1">
        {warnings.map((w) => (
          <span key={w}>{w}</span>
        ))}
        {alternatives.length > 0 ? (
          <span>
            {F.gradeAlternatives}: {alternatives.join(', ')}
          </span>
        ) : null}
        {unknown.length > 0 ? (
          <span>
            {F.unknownTerms}: <span className="num break-words">{unknown.join(', ')}</span>. {F.unknownTermsTail}
          </span>
        ) : null}
      </AlertDescription>
    </Alert>
  )
}
