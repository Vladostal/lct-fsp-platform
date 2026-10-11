import type { LucideIcon } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import { IconTile } from './icon-tile'
import type { TileTone } from './tone'

export type FunnelStripProps = {
  /** Ступень: число и подпись в одно-два слова; `icon` добавляет плитку со значком тона `tone`. */
  steps: readonly { label: string; value: number; icon?: LucideIcon; tone?: TileTone }[]
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
      <span aria-hidden="true" className="num text-2xl leading-7 font-semibold text-ink">
        {shown}
      </span>
      <span className="sr-only">{value}</span>
    </>
  )
}

/**
 * Показатели в строку в виде `StatTile`: необязательная плитка со значком, крупное число, подпись.
 * Между ячейками тонкий разделитель; на узких экранах переносится. Числа плавно доезжают до нового значения.
 */
export function FunnelStrip({ steps, className }: FunnelStripProps) {
  return (
    // Разделитель слева у каждой ячейки; у первой в строке он уходит за обрезанный край.
    <div data-slot="funnel-strip" className={cn('min-w-0 overflow-hidden', className)}>
      <ol className="-ml-[17px] flex min-w-0 flex-wrap gap-y-3">
        {steps.map((step) => (
          <li key={step.label} className="flex min-w-[136px] flex-1 items-center gap-3 border-l border-line px-4">
            {step.icon ? <IconTile icon={step.icon} tone={step.tone ?? 'brand'} /> : null}
            <span className="flex min-w-0 flex-col">
              <span className="flex">
                <FunnelValue value={step.value} />
              </span>
              <span className="type-caption text-ink-muted">{step.label}</span>
            </span>
          </li>
        ))}
      </ol>
    </div>
  )
}
