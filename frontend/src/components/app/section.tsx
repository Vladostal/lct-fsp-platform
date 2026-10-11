import type { LucideIcon } from 'lucide-react'
import type * as React from 'react'
import { cn } from '@/lib/utils'
import { ICON_TONE, type Tone } from './tone'

export type SectionProps = {
  title: React.ReactNode
  /** Значок перед заголовком (14 px) — подсказывает тему раздела цветом тона. */
  icon?: LucideIcon
  iconTone?: Tone
  /** Число рядом с заголовком (размер списка). */
  count?: number
  action?: React.ReactNode
  children: React.ReactNode
  /** Уровень заголовка, чтобы уровни шли без пропусков. */
  as?: 'h2' | 'h3' | 'h4'
  className?: string
}

/** Раздел страницы: заголовок-eyebrow без линии, между разделами 32 px. */
export function Section({
  title,
  icon: Icon,
  iconTone = 'neutral',
  count,
  action,
  children,
  as: Heading = 'h2',
  className,
}: SectionProps) {
  return (
    <section data-slot="section" className={cn('flex min-w-0 flex-col gap-3', className)}>
      <div className="flex min-w-0 items-center justify-between gap-3">
        <Heading className="type-eyebrow flex min-w-0 items-center gap-1.5">
          {Icon ? <Icon aria-hidden="true" className={cn('size-3.5', ICON_TONE[iconTone])} /> : null}
          <span className="min-w-0">
            {title}
            {count !== undefined ? <span className="num ml-2 text-ink-subtle">{count}</span> : null}
          </span>
        </Heading>
        {action ? <div className="flex shrink-0 items-center gap-2">{action}</div> : null}
      </div>
      <div className="min-w-0">{children}</div>
    </section>
  )
}
