import type * as React from 'react'
import { cn } from '@/lib/utils'

/** Поле ввода: высота 44, радиус 12, граница 1 px line-strong (контраст 3,45 на surface), отступ 12 × 14 (E §3.1). */
const fieldClassName =
  'w-full min-w-0 rounded-md border border-line-strong bg-surface px-3.5 text-base text-ink transition-colors duration-(--dur-fast) placeholder:text-ink-muted hover:border-ink-muted disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:border-line-strong read-only:bg-fill read-only:hover:border-line-strong aria-invalid:border-danger aria-invalid:hover:border-danger'

function Input({ className, type, ...props }: React.ComponentProps<'input'>) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        fieldClassName,
        'h-11 file:mr-3 file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-ink',
        className,
      )}
      {...props}
    />
  )
}

export { fieldClassName, Input }
