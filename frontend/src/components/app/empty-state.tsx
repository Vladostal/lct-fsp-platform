import type { LucideIcon } from 'lucide-react'
import { Inbox } from 'lucide-react'
import type * as React from 'react'
import { cn } from '@/lib/utils'
import { IconTile } from './icon-tile'

export type EmptyStateProps = {
  /** Значок в мягкой плитке бренда; по умолчанию — «входящие». */
  icon?: LucideIcon
  title?: string
  /** Одно-два предложения; переносится, никогда не усекается. */
  text?: React.ReactNode
  /** Не больше одного действия (E §2.0). */
  action?: React.ReactNode
  /** Уровень заголовка, чтобы уровни шли без пропусков. */
  headingLevel?: 2 | 3 | 4
  /** Компактный вид — внутри карточки или вкладки. */
  compact?: boolean
  className?: string
}

/** Пустое состояние: плитка со значком, заголовок, пояснение и не больше одного действия — отвечает на «что дальше». */
export function EmptyState({
  icon: Icon = Inbox,
  title,
  text,
  action,
  headingLevel = 2,
  compact = false,
  className,
}: EmptyStateProps) {
  const Heading = `h${headingLevel}` as 'h2' | 'h3' | 'h4'
  return (
    <div
      data-slot="empty-state"
      className={cn(
        'flex min-w-0 flex-col items-center gap-3 text-center',
        compact ? 'px-4 py-6' : 'px-4 py-8 md:py-12',
        className,
      )}
    >
      <IconTile icon={Icon} tone="soft" size={compact ? 'md' : 'xl'} />
      <div className="flex max-w-[52ch] min-w-0 flex-col gap-2">
        {title ? <Heading className="type-h3 text-ink">{title}</Heading> : null}
        {text ? <p className="type-body text-ink-muted">{text}</p> : null}
      </div>
      {action ? (
        <div className="flex min-w-0 flex-col items-center max-[479px]:w-full max-[479px]:items-stretch">{action}</div>
      ) : null}
    </div>
  )
}
