import { Lock } from 'lucide-react'
import { useId } from 'react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { formatMoney, formatSalaryRange } from '@/lib/format'
import { useSalaryHint } from '../api'
import { PROFILE } from '../content'

const NONE = 'none'
const GRID: number[] = Array.from({ length: 29 }, (_, i) => 40_000 + i * 20_000)

export type MinSalarySelectProps = {
  value: number | null
  onChange: (value: number | null) => void
  /** Категория для ориентира рынка; без неё ориентир считается по всем категориям. */
  category?: string | null
  /** Подпись «Действует только на будущие приглашения» (в кабинете). */
  showFutureNote?: boolean
  disabled?: boolean
}

/**
 * Минимум зарплаты («Не видит никто»): «Не задан», 40 000 … 600 000 ₽ с шагом 20 000. Рядом — ориентир
 * из `GET /contact/salary-hint`: сведения о предложениях работодателей, а не о чужих минимумах.
 */
export function MinSalarySelect({ value, onChange, category, showFutureNote = false, disabled }: MinSalarySelectProps) {
  const S = PROFILE.salary
  const id = useId()
  const hint = useSalaryHint(category)
  const options = value != null && !GRID.includes(value) ? [...GRID, value].sort((a, b) => a - b) : GRID

  return (
    <div className="flex min-w-0 flex-col gap-2">
      <label htmlFor={id} className="type-sm flex items-center gap-1.5 font-medium text-ink">
        <Lock className="size-3.5 text-ink-muted" aria-hidden="true" />
        {S.label}
      </label>
      <Select
        value={value == null ? NONE : String(value)}
        onValueChange={(next) => onChange(next === NONE ? null : Number(next))}
        disabled={disabled}
      >
        <SelectTrigger id={id} className="max-w-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={NONE}>{S.none}</SelectItem>
          {options.map((option) => (
            <SelectItem key={option} value={String(option)}>
              <span className="num">{formatMoney(option)}</span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <p className="type-caption text-ink-muted">{S.note}</p>
      {showFutureNote ? <p className="type-caption text-ink-muted">{S.futureOnly}</p> : null}
      {hint.data ? (
        <p className="type-caption text-ink-muted" data-testid="salary-hint">
          <span className="num font-medium text-ink">{S.hint(formatSalaryRange(hint.data.from, hint.data.to))}</span>
          <span className="block">{S.hintSource}</span>
        </p>
      ) : null}
    </div>
  )
}
