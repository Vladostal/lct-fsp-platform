import { CircleAlert, ExternalLink } from 'lucide-react'
import type * as React from 'react'
import { useId } from 'react'
import { Checkbox } from '@/components/ui/checkbox'
import { COMMON } from '@/content/common'
import { cn } from '@/lib/utils'

export type ConsentCheckboxProps = {
  checked: boolean
  onCheckedChange: (checked: boolean) => void
  /** Текст согласия от первого лица: «Согласен(на) на обработку персональных данных». */
  children: React.ReactNode
  /** Ссылка на полный текст согласия; открывается в новой вкладке. */
  href?: string
  linkLabel?: string
  /** Версия текста согласия — mono caption. */
  version?: string | null
  /** Пояснение под подписью. */
  hint?: React.ReactNode
  error?: string | null
  required?: boolean
  disabled?: boolean
  id?: string
  name?: string
  className?: string
}

/**
 * Чекбокс согласия со ссылкой на текст (E §3.3). Флажок не предвыбран: согласие даётся отдельным действием.
 * Ссылка стоит вне <label>, чтобы нажатие на неё не переключало флажок.
 */
export function ConsentCheckbox({
  checked,
  onCheckedChange,
  children,
  href,
  linkLabel = 'Текст согласия',
  version,
  hint,
  error,
  required = false,
  disabled = false,
  id,
  name,
  className,
}: ConsentCheckboxProps) {
  const autoId = useId()
  const fieldId = id ?? autoId
  const hintId = `${fieldId}-hint`
  const errorId = `${fieldId}-error`
  const describedBy = [hint || href ? hintId : null, error ? errorId : null].filter(Boolean).join(' ') || undefined

  return (
    <div data-slot="consent-checkbox" className={cn('flex min-w-0 flex-col gap-1.5', className)}>
      <div className="flex min-w-0 items-start gap-3">
        <Checkbox
          id={fieldId}
          name={name}
          checked={checked}
          disabled={disabled}
          aria-required={required || undefined}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          onCheckedChange={(state) => onCheckedChange(state === true)}
          className="mt-0.5"
        />
        <div className="flex min-w-0 flex-col gap-1">
          <label htmlFor={fieldId} className={cn('min-w-0 text-base leading-6 text-ink', disabled && 'opacity-50')}>
            {children}
            {required ? (
              <span className="text-danger" aria-hidden="true">
                {' '}
                *
              </span>
            ) : null}
          </label>
          {hint || href ? (
            <p id={hintId} className="type-sm flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-ink-muted">
              {hint ? <span className="min-w-0">{hint}</span> : null}
              {href ? (
                <a
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-link tap-target inline-flex min-h-6 items-center gap-1"
                >
                  {linkLabel}
                  <ExternalLink className="size-3.5" aria-hidden="true" />
                  <span className="sr-only">({COMMON.newTab})</span>
                </a>
              ) : null}
              {version ? <span className="type-caption num text-ink-muted">версия {version}</span> : null}
            </p>
          ) : null}
        </div>
      </div>
      {error ? (
        <p id={errorId} className="type-sm flex min-w-0 items-start gap-1.5 pl-8 text-danger">
          <CircleAlert className="mt-0.5 size-4" aria-hidden="true" />
          <span className="min-w-0">{error}</span>
        </p>
      ) : null}
    </div>
  )
}
