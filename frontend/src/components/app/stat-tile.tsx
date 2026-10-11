import type { LucideIcon } from 'lucide-react'
import type * as React from 'react'
import { createContext, useContext } from 'react'
import { cn } from '@/lib/utils'
import { IconTile } from './icon-tile'
import type { TileTone } from './tone'

const StripContext = createContext(false)

export type StatTileProps = {
  icon: LucideIcon
  /** Число или короткое значение («20 ч»); рисуется классом `num`. */
  value: React.ReactNode
  /** Подпись в одно-два слова. */
  label: string
  tone?: TileTone
  /** Вне полосы: `md` — плитка 40 и число 24 px, `lg` — плитка 48 и число 30 px (одна главная цифра блока). */
  size?: 'md' | 'lg'
  className?: string
}

/**
 * Показатель: плитка со значком, крупное число и подпись в одно слово. Внутри `SummaryStrip` — пункт
 * списка (на узком экране значок над числом), отдельно — строка «плитка + число».
 */
export function StatTile({ icon, value, label, tone = 'brand', size = 'md', className }: StatTileProps) {
  const inStrip = useContext(StripContext)
  if (inStrip) {
    return (
      <li
        data-slot="stat-tile"
        className={cn(
          'flex min-w-0 flex-auto flex-col gap-1 px-1.5 first:pl-0 min-[360px]:px-2.5 sm:flex-none sm:flex-row sm:items-center sm:gap-3 sm:px-6 lg:px-8',
          className,
        )}
      >
        <IconTile icon={icon} tone={tone} size="sm" className="sm:size-10 sm:[&>svg]:size-5" />
        <span className="flex min-w-0 flex-col">
          <span className="num text-2xl leading-7 font-semibold text-ink">{value}</span>
          <span className="text-[0.6875rem] leading-4 tracking-tight whitespace-nowrap text-ink-muted sm:text-xs sm:tracking-normal">
            {label}
          </span>
        </span>
      </li>
    )
  }
  return (
    <div data-slot="stat-tile" className={cn('flex min-w-0 shrink-0 items-center gap-3', className)}>
      <IconTile icon={icon} tone={tone} size={size === 'lg' ? 'xl' : 'md'} />
      <p className="flex min-w-0 flex-col">
        <span className={cn('num font-semibold text-ink', size === 'lg' ? 'text-3xl leading-9' : 'text-2xl leading-7')}>
          {value}
        </span>
        <span className="type-caption text-ink-muted">{label}</span>
      </p>
    </div>
  )
}

export type SummaryStripProps = {
  /** Имя списка показателей для скринридера. */
  label: string
  /** Набор `StatTile`. */
  children: React.ReactNode
  /** Справа от показателей: обычно `ProgressRing`. */
  aside?: React.ReactNode
  className?: string
}

/** Сводка страницы: одна акцентная полоса с градиентом бренда — два-четыре `StatTile` и необязательное кольцо. */
export function SummaryStrip({ label, children, aside, className }: SummaryStripProps) {
  return (
    <div
      data-slot="summary-strip"
      className={cn(
        'brand-band surface-row flex min-w-0 animate-rise-in items-center gap-2 p-3 sm:gap-6 sm:p-4 md:px-6',
        className,
      )}
    >
      <ul aria-label={label} className="flex min-w-0 flex-1 items-stretch divide-x divide-line">
        <StripContext.Provider value={true}>{children}</StripContext.Provider>
      </ul>
      {/* На самых узких экранах кольцо уступает место числам: его значение повторяет их. */}
      {aside ? <div className="flex shrink-0 items-center max-[359px]:hidden">{aside}</div> : null}
    </div>
  )
}
