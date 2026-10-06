import type * as React from 'react'
import { useLayoutEffect, useRef, useState } from 'react'
import { ActionRow } from '@/components/ui/action-row'
import { useNarrowActions } from '@/lib/hooks/use-media-query'
import { cn } from '@/lib/utils'

export type StickyActionBarProps = {
  /**
   * Действия шага в порядке чтения на широком экране: вторичные, затем основное (оно справа).
   * Ниже 480 px кнопки встают столбцом, основная — первой.
   */
  children: React.ReactNode
  /** Действие у левого края — обычно «Назад» (ghost). На узком экране — последним в столбце. */
  secondary?: React.ReactNode
  /** Подпись под основным действием: «Сохранено в 14:02», причина недоступности кнопки. */
  note?: React.ReactNode
  /** Ширина содержимого панели: колонка мастера 720, колонка теста 880 или контейнер страницы. */
  width?: 'wizard' | 'focus' | 'page'
  className?: string
}

const WIDTH: Record<NonNullable<StickyActionBarProps['width']>, string> = {
  wizard: 'max-w-[720px]',
  focus: 'max-w-[880px]',
  page: 'max-w-[1340px]',
}

/**
 * Липкая панель действий внизу экрана (E §4.4): слой 20, тень shadow-bar, отступ под безопасную зону.
 * Чтобы панель не закрывала последний блок и элемент в фокусе, компонент оставляет в потоке распорку своей
 * высоты и выставляет на <html> переменную --action-bar-space: её читают scroll-padding-bottom и сдвиг toast.
 */
export function StickyActionBar({ children, secondary, note, width = 'wizard', className }: StickyActionBarProps) {
  const barRef = useRef<HTMLDivElement>(null)
  const [height, setHeight] = useState(72)
  const narrow = useNarrowActions()

  useLayoutEffect(() => {
    const bar = barRef.current
    if (!bar) return
    const root = document.documentElement
    const update = () => {
      const next = Math.ceil(bar.getBoundingClientRect().height)
      setHeight(next)
      root.style.setProperty('--action-bar-space', `${next + 24}px`)
    }
    update()
    const observer = new ResizeObserver(update)
    observer.observe(bar)
    return () => {
      observer.disconnect()
      root.style.removeProperty('--action-bar-space')
    }
  }, [])

  const main = (
    <div key="main" className={cn('flex min-w-0 flex-col gap-1', narrow ? 'items-stretch' : 'ml-auto items-end')}>
      <ActionRow>{children}</ActionRow>
      {note ? <div className={cn('type-caption min-w-0 text-ink-muted', narrow && 'text-center')}>{note}</div> : null}
    </div>
  )
  const side = secondary ? (
    <div key="side" className={cn('flex min-w-0 shrink-0 flex-col', narrow && 'items-stretch')}>
      {secondary}
    </div>
  ) : null

  return (
    <>
      <div aria-hidden="true" style={{ height: height + 24 }} />
      <div
        ref={barRef}
        data-slot="sticky-action-bar"
        data-sticky="bottom"
        className={cn(
          'fixed inset-x-0 bottom-0 z-20 border-t border-line bg-surface pb-[env(safe-area-inset-bottom)] shadow-bar',
          className,
        )}
      >
        <div
          className={cn(
            'mx-auto flex min-h-[72px] w-full min-w-0 gap-x-4 gap-y-3 px-4 py-3 md:px-6',
            narrow ? 'flex-col' : 'flex-row items-center',
            WIDTH[width],
          )}
        >
          {narrow ? [main, side] : [side, main]}
        </div>
      </div>
    </>
  )
}
