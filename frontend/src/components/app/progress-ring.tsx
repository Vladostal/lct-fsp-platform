import type * as React from 'react'
import { cn } from '@/lib/utils'
import { CHART, type ChartColor } from './tone'

export type RingSegment = { key: string; value: number; color: ChartColor }

export type ProgressRingProps = {
  /** Доступное имя графика: что показано и числа («Принято 2 из 11»). Обязательно. */
  label: string
  /** Одна доля 0…1 — кольцо прогресса со скруглённым концом. */
  value?: number
  /** Цвет доли при `value`. */
  color?: ChartColor
  /** Несколько долей — кольцо-диаграмма с зазорами; нулевые не рисуются. Задаётся вместо `value`. */
  segments?: readonly RingSegment[]
  /** Дорожка под долями: `fill` — серая (диаграмма), `brand` — brand-100 (прогресс на акцентной полосе). */
  track?: 'fill' | 'brand'
  /** Содержимое центра: число, процент. Если оно повторяет `label`, передавайте с aria-hidden. */
  children?: React.ReactNode
  /** Размер задаётся классом (`size-16`, `size-32`); по умолчанию 64 px. */
  className?: string
}

/**
 * Кольцо: прогресс одной доли либо диаграмма исходов. SVG с role="img" и доступным именем; центр — обычное
 * содержимое. Окружность нормирована к 100 через pathLength: длина дуги равна её проценту.
 */
export function ProgressRing({
  label,
  value,
  color = 'success',
  segments,
  track = segments ? 'fill' : 'brand',
  children,
  className,
}: ProgressRingProps) {
  const single = segments === undefined
  const parts: readonly RingSegment[] = segments ?? []
  const total = parts.reduce((sum, s) => sum + s.value, 0)
  const visible = parts.filter((s) => s.value > 0)
  const gap = visible.length > 1 ? 1.5 : 0
  let offset = 0
  const arcs = visible.map((s) => {
    const length = (s.value / total) * 100
    const arc = { ...s, start: offset, length: Math.max(length - gap, 0.5) }
    offset += length
    return arc
  })
  const share = Math.min(1, Math.max(0, value ?? 0)) * 100
  return (
    <div
      data-slot="progress-ring"
      title={single ? label : undefined}
      className={cn('relative flex size-16 shrink-0 items-center justify-center', className)}
    >
      <svg viewBox="0 0 120 120" role="img" aria-label={label} className="absolute inset-0 size-full -rotate-90">
        <circle
          cx="60"
          cy="60"
          r="50"
          fill="none"
          strokeWidth="12"
          stroke={track === 'brand' ? 'var(--color-brand-100)' : 'var(--color-fill)'}
        />
        {single ? (
          share > 0 ? (
            <circle
              cx="60"
              cy="60"
              r="50"
              fill="none"
              strokeWidth="12"
              strokeLinecap="round"
              pathLength={100}
              stroke={CHART[color]}
              strokeDasharray={`${share} 100`}
            />
          ) : null
        ) : (
          arcs.map((a) => (
            <circle
              key={a.key}
              cx="60"
              cy="60"
              r="50"
              fill="none"
              strokeWidth="12"
              pathLength={100}
              stroke={CHART[a.color]}
              strokeDasharray={`${a.length} ${100 - a.length}`}
              strokeDashoffset={-a.start}
            />
          ))
        )}
      </svg>
      {children !== undefined ? (
        <div className="relative flex flex-col items-center justify-center">{children}</div>
      ) : null}
    </div>
  )
}
