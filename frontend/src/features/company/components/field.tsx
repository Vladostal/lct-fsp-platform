import { useId } from 'react'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'

type FieldProps = {
  label: string
  required?: boolean
  hint?: React.ReactNode
  error?: string | null
  counter?: string
  className?: string
  children: (props: { id: string; 'aria-invalid': boolean; 'aria-describedby': string | undefined }) => React.ReactNode
}

/** Поле формы: подпись, подсказка, ошибка под полем (с `role="alert"` по требованию доступности). */
export function Field({ label, required, hint, error, counter, className, children }: FieldProps) {
  const id = useId()
  const describedBy = [hint ? `${id}-hint` : null, error ? `${id}-error` : null].filter(Boolean).join(' ') || undefined
  return (
    <div className={cn('flex min-w-0 flex-col gap-1.5', className)}>
      <div className="flex min-w-0 items-baseline justify-between gap-3">
        <Label htmlFor={id} className="min-w-0">
          {label}
          {required ? <span aria-hidden="true"> *</span> : null}
        </Label>
        {counter ? <span className="num shrink-0 text-ink-muted type-caption">{counter}</span> : null}
      </div>
      {children({ id, 'aria-invalid': Boolean(error), 'aria-describedby': describedBy })}
      {hint ? (
        <p id={`${id}-hint`} className="type-sm text-ink-muted">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={`${id}-error`} role="alert" className="type-sm text-danger">
          {error}
        </p>
      ) : null}
    </div>
  )
}
