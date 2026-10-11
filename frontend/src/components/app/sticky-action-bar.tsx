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
  /** Устарело: панель сама берёт ширину и положение колонки, в которой стоит. */
  width?: 'wizard' | 'focus' | 'page'
  className?: string
}

/** Зазор между панелью и нижним краем окна. */
const GAP = 12

/**
 * Липкая панель действий внизу экрана (E §4.4) — один шаблон на все экраны: плавающая белая карточка с тенью
 * шириной в контентную колонку. Колонку задаёт распорка в потоке: панель повторяет её левый край и ширину,
 * поэтому в мастере, тесте и кабинете она стоит ровно под содержимым. Распорка же не даёт панели закрыть
 * последний блок, а переменная --action-bar-space на <html> задаёт scroll-padding-bottom и сдвиг toast.
 */
export function StickyActionBar({ children, secondary, note, className }: StickyActionBarProps) {
  const barRef = useRef<HTMLDivElement>(null)
  const spacerRef = useRef<HTMLDivElement>(null)
  const [height, setHeight] = useState(72)
  const [box, setBox] = useState<{ left: number; width: number } | null>(null)
  const narrow = useNarrowActions()

  useLayoutEffect(() => {
    const bar = barRef.current
    const spacer = spacerRef.current
    if (!bar || !spacer) return
    const root = document.documentElement
    const update = () => {
      const next = Math.ceil(bar.getBoundingClientRect().height)
      setHeight(next)
      root.style.setProperty('--action-bar-space', `${next + GAP + 24}px`)
      const rect = spacer.getBoundingClientRect()
      setBox((prev) =>
        prev && prev.left === rect.left && prev.width === rect.width ? prev : { left: rect.left, width: rect.width },
      )
    }
    update()
    const observer = new ResizeObserver(update)
    observer.observe(bar)
    observer.observe(spacer)
    observer.observe(root)
    window.addEventListener('resize', update)
    return () => {
      observer.disconnect()
      window.removeEventListener('resize', update)
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
      <div ref={spacerRef} aria-hidden="true" className="w-full shrink-0" style={{ height: height + GAP * 2 }} />
      <div
        ref={barRef}
        data-slot="sticky-action-bar"
        data-sticky="bottom"
        style={box ? { left: box.left, width: box.width } : undefined}
        className={cn(
          'surface-row fixed bottom-[calc(12px+env(safe-area-inset-bottom))] z-20 flex min-h-16 min-w-0 gap-x-4 gap-y-3 px-4 py-3 shadow-(--shadow-pop)',
          box ? null : 'inset-x-4',
          narrow ? 'flex-col' : 'flex-row items-center',
          className,
        )}
      >
        {narrow ? [main, side] : [side, main]}
      </div>
    </>
  )
}
