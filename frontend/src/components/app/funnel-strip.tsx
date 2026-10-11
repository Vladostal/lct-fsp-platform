import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'

export type FunnelStripProps = {
  steps: readonly { label: string; value: number }[]
  className?: string
}

function canAnimate(): boolean {
  if (typeof requestAnimationFrame !== 'function') return false
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  return !window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/** Плавный переход целого числа к новому значению; первый рендер без анимации. */
function useTweenedNumber(target: number, ms = 400): number {
  const [shown, setShown] = useState(target)
  // Текущее отображаемое значение: новая анимация стартует с него, а не с прошлой цели.
  const shownRef = useRef(target)
  const animate = canAnimate()

  useEffect(() => {
    if (!animate) {
      shownRef.current = target
      setShown(target)
      return
    }
    const from = shownRef.current
    if (from === target) return
    const start = performance.now()
    let raf = 0
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / ms)
      const eased = 1 - (1 - t) ** 3
      // Последний кадр ставит ровно target, без накопленного округления.
      const next = t >= 1 ? target : Math.round(from + (target - from) * eased)
      shownRef.current = next
      setShown(next)
      if (t < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [target, ms, animate])

  return animate ? shown : target
}

function FunnelValue({ value }: { value: number }) {
  const shown = useTweenedNumber(value)
  return (
    <>
      <span aria-hidden="true" className="num text-xl leading-7 font-medium text-ink tabular-nums">
        {shown}
      </span>
      <span className="sr-only">{value}</span>
    </>
  )
}

/** Воронка в строку: числа mono с подписью, между ними тонкая линия. Переносится на узких экранах. */
export function FunnelStrip({ steps, className }: FunnelStripProps) {
  return (
    <ol data-slot="funnel-strip" className={cn('flex min-w-0 flex-wrap gap-y-3', className)}>
      {steps.map((step) => (
        <li key={step.label} className="flex min-w-[136px] flex-1 flex-col gap-0.5 border-l border-line pr-4 pl-4">
          <FunnelValue value={step.value} />
          <span className="type-caption text-ink-muted">{step.label}</span>
        </li>
      ))}
    </ol>
  )
}
