import { SALARY } from '@/content/common'
import { formatSalaryRange, salaryRangeAriaLabel } from '@/lib/format'
import { cn } from '@/lib/utils'

export type SalaryRangeProps = {
  from: number
  to: number
  /** `sm` 14 / 500, `md` 18 / 500, `lg` 32 / 700 (24 при < 768, плавно до 18 на 320 px) с подписью «₽ в месяц» отдельной строкой. */
  size?: 'sm' | 'md' | 'lg'
  /** Узкие ячейки таблиц: «180–240 тыс. ₽», если обе границы кратны 1000. */
  compact?: boolean
  className?: string
}

/**
 * Вилка: «180 000 – 240 000 ₽» — mono, tabular-nums, всегда в одну строку (E §3.3).
 * Скринридеру читается «от 180 000 до 240 000 рублей в месяц».
 */
export function SalaryRange({ from, to, size = 'md', compact = false, className }: SalaryRangeProps) {
  const text = formatSalaryRange(from, to, { compact })
  const label = salaryRangeAriaLabel(from, to)

  if (size === 'lg') {
    return (
      <span data-slot="salary-range" className={cn('inline-flex max-w-full flex-col gap-1', className)}>
        {/*
          Ниже 768 px кегль 24 px, но на самых узких экранах он плавно уменьшается (до 18 px на 320 px):
          вилка не переносится и не усекается, поэтому «2 000 000 – 3 000 000 ₽» обязана поместиться в строку.
        */}
        <span className="num text-[clamp(1.125rem,6vw,1.5rem)] leading-8 font-bold text-ink md:text-[2rem] md:leading-10">
          <span aria-hidden="true">{text}</span>
          <span className="sr-only">{label}</span>
        </span>
        <span className="type-sm text-ink-muted" aria-hidden="true">
          {SALARY.perMonth}
        </span>
      </span>
    )
  }

  return (
    <span
      data-slot="salary-range"
      className={cn('num font-medium text-ink', size === 'sm' ? 'text-sm leading-5' : 'text-lg leading-7', className)}
    >
      <span aria-hidden="true">{text}</span>
      <span className="sr-only">{label}</span>
    </span>
  )
}
