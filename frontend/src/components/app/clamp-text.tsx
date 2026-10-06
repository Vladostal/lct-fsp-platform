import { useLayoutEffect, useRef, useState } from 'react'
import { COMMON } from '@/content/common'
import { cn } from '@/lib/utils'

export type ClampTextProps = {
  /** Пользовательский текст: описание предложения, «О себе», комментарий. */
  text: string
  className?: string
}

/**
 * Длинный пользовательский текст (E §4.3): переносы строк сохраняются, слова без пробелов переносятся;
 * в превью — не больше шести строк и кнопка «Показать полностью». Усечение явное и обратимое.
 */
export function ClampText({ text, className }: ClampTextProps) {
  const ref = useRef<HTMLParagraphElement>(null)
  const [expanded, setExpanded] = useState(false)
  const [overflowing, setOverflowing] = useState(false)

  // biome-ignore lint/correctness/useExhaustiveDependencies: измеряем заново при смене текста
  useLayoutEffect(() => {
    const node = ref.current
    if (!node || expanded) return
    const measure = () => setOverflowing(node.scrollHeight > node.clientHeight + 1)
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(node)
    return () => observer.disconnect()
  }, [text, expanded])

  return (
    <div data-slot="clamp-text" className={cn('flex min-w-0 flex-col items-start gap-1', className)}>
      <p
        ref={ref}
        title={!expanded && overflowing ? text : undefined}
        className={cn(
          'type-body min-w-0 whitespace-pre-line text-ink [overflow-wrap:anywhere]',
          !expanded && 'line-clamp-6',
        )}
      >
        {text}
      </p>
      {overflowing || expanded ? (
        <button
          type="button"
          aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}
          className="text-link inline-flex min-h-11 items-center text-sm"
        >
          {expanded ? COMMON.showLess : COMMON.showMore}
        </button>
      ) : null}
    </div>
  )
}
