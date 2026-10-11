import { useState } from 'react'
import type { BlueprintPreview } from '@/client'
import { CategoryChip } from '@/components/app'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { CoverageTable } from '@/features/matching'
import { errorMessage } from '@/lib/api'
import { HOW } from '../content'
import { useTextPreview } from '../hooks'

const T = HOW.testing
const CUSTOM = 'custom'

function Slots({ data }: { data: BlueprintPreview }) {
  const need = new Map((data.need_slots ?? []).map((s) => [s.group.code, s]))
  const rows = (data.standard_slots ?? []).map((s) => {
    const n = need.get(s.group.code)
    return { group: s.group.title, standard: s.slots, own: n?.slots ?? s.slots, delta: n?.delta ?? 0 }
  })
  if (rows.length === 0) return null
  return (
    <div className="min-w-0 overflow-x-auto">
      <table className="type-sm w-full min-w-[420px] border-collapse text-left">
        <caption className="type-sm mb-2 text-left font-medium">{T.slots}</caption>
        <thead>
          <tr className="text-ink-muted">
            <th scope="col" className="py-2 pr-3 font-medium">
              {T.group}
            </th>
            <th scope="col" className="py-2 pr-3 font-medium">
              {T.standard}
            </th>
            <th scope="col" className="py-2 font-medium">
              {T.forNeed}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.group}>
              <td className="min-w-0 break-words py-2 pr-3">{r.group}</td>
              <td className="num py-2 pr-3">{r.standard}</td>
              <td className="num py-2">
                {r.own}
                {r.delta !== 0 ? (
                  <span className="ml-2 text-ink-muted">({r.delta > 0 ? `+${r.delta}` : `−${Math.abs(r.delta)}`})</span>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Интерактивный блок «Из вакансии — в тест»: пример или свой текст → `POST /assessment/blueprints/preview`. */
export function BlueprintDemo({ min, max }: { min: number; max: number }) {
  const [choice, setChoice] = useState<string>(HOW.examples[1].id)
  const [custom, setCustom] = useState('')
  const [localError, setLocalError] = useState<string | null>(null)
  const preview = useTextPreview()
  const example = HOW.examples.find((e) => e.id === choice)
  const text = choice === CUSTOM ? custom.trim() : example ? `${example.title}. ${example.text}` : ''

  const run = () => {
    if (text.length < min) return setLocalError(T.tooShort(min))
    if (text.length > max) return setLocalError(T.tooLong(max))
    setLocalError(null)
    preview.mutate(text)
  }

  return (
    <div className="surface-card flex min-w-0 flex-col gap-4 p-5 md:p-6">
      <h3 className="type-h3">{T.demoTitle}</h3>
      <p className="type-body text-ink-muted">{T.demoLead}</p>
      <ToggleGroup type="single" value={choice} aria-label={T.examplesLabel} onValueChange={(v) => v && setChoice(v)}>
        {HOW.examples.map((e) => (
          <ToggleGroupItem key={e.id} value={e.id}>
            {e.title}
          </ToggleGroupItem>
        ))}
        <ToggleGroupItem value={CUSTOM}>{T.custom}</ToggleGroupItem>
      </ToggleGroup>
      {choice === CUSTOM ? (
        <div className="flex min-w-0 flex-col gap-1.5">
          <Label htmlFor="hw-custom">{T.customLabel}</Label>
          <Textarea
            id="hw-custom"
            rows={6}
            value={custom}
            onChange={(e) => setCustom(e.target.value)}
            maxLength={max}
          />
        </div>
      ) : (
        <blockquote className="type-sm min-w-0 break-words text-ink-muted">{example?.text}</blockquote>
      )}
      {localError ? (
        <p role="alert" className="type-sm text-danger">
          {localError}
        </p>
      ) : null}
      <Button type="button" variant="secondary" className="self-start" loading={preview.isPending} onClick={run}>
        {T.run}
      </Button>
      {preview.isError ? (
        <Alert variant="warning">
          <AlertDescription>
            {T.unavailable} {errorMessage(preview.error)}
          </AlertDescription>
        </Alert>
      ) : null}
      {preview.data ? (
        <div className="flex min-w-0 flex-col gap-5" aria-live="polite">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="type-sm font-medium">{T.target}:</span>
            <CategoryChip title={preview.data.target.title} />
          </div>
          <div className="flex min-w-0 flex-col gap-2">
            <h4 className="type-sm font-medium">{T.coverage}</h4>
            <CoverageTable data={preview.data} />
          </div>
          <Slots data={preview.data} />
          <p className="type-caption text-ink-muted">{T.slotsNote}</p>
        </div>
      ) : null}
    </div>
  )
}
