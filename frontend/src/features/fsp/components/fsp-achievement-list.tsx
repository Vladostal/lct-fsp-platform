import { Award, CalendarDays, CircleSlash, MapPin, Medal, Trophy, Users } from 'lucide-react'
import type * as React from 'react'
import type { FspAchievementView } from '@/client'
import { CHART, ExternalLink, IconTile, SoftPill } from '@/components/app'
import { formatDate } from '@/lib/format'
import { cn } from '@/lib/utils'
import { FSP } from '../content'

export type FspAchievementListProps = {
  achievements: readonly FspAchievementView[]
  /** `self` — кандидату: все записи, незачтённые с причиной; `employer` — только зачтённые. */
  mode?: 'self' | 'employer'
  className?: string
}

/** Пилюля с произвольным текстом: длинное значение переносится внутри, а не вылезает из карточки. */
const WRAP_PILL = 'h-auto min-h-6 shrink rounded-xl py-0.5 [overflow-wrap:anywhere] [&>svg]:size-3.5 [&>svg]:shrink-0'

function Achievement({ item, mode, index }: { item: FspAchievementView; mode: 'self' | 'employer'; index: number }) {
  const A = FSP.achievement
  const team = [item.team_name, item.team_size ? A.teamOf(item.team_size) : null].filter(Boolean).join(', ')
  const facts = [item.discipline_label, item.role_label, item.score_label].filter(Boolean).join(' · ')
  return (
    <li
      className={cn(
        'surface-row stagger flex min-w-0 animate-rise-in flex-col gap-3 p-4',
        item.counted ? 'accent-card' : 'border-dashed',
      )}
      style={{ '--i': Math.min(index, 8) } as React.CSSProperties}
    >
      <div className="flex min-w-0 items-start gap-3">
        <IconTile icon={item.counted ? Trophy : Medal} tone={item.counted ? 'accent' : 'dashed'} size="lg" />
        <div className="flex min-w-0 flex-1 flex-col items-start gap-1.5">
          <h3 className="type-h3 min-w-0 text-ink [overflow-wrap:anywhere]">{item.competition_title}</h3>
          <SoftPill
            tone={item.counted ? 'solid' : 'neutral'}
            size="sm"
            icon={Medal}
            className={cn(WRAP_PILL, 'font-medium')}
          >
            <span className="num whitespace-normal">{item.place_label}</span>
          </SoftPill>
        </div>
      </div>
      <ul className="flex min-w-0 flex-wrap gap-1.5">
        {[item.level_label, item.stage_label, item.format_label].filter(Boolean).map((label) => (
          <li key={label} className="max-w-full min-w-0">
            <SoftPill size="sm" tone={item.counted ? 'brand' : 'neutral'} className={WRAP_PILL}>
              {label}
            </SoftPill>
          </li>
        ))}
        {item.date_end ? (
          <li className="max-w-full min-w-0">
            <SoftPill size="sm" icon={CalendarDays} className={WRAP_PILL}>
              <span className="num">{formatDate(item.date_end)}</span>
            </SoftPill>
          </li>
        ) : null}
        {item.city ? (
          <li className="max-w-full min-w-0">
            <SoftPill size="sm" icon={MapPin} className={WRAP_PILL}>
              {item.city}
            </SoftPill>
          </li>
        ) : null}
        {team ? (
          <li className="max-w-full min-w-0">
            <SoftPill size="sm" icon={Users} className={WRAP_PILL}>
              {team}
            </SoftPill>
          </li>
        ) : null}
      </ul>
      {facts ? <p className="type-sm min-w-0 text-ink-muted [overflow-wrap:anywhere]">{facts}</p> : null}
      {item.norm ? (
        <SoftPill tone="success" size="sm" icon={Award} className={cn(WRAP_PILL, 'self-start')}>
          {item.norm.rank_label}
        </SoftPill>
      ) : null}
      {mode === 'self' || item.protocol_url ? (
        <div className="mt-auto flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
          {mode === 'self' ? (
            item.counted ? (
              item.recency_percent != null ? (
                <p className="flex min-w-0 flex-1 basis-40 flex-col gap-1">
                  <span className="type-caption text-ink-muted">{A.counted(item.recency_percent)}</span>
                  <span aria-hidden="true" className="block h-1.5 overflow-hidden rounded-full bg-fill">
                    <span
                      className="stagger block h-full origin-left animate-grow-x rounded-full"
                      style={
                        {
                          width: `${Math.max(0, Math.min(100, item.recency_percent))}%`,
                          backgroundColor: CHART.brand,
                          '--i': index * 2,
                        } as React.CSSProperties
                      }
                    />
                  </span>
                </p>
              ) : null
            ) : (
              <p className="type-caption flex min-w-0 flex-1 basis-40 items-start gap-1.5 text-ink-muted">
                <CircleSlash className="mt-px size-3.5 shrink-0" aria-hidden="true" />
                <span className="min-w-0">{item.uncounted_label ?? A.uncounted}</span>
              </p>
            )
          ) : null}
          {item.protocol_url ? (
            <ExternalLink href={item.protocol_url} className="type-sm ml-auto min-h-11 shrink-0">
              {A.protocol}
            </ExternalLink>
          ) : null}
        </div>
      ) : null}
    </li>
  )
}

/** Карточки достижений ФСП. Для кандидата (`self`) показаны все записи, незачтённые — пунктиром и с причиной. */
export function FspAchievementList({ achievements, mode = 'self', className }: FspAchievementListProps) {
  const items = mode === 'employer' ? achievements.filter((item) => item.counted) : achievements
  if (items.length === 0) return null
  return (
    <ul className={cn('grid min-w-0 gap-3 md:grid-cols-2', className)}>
      {items.map((item, index) => (
        <Achievement key={item.id} item={item} mode={mode} index={index} />
      ))}
    </ul>
  )
}
