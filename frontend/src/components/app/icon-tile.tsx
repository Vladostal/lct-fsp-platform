import type { LucideIcon } from 'lucide-react'
import type * as React from 'react'
import { cn } from '@/lib/utils'
import { TILE_TONE, type TileTone } from './tone'

export type IconTileProps = {
  /** Значок lucide; вместо него можно передать `children` (инициалы, число). */
  icon?: LucideIcon
  tone?: TileTone
  /** Сторона плитки и значка: xs 28/14, sm 32/16, md 40/20, lg 44/20, xl 48/24. */
  size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl'
  children?: React.ReactNode
  className?: string
}

const SIZE = {
  xs: 'size-7 rounded-md [&>svg]:size-3.5',
  sm: 'size-8 [&>svg]:size-4',
  md: 'size-10 [&>svg]:size-5',
  lg: 'size-11 [&>svg]:size-5',
  xl: 'size-12 [&>svg]:size-6',
} as const

/**
 * Плитка со значком: скруглённый квадрат мягкого тона. Первый элемент любой карточки и строки —
 * по форме и цвету читается, что это и в каком оно состоянии. Декоративна (aria-hidden): смысл дублирует подпись.
 */
export function IconTile({ icon: Icon, tone = 'brand', size = 'md', children, className }: IconTileProps) {
  return (
    <span
      aria-hidden="true"
      data-slot="icon-tile"
      className={cn(
        'type-sm flex shrink-0 items-center justify-center rounded-lg font-semibold',
        SIZE[size],
        TILE_TONE[tone],
        className,
      )}
    >
      {Icon ? <Icon /> : children}
    </span>
  )
}
