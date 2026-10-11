import type { LevelView } from '@/client'
import { cn } from '@/lib/utils'

export type LevelScaleProps = {
  /** Уровень с интервалом; координаты 0–100 приходят с сервера. */
  level: Pick<LevelView, 'point' | 'lower' | 'upper' | 'thresholds' | 'verdict_label'>
  /** `md` — на всю ширину (не уже 240 px), подписи всех порогов; `sm` — 160 px, подпись порога своего грейда. */
  size?: 'sm' | 'md'
  /** Код грейда категории: его порог подписан в `sm` и назван в текстовой замене. */
  ownGrade?: string
  /** Показать вердикт текстом над шкалой (по умолчанию да: вердикт всегда стоит рядом со шкалой). */
  showVerdict?: boolean
  /** Появление интервала «от точки» (один раз, только `md`). */
  animate?: boolean
  className?: string
}

const clamp = (value: number, min = 0, max = 100) => Math.min(max, Math.max(min, value))

/**
 * Шкала уровня (E §3.3): уровень — интервал и точка, а не балл. Трек 8 px, интервал brand-600, точка 12 px
 * с кольцом brand-900, пороги — штрихи 2 × 16 px с подписью грейда. Чисел, процентов и баллов нет.
 * Текстовая замена обязательна: role="img" с aria-label, рядом — вердикт текстом.
 *
 * Подписи порогов стоят в потоке, а не абсолютно: каждой отведён отрезок, симметричный относительно её штриха
 * и ограниченный серединами расстояний до соседних порогов и краями трека, — так подписи не накладываются
 * друг на друга и не выходят за шкалу.
 */
export function LevelScale({
  level,
  size = 'md',
  ownGrade,
  showVerdict = true,
  animate = false,
  className,
}: LevelScaleProps) {
  const lower = clamp(Math.min(level.lower, level.upper))
  const upper = clamp(Math.max(level.lower, level.upper))
  const point = clamp(level.point)
  const width = Math.max(upper - lower, 3)
  const left = Math.min(lower, 100 - width)
  const thresholds = [...level.thresholds].sort((a, b) => a.pos - b.pos)
  const own = thresholds.find((threshold) => threshold.grade.code === ownGrade)

  const thresholdText = (own ? [own] : thresholds)
    .map((threshold) => `порог ${threshold.grade.title} — ${Math.round(threshold.pos)}`)
    .join(', ')
  const ariaLabel = `Уровень: ${level.verdict_label}. Интервал оценки от ${Math.round(lower)} до ${Math.round(upper)} из 100${thresholdText ? `, ${thresholdText}` : ''}`

  // Отрезки подписей: [pos − h, pos + h], где h — расстояние до ближайшей границы (середина до соседа или край).
  const labelled = size === 'md' ? thresholds : own ? [own] : []
  const boxes = labelled.map((threshold, index) => {
    const prev = labelled[index - 1]
    const next = labelled[index + 1]
    const leftBound = prev ? (prev.pos + threshold.pos) / 2 : 0
    const rightBound = next ? (threshold.pos + next.pos) / 2 : 100
    const half = Math.max(0, Math.min(threshold.pos - leftBound, rightBound - threshold.pos))
    return { threshold, start: threshold.pos - half, end: threshold.pos + half }
  })

  return (
    <div
      data-slot="level-scale"
      data-size={size}
      className={cn('flex min-w-0 flex-col gap-2', size === 'md' ? 'w-full min-w-[240px]' : 'w-40 shrink-0', className)}
    >
      {showVerdict ? (
        <p className={cn('min-w-0 font-medium text-ink', size === 'md' ? 'type-body' : 'type-sm')}>
          {level.verdict_label}
        </p>
      ) : null}
      <div role="img" aria-label={ariaLabel} className="flex min-w-0 flex-col gap-1">
        <div className="relative h-4">
          <div className="absolute inset-x-0 top-1 h-2 rounded-xs bg-fill" />
          <div
            className={cn('absolute top-1 h-2 rounded-xs bg-brand-600', animate && size === 'md' && 'animate-grow-x')}
            style={{
              left: `${left}%`,
              width: `${width}%`,
              transformOrigin: `${clamp(((point - left) / width) * 100)}% 50%`,
            }}
          />
          {thresholds.map((threshold) => (
            <span
              key={threshold.grade.code}
              className="absolute top-0 h-4 w-0.5 -translate-x-1/2 rounded-full bg-ink-muted"
              style={{ left: `${clamp(threshold.pos)}%` }}
            />
          ))}
          <span
            className="absolute top-0.5 size-3 -translate-x-1/2 rounded-full border-2 border-brand-900 bg-surface dark:border-brand-700"
            style={{ left: `clamp(6px, ${point}%, calc(100% - 6px))` }}
          />
        </div>
        {boxes.length > 0 ? (
          <div className="flex min-h-4" aria-hidden="true">
            {boxes.map((box, index) => {
              const prevEnd = index === 0 ? 0 : (boxes[index - 1]?.end ?? 0)
              return (
                <span key={box.threshold.grade.code} className="contents">
                  <span className="shrink-0" style={{ width: `${Math.max(0, box.start - prevEnd)}%` }} />
                  <span
                    className="type-caption shrink-0 text-center whitespace-nowrap text-ink-muted"
                    style={{ width: `${box.end - box.start}%` }}
                  >
                    {box.threshold.grade.title}
                  </span>
                </span>
              )
            })}
          </div>
        ) : null}
      </div>
    </div>
  )
}
