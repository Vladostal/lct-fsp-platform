import { cn } from '@/lib/utils'

export type PipelineLineProps = {
  /**
   * Форма линии:
   *  - horizontal / vertical — прямой отрезок с точкой на конце;
   *  - turn-down — вправо, затем скруглённый поворот вниз;
   *  - turn-right — вниз, затем скруглённый поворот вправо.
   */
  shape?: 'horizontal' | 'vertical' | 'turn-down' | 'turn-right'
  /** Точка 8 px на конце линии. */
  dot?: boolean
  /** Приглушённая линия (будущие шаги): цвет line-strong вместо brand-600. */
  muted?: boolean
  className?: string
}

/**
 * Линия-пайплайн брендбука ФСП: 2 px brand-600, скруглённый поворот, точка 8 px на конце (E §3.1).
 * Чисто декоративна: смысл дублируется текстом, поэтому aria-hidden.
 */
export function PipelineLine({ shape = 'horizontal', dot = true, muted = false, className }: PipelineLineProps) {
  const color = muted ? 'border-line-strong' : 'border-brand-600'
  const dotColor = muted ? 'bg-line-strong' : 'bg-brand-600'

  if (shape === 'horizontal') {
    return (
      <span aria-hidden="true" data-slot="pipeline-line" className={cn('relative block h-2 min-w-6', className)}>
        <span className={cn('absolute inset-x-0 top-1/2 -translate-y-1/2 border-t-2', color, dot && 'right-1')} />
        {dot ? <span className={cn('absolute top-0 right-0 size-2 rounded-full', dotColor)} /> : null}
      </span>
    )
  }
  if (shape === 'vertical') {
    return (
      <span aria-hidden="true" data-slot="pipeline-line" className={cn('relative block min-h-6 w-2', className)}>
        <span className={cn('absolute inset-y-0 left-1/2 -translate-x-1/2 border-l-2', color, dot && 'bottom-1')} />
        {dot ? <span className={cn('absolute bottom-0 left-0 size-2 rounded-full', dotColor)} /> : null}
      </span>
    )
  }
  if (shape === 'turn-down') {
    return (
      <span aria-hidden="true" data-slot="pipeline-line" className={cn('relative block min-h-8 min-w-8', className)}>
        <span className={cn('absolute inset-0 right-[3px] bottom-1 rounded-tr-lg border-t-2 border-r-2', color)} />
        {dot ? <span className={cn('absolute right-0 bottom-0 size-2 rounded-full', dotColor)} /> : null}
      </span>
    )
  }
  return (
    <span aria-hidden="true" data-slot="pipeline-line" className={cn('relative block min-h-8 min-w-8', className)}>
      <span className={cn('absolute inset-0 right-1 bottom-[3px] rounded-bl-lg border-b-2 border-l-2', color)} />
      {dot ? <span className={cn('absolute right-0 bottom-0 size-2 rounded-full', dotColor)} /> : null}
    </span>
  )
}
