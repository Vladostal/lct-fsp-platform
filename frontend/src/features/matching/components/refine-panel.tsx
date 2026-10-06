import { useState } from 'react'
import type { Catalog, ShortlistQuery, ShortlistRefinement, WorkFormat } from '@/client'
import { type SalaryLimits, SalaryRangeInput, type SalaryRangeValue, TagInput, type TagValue } from '@/components/app'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { MATCHING, WORK_FORMATS } from '../content'

const R = MATCHING.refine
const FORMATS = MATCHING.form.formats_

export function salaryLimits(catalog: Catalog | null | undefined): SalaryLimits {
  const l = catalog?.limits ?? {}
  return {
    salary_min: Number(l.salary_min ?? 10000),
    salary_max: Number(l.salary_max ?? 3000000),
    salary_max_ratio: Number(l.salary_max_ratio ?? 1.5),
  }
}

type Props = {
  query: ShortlistQuery
  catalog: Catalog | null | undefined
  pending: boolean
  rateLimited: string | null
  hiddenByFsp: number
  onApply: (refinement: ShortlistRefinement) => void
  onReset: () => void
}

const same = (a: readonly string[], b: readonly string[]) => a.length === b.length && a.every((x) => b.includes(x))

/** Уточнение запроса: изменённые поля уходят в `refinement`, версия создаётся на сервере. */
export function RefinePanel({ query, catalog, pending, rateLimited, hiddenByFsp, onApply, onReset }: Props) {
  const titleOf = (code: string) => catalog?.skills.find((s) => s.code === code)?.title ?? code
  const toTags = (codes: readonly string[] | undefined): TagValue[] =>
    (codes ?? []).map((c) => ({ code: c, title: titleOf(c) }))
  const [grades, setGrades] = useState<string[]>(query.grade_codes ?? [query.grade_code])
  const [must, setMust] = useState<TagValue[]>(toTags(query.must_skills))
  const [nice, setNice] = useState<TagValue[]>(toTags(query.nice_skills))
  const [formats, setFormats] = useState<WorkFormat[]>(query.work_formats ?? [])
  const [salary, setSalary] = useState<SalaryRangeValue>({
    from: query.salary_from ?? null,
    to: query.salary_to ?? null,
  })
  const [requireFsp, setRequireFsp] = useState(Boolean(query.require_fsp))

  const codes = (t: TagValue[]) => t.map((x) => x.code).filter((x): x is string => Boolean(x))
  const diff: ShortlistRefinement = {}
  if (!same(grades, query.grade_codes ?? [query.grade_code])) diff.grade_codes = grades
  if (!same(codes(must), query.must_skills ?? [])) diff.must_skills = codes(must)
  if (!same(codes(nice), query.nice_skills ?? [])) diff.nice_skills = codes(nice)
  if (!same(formats, query.work_formats ?? [])) diff.work_formats = formats
  if (salary.from !== (query.salary_from ?? null) || salary.to !== (query.salary_to ?? null)) {
    diff.salary_from = salary.from
    diff.salary_to = salary.to
  }
  if (requireFsp !== Boolean(query.require_fsp)) diff.require_fsp = requireFsp
  const changed = Object.keys(diff).length > 0
  const options = (catalog?.skills ?? []).map((s) => ({ code: s.code, title: s.title, aliases: s.aliases }))
  const availableGrades = (catalog?.grades ?? []).filter((g) => g.available)

  const move = (tag: TagValue, from: 'must' | 'nice') => {
    if (from === 'must') {
      setMust(must.filter((t) => t.code !== tag.code))
      setNice([...nice, tag])
    } else {
      setNice(nice.filter((t) => t.code !== tag.code))
      setMust([...must, tag])
    }
  }

  return (
    <form
      className="flex min-w-0 flex-col gap-5"
      onSubmit={(e) => {
        e.preventDefault()
        if (changed) onApply(diff)
      }}
    >
      {rateLimited ? (
        <Alert variant="warning">
          <AlertDescription>{MATCHING.shortlist.rateLimited(rateLimited)}</AlertDescription>
        </Alert>
      ) : null}

      <fieldset className="flex min-w-0 flex-col gap-2">
        <legend className="type-sm mb-1 font-medium">{R.grades}</legend>
        {availableGrades.map((g) => (
          <Label key={g.code} className="tap-target flex min-w-0 items-center gap-2 font-normal">
            <Checkbox
              checked={grades.includes(g.code)}
              onCheckedChange={(on) => setGrades((prev) => (on ? [...prev, g.code] : prev.filter((x) => x !== g.code)))}
            />
            <span className="min-w-0">{g.title}</span>
          </Label>
        ))}
      </fieldset>

      <div className="flex min-w-0 flex-col gap-2">
        <TagInput label={R.must} value={must} onChange={setMust} options={options} max={8} />
        {must.length > 0 ? (
          <ul className="flex min-w-0 flex-wrap gap-1.5">
            {must.map((t) => (
              <li key={t.code ?? t.title}>
                <Button type="button" variant="ghost" size="sm" onClick={() => move(t, 'must')}>
                  {t.title}: {R.toNice}
                </Button>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
      <div className="flex min-w-0 flex-col gap-2">
        <TagInput label={R.nice} value={nice} onChange={setNice} options={options} max={12} />
        {nice.length > 0 ? (
          <ul className="flex min-w-0 flex-wrap gap-1.5">
            {nice.map((t) => (
              <li key={t.code ?? t.title}>
                <Button type="button" variant="ghost" size="sm" onClick={() => move(t, 'nice')}>
                  {t.title}: {R.toMust}
                </Button>
              </li>
            ))}
          </ul>
        ) : null}
      </div>

      <fieldset className="flex min-w-0 flex-col gap-2">
        <legend className="type-sm mb-1 font-medium">{R.formats}</legend>
        {WORK_FORMATS.map((f) => (
          <Label key={f} className="tap-target flex min-w-0 items-center gap-2 font-normal">
            <Checkbox
              checked={formats.includes(f)}
              onCheckedChange={(on) => setFormats((prev) => (on ? [...prev, f] : prev.filter((x) => x !== f)))}
            />
            <span className="min-w-0">{FORMATS[f]}</span>
          </Label>
        ))}
      </fieldset>

      <div className="flex min-w-0 flex-col gap-1">
        <SalaryRangeInput legend={R.salary} value={salary} onChange={setSalary} limits={salaryLimits(catalog)} />
        <p className="type-sm text-ink-muted">{R.salaryNote}</p>
      </div>

      <div className="flex min-w-0 flex-col gap-1">
        <Label className="tap-target flex min-w-0 items-center justify-between gap-3 font-normal">
          <span className="min-w-0">{R.requireFsp}</span>
          <Switch checked={requireFsp} onCheckedChange={setRequireFsp} />
        </Label>
        {requireFsp && hiddenByFsp > 0 ? <p className="type-sm text-ink-muted">{R.hiddenByFsp(hiddenByFsp)}</p> : null}
      </div>

      <div className="flex min-w-0 flex-col gap-2">
        <Button type="submit" variant="primary" loading={pending} disabled={!changed}>
          {R.apply}
        </Button>
        <Button type="button" variant="ghost" onClick={onReset} disabled={pending}>
          {R.reset}
        </Button>
        <p className="type-sm text-ink-muted">{R.note}</p>
      </div>
    </form>
  )
}
