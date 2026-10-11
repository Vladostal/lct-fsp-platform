import type { LucideIcon } from 'lucide-react'
import type * as React from 'react'
import { cn } from '@/lib/utils'
import { IconTile } from './icon-tile'
import type { TileTone } from './tone'

export type StatProps = {
  label: string
  value: React.ReactNode
  hint?: React.ReactNode
  /** Плитка со значком слева — тот же вид, что у `StatTile`. */
  icon?: LucideIcon
  tone?: TileTone
  className?: string
}

/** Показатель: крупное число, подпись в одно-два слова и необязательная подсказка; со значком — как `StatTile`. */
export function Stat({ label, value, hint, icon, tone = 'brand', className }: StatProps) {
  return (
    <div data-slot="stat" className={cn('flex min-w-0 items-center gap-3', className)}>
      {icon ? <IconTile icon={icon} tone={tone} /> : null}
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="num text-2xl leading-7 font-semibold text-ink">{value}</span>
        <span className="type-caption text-ink-muted">{label}</span>
        {hint ? <span className="type-caption text-ink-muted">{hint}</span> : null}
      </div>
    </div>
  )
}
