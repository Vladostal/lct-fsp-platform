import type * as React from 'react'
import { cn } from '@/lib/utils'

export type StatProps = {
  label: string
  value: React.ReactNode
  hint?: React.ReactNode
  className?: string
}

/** Показатель: число mono крупно, подпись и необязательная подсказка. */
export function Stat({ label, value, hint, className }: StatProps) {
  return (
    <div data-slot="stat" className={cn('flex min-w-0 flex-col gap-0.5', className)}>
      <span className="num text-xl leading-7 font-medium text-ink">{value}</span>
      <span className="type-caption text-ink-muted">{label}</span>
      {hint ? <span className="type-caption text-ink-muted">{hint}</span> : null}
    </div>
  )
}
