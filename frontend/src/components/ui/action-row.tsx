import * as React from 'react'
import { useNarrowActions } from '@/lib/hooks/use-media-query'
import { cn } from '@/lib/utils'

/**
 * Ряд кнопок подвала диалога, панели и липкой панели действий (E §4.2).
 * Кнопки передаются в порядке чтения на широком экране: вторичные слева, основная — последней (справа).
 * Ниже 480 px они встают столбцом на всю ширину, основная — первой. Порядок меняется в DOM, а не стилями,
 * поэтому порядок Tab всегда совпадает с порядком чтения (E §9.1, G10).
 * Кнопки должны быть прямыми потомками (не внутри фрагмента).
 */
function ActionRow({ className, children, ...props }: React.ComponentProps<'div'>) {
  const narrow = useNarrowActions()
  const items = React.Children.toArray(children)
  return (
    <div
      data-slot="action-row"
      className={cn(
        'flex min-w-0',
        narrow ? 'flex-col items-stretch gap-3' : 'flex-row flex-wrap items-center justify-end gap-3',
        className,
      )}
      {...props}
    >
      {narrow ? items.reverse() : items}
    </div>
  )
}

export { ActionRow }
