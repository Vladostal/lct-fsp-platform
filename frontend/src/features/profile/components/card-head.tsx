import type { LucideIcon } from 'lucide-react'
import type * as React from 'react'
import { IconTile, type TileTone } from '@/components/app'
import { cn } from '@/lib/utils'

export type CardHeadProps = {
  icon: LucideIcon
  tone?: TileTone
  title: React.ReactNode
  /** Уровень заголовка, чтобы уровни шли без пропусков. */
  as?: 'h2' | 'h3'
  id?: string
  /** Справа от заголовка: пилюля-пометка или действие. */
  aside?: React.ReactNode
  className?: string
}

/** Шапка белой карточки-раздела: плитка со значком, короткий заголовок и необязательная пометка справа. */
export function CardHead({ icon, tone = 'brand', title, as: Heading = 'h2', id, aside, className }: CardHeadProps) {
  return (
    <div className={cn('flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2', className)}>
      <IconTile icon={icon} tone={tone} />
      <Heading id={id} className="type-h2 min-w-0 flex-1 [overflow-wrap:anywhere]">
        {title}
      </Heading>
      {aside ? <div className="flex min-w-0 max-w-full shrink-0 flex-wrap items-center gap-2">{aside}</div> : null}
    </div>
  )
}
