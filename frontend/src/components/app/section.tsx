import type * as React from 'react'
import { cn } from '@/lib/utils'

export type SectionProps = {
  title: React.ReactNode
  /** Число рядом с заголовком (размер списка). */
  count?: number
  action?: React.ReactNode
  children: React.ReactNode
  /** Уровень заголовка, чтобы уровни шли без пропусков. */
  as?: 'h2' | 'h3'
  className?: string
}

/** Раздел страницы: заголовок-eyebrow без линии, между разделами 32 px. */
export function Section({ title, count, action, children, as: Heading = 'h2', className }: SectionProps) {
  return (
    <section data-slot="section" className={cn('flex min-w-0 flex-col gap-3', className)}>
      <div className="flex min-w-0 items-center justify-between gap-3">
        <Heading className="type-eyebrow min-w-0">
          {title}
          {count !== undefined ? <span className="num ml-2 text-ink-subtle">{count}</span> : null}
        </Heading>
        {action ? <div className="flex shrink-0 items-center gap-2">{action}</div> : null}
      </div>
      <div className="min-w-0">{children}</div>
    </section>
  )
}
