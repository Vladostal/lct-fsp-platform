import { Skeleton } from '@/components/ui/skeleton'
import { COMMON } from '@/content/common'
import { cn } from '@/lib/utils'

export type PageSkeletonProps = {
  /** Геометрия содержимого: форма, список строк или карточки. */
  variant?: 'form' | 'list' | 'cards'
  className?: string
}

/**
 * Скелетон страницы для `pendingComponent` маршрута (E §2.0, §5): та же геометрия, что у готового экрана —
 * заголовок, затем блоки; пустого белого экрана не бывает. Экран с особой раскладкой задаёт свой скелетон.
 */
export function PageSkeleton({ variant = 'cards', className }: PageSkeletonProps) {
  return (
    <div data-slot="page-skeleton" aria-busy="true" className={cn('flex min-w-0 flex-col gap-6', className)}>
      <span className="sr-only" role="status">
        {COMMON.loading}
      </span>
      <div className="flex flex-col gap-3">
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-8 w-2/3 max-w-md md:h-10" />
        <Skeleton className="h-6 w-full max-w-xl" />
      </div>
      {variant === 'form' ? (
        <div className="flex flex-col gap-6 rounded-lg bg-surface p-4 shadow-card md:rounded-xl md:p-6">
          {[0, 1, 2, 3].map((row) => (
            <div key={row} className="flex flex-col gap-2">
              <Skeleton className="h-5 w-40" />
              <Skeleton className="h-11 w-full" />
            </div>
          ))}
        </div>
      ) : null}
      {variant === 'list' ? (
        <div className="flex flex-col gap-3">
          {[0, 1, 2, 3, 4, 5, 6, 7].map((row) => (
            <Skeleton key={row} className="h-[104px] w-full rounded-lg" />
          ))}
        </div>
      ) : null}
      {variant === 'cards' ? (
        <div className="grid gap-4 md:gap-6 lg:grid-cols-2">
          {[0, 1, 2].map((card) => (
            <div key={card} className="flex flex-col gap-4 rounded-lg bg-surface p-4 shadow-card md:rounded-xl md:p-6">
              <Skeleton className="h-7 w-1/2" />
              <Skeleton className="h-5 w-full" />
              <Skeleton className="h-5 w-4/5" />
              <Skeleton className="h-11 w-40 rounded-full" />
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}
