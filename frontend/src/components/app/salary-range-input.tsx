import { CircleAlert } from 'lucide-react'
import { useEffect, useId, useState } from 'react'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { SALARY } from '@/content/common'
import { errorText } from '@/lib/api'
import { formatNumber } from '@/lib/format'
import { cn } from '@/lib/utils'

/** Константы вилки из `catalog.limits` (Арх. 4.6): границы и допустимая ширина. */
export type SalaryLimits = {
  salary_min: number
  salary_max: number
  /** Во сколько раз «до» может превышать «от» (по умолчанию 1,5). */
  salary_max_ratio: number
}

export type SalaryRangeValue = { from: number | null; to: number | null }
export type SalaryRangeIssue = {
  code: 'salary_out_of_bounds' | 'salary_order' | 'salary_range_too_wide'
  params: Record<string, number>
}

/** Наибольшее допустимое «до» при данном «от». */
export function maxSalaryTo(from: number, limits: SalaryLimits): number {
  return Math.min(limits.salary_max, Math.floor(from * limits.salary_max_ratio))
}

/**
 * Проверки вилки в порядке сервера (E §3.3): границы → порядок → ширина. Возвращает код и параметры для
 * `errorText` либо null. Пустые поля ошибкой не считаются — обязательность проверяет форма.
 */
export function validateSalaryRange(value: SalaryRangeValue, limits: SalaryLimits): SalaryRangeIssue | null {
  const { from, to } = value
  const bounds = { salary_min: limits.salary_min, salary_max: limits.salary_max }
  if (from !== null && (from < limits.salary_min || from > limits.salary_max)) {
    return { code: 'salary_out_of_bounds', params: bounds }
  }
  if (to !== null && (to < limits.salary_min || to > limits.salary_max)) {
    return { code: 'salary_out_of_bounds', params: bounds }
  }
  if (from === null || to === null) return null
  if (from > to) return { code: 'salary_order', params: {} }
  const maxTo = Math.floor(from * limits.salary_max_ratio)
  if (to > maxTo) return { code: 'salary_range_too_wide', params: { max_to: maxTo } }
  return null
}

function parseAmount(text: string): number | null {
  const digits = text.replace(/\D/g, '')
  if (digits === '') return null
  const value = Number.parseInt(digits.slice(0, 9), 10)
  return Number.isFinite(value) ? value : null
}

export type SalaryRangeInputProps = {
  value: SalaryRangeValue
  onChange: (value: SalaryRangeValue) => void
  limits: SalaryLimits
  /** Ошибка сервера для вилки (код из `ApiError`); показывается вместо собственной проверки. */
  serverError?: string | null
  /** Общая подпись группы; по умолчанию «Зарплата, ₽ в месяц». */
  legend?: string
  required?: boolean
  disabled?: boolean
  /** Показывать ошибку сразу, не дожидаясь потери фокуса (после попытки отправить форму). */
  showErrors?: boolean
  className?: string
}

/**
 * Два поля «от» и «до»: только цифры, разряды группируются при потере фокуса, суффикс ₽.
 * Под полями — постоянная подсказка о допустимом «до»; ошибка — иконка и текст по коду.
 * Каждое поле не уже 132 px: вмещает «3 000 000 ₽», два поля рядом помещаются в 320 px.
 */
export function SalaryRangeInput({
  value,
  onChange,
  limits,
  serverError = null,
  legend = SALARY.fieldLabel,
  required = false,
  disabled = false,
  showErrors = false,
  className,
}: SalaryRangeInputProps) {
  const id = useId()
  const [fromText, setFromText] = useState(() => (value.from === null ? '' : formatNumber(value.from)))
  const [toText, setToText] = useState(() => (value.to === null ? '' : formatNumber(value.to)))
  const [focused, setFocused] = useState<'from' | 'to' | null>(null)
  const [touched, setTouched] = useState(false)

  // Значение изменили снаружи (подстановка из разбора текста, сброс формы) — обновить текст в поле без фокуса.
  useEffect(() => {
    if (focused !== 'from') setFromText(value.from === null ? '' : formatNumber(value.from))
  }, [value.from, focused])
  useEffect(() => {
    if (focused !== 'to') setToText(value.to === null ? '' : formatNumber(value.to))
  }, [value.to, focused])

  const issue = validateSalaryRange(value, limits)
  const errorVisible = serverError ?? (issue && (touched || showErrors) ? errorText(issue.code, issue.params) : null)
  const hint =
    value.from !== null && value.from >= limits.salary_min
      ? `«До» — не больше ${formatNumber(maxSalaryTo(value.from, limits))} ₽`
      : `«До» — не больше чем в ${String(limits.salary_max_ratio).replace('.', ',')} раза выше «от»`

  const hintId = `${id}-hint`
  const errorId = `${id}-error`
  const describedBy = errorVisible ? `${hintId} ${errorId}` : hintId

  const field = (which: 'from' | 'to') => {
    const text = which === 'from' ? fromText : toText
    const setText = which === 'from' ? setFromText : setToText
    const invalid = Boolean(errorVisible)
    return (
      <div className="flex min-w-[132px] flex-1 flex-col gap-2">
        <Label htmlFor={`${id}-${which}`}>
          <span>
            {which === 'from' ? SALARY.from : SALARY.to}
            {required ? (
              <span className="text-danger" aria-hidden="true">
                {' '}
                *
              </span>
            ) : null}
          </span>
        </Label>
        <div className="relative">
          <Input
            id={`${id}-${which}`}
            inputMode="numeric"
            autoComplete="off"
            disabled={disabled}
            aria-required={required || undefined}
            aria-invalid={invalid || undefined}
            aria-describedby={describedBy}
            className="num pr-9"
            value={text}
            onFocus={() => setFocused(which)}
            onChange={(event) => {
              const raw = event.target.value.replace(/[^\d\s ]/g, '')
              setText(raw)
              const amount = parseAmount(raw)
              onChange(which === 'from' ? { ...value, from: amount } : { ...value, to: amount })
            }}
            onBlur={() => {
              setFocused(null)
              setTouched(true)
              const amount = parseAmount(text)
              setText(amount === null ? '' : formatNumber(amount))
            }}
          />
          {/* Суффикс лежит поверх поля намеренно: data-overlay исключает его из проверки наложений. */}
          <span
            data-overlay
            className="num pointer-events-none absolute inset-y-0 right-3.5 flex items-center text-base text-ink-muted"
            aria-hidden="true"
          >
            ₽
          </span>
        </div>
      </div>
    )
  }

  return (
    <fieldset
      data-slot="salary-range-input"
      disabled={disabled}
      className={cn('flex min-w-0 flex-col gap-2', className)}
    >
      <legend className="mb-2 text-sm leading-5 font-medium text-ink">{legend}</legend>
      <div className="flex min-w-0 flex-wrap gap-2 sm:gap-3">
        {field('from')}
        {field('to')}
      </div>
      <p id={hintId} className="type-sm text-ink-muted">
        {hint}
      </p>
      {errorVisible ? (
        <p id={errorId} role="alert" className="type-sm flex min-w-0 items-start gap-1.5 text-danger">
          <CircleAlert className="mt-0.5 size-4" aria-hidden="true" />
          <span className="min-w-0">{errorVisible}</span>
        </p>
      ) : null}
    </fieldset>
  )
}
