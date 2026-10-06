import { Trophy } from 'lucide-react'
import type { FspAchievementView } from '@/client'
import { ExternalLink } from '@/components/app'
import { Badge } from '@/components/ui/badge'
import { formatDate } from '@/lib/format'
import { cn } from '@/lib/utils'
import { FSP } from '../content'

export type FspAchievementListProps = {
  achievements: readonly FspAchievementView[]
  /** `self` — кандидату: все записи, незачтённые с причиной; `employer` — только зачтённые. */
  mode?: 'self' | 'employer'
  className?: string
}

function Achievement({ item, mode }: { item: FspAchievementView; mode: 'self' | 'employer' }) {
  const A = FSP.achievement
  const meta = [item.discipline_label, item.level_label, item.stage_label, item.format_label]
    .filter(Boolean)
    .join(' · ')
  const team = [item.team_name, item.team_size ? A.teamOf(item.team_size) : null].filter(Boolean).join(', ')
  return (
    <li
      className={cn(
        'flex min-w-0 flex-col gap-1.5 border-l-[3px] bg-surface py-3 pr-3 pl-4',
        item.counted ? 'border-l-fsp-red' : 'border-l-line-strong',
      )}
    >
      <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
        <Trophy
          className={cn('size-4 shrink-0', item.counted ? 'text-fsp-red' : 'text-ink-muted')}
          aria-hidden="true"
        />
        <span className="type-body min-w-0 font-medium text-ink [overflow-wrap:anywhere]">
          {item.competition_title}
        </span>
        <Badge variant={item.counted ? 'info' : 'neutral'} size="sm">
          {item.place_label}
        </Badge>
      </div>
      <p className="type-sm min-w-0 text-ink-muted [overflow-wrap:anywhere]">{meta}</p>
      <p className="type-sm min-w-0 text-ink-muted [overflow-wrap:anywhere]">
        {[item.role_label, team, item.city, item.date_end ? formatDate(item.date_end) : null, item.score_label]
          .filter(Boolean)
          .join(' · ')}
      </p>
      {item.norm ? <p className="type-sm min-w-0 text-ink [overflow-wrap:anywhere]">{item.norm.rank_label}</p> : null}
      {mode === 'self' ? (
        <p className="type-caption min-w-0 text-ink-muted">
          {item.counted
            ? item.recency_percent != null
              ? A.counted(item.recency_percent)
              : null
            : (item.uncounted_label ?? A.uncounted)}
        </p>
      ) : null}
      {item.protocol_url ? (
        <ExternalLink href={item.protocol_url} className="type-sm self-start">
          {A.protocol}
        </ExternalLink>
      ) : null}
    </li>
  )
}

/** Список достижений ФСП. Для кандидата (`self`) показаны все записи, незачтённые — с причиной. */
export function FspAchievementList({ achievements, mode = 'self', className }: FspAchievementListProps) {
  const items = mode === 'employer' ? achievements.filter((item) => item.counted) : achievements
  if (items.length === 0) return null
  return (
    <ul className={cn('flex min-w-0 flex-col divide-y divide-line rounded-md border border-line', className)}>
      {items.map((item) => (
        <Achievement key={item.id} item={item} mode={mode} />
      ))}
    </ul>
  )
}
