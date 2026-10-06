import type { Contribution } from '@/client'
import { formatDecimal } from '@/lib/format'
import { cn } from '@/lib/utils'

export type ContributionBarsProps = {
  items: readonly Contribution[]
  className?: string
}

/**
 * Вклады в оценку (E §3.3). Строка: подпись (до двух строк), полоса на треке fill (заливка brand-600,
 * длина points / max_points), справа mono «{points} из {max_points}». Отрицательный вклад (давность):
 * полосы нет, значение «−0,8». Строка `fsp` с нулём не рисуется (кандидат без истории ФСП не штрафуется).
 * Раскладка зависит от ширины контейнера: в узком полоса уходит под подпись.
 */
export function ContributionBars({ items, className }: ContributionBarsProps) {
  const rows = items.filter((item) => !(item.code === 'fsp' && item.points === 0))
  if (rows.length === 0) return null

  return (
    <div data-slot="contribution-bars" className={cn('@container min-w-0', className)}>
      {/* Одна сетка на все строки (subgrid): полосы и числа выровнены по общим колонкам. */}
      <dl className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-3 @md:grid-cols-[minmax(0,5fr)_minmax(0,4fr)_auto]">
        {rows.map((item) => {
          const negative = item.points < 0
          const share = item.max_points > 0 ? Math.min(1, Math.max(0, item.points / item.max_points)) : 0
          return (
            <div
              key={`${item.group}-${item.code}`}
              className="col-span-full grid min-w-0 grid-cols-subgrid items-center gap-y-1.5"
            >
              <dt className="type-sm min-w-0 text-ink">{item.label}</dt>
              <dd className="num type-sm justify-self-end text-ink @md:order-3">
                {negative
                  ? formatDecimal(item.points)
                  : `${formatDecimal(item.points)} из ${formatDecimal(item.max_points)}`}
              </dd>
              {negative ? (
                <span className="hidden @md:order-2 @md:block" aria-hidden="true" />
              ) : (
                <span
                  className="col-span-2 block h-2 overflow-hidden rounded-xs bg-fill @md:order-2 @md:col-span-1"
                  aria-hidden="true"
                >
                  <span className="block h-full rounded-xs bg-brand-600" style={{ width: `${share * 100}%` }} />
                </span>
              )}
            </div>
          )
        })}
      </dl>
    </div>
  )
}
