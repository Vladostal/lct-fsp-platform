import { useQuery } from '@tanstack/react-query'
import type { CategoryRef } from '@/client'
import { CATEGORY_DECLARED } from '@/content/common'
import { isDeclared } from '@/lib/category'
import { catalogQuery } from '@/lib/query'
import { cn } from '@/lib/utils'

export type CategoryChipProps = {
  /** Название категории как пришло с сервера: «Backend · Middle». */
  title: string
  /** `lg` — 22 / 500 на экране результата. */
  size?: 'md' | 'lg'
  /** Грейд заявлен кандидатом, теста по специализации ещё нет: рядом ставится пометка «заявлен». */
  declared?: boolean
  className?: string
}

/**
 * Категория — специализация и грейд: `md` без фона (ink), `lg` на brand-50; в одну строку.
 * Грейд подтверждён тестом либо заявлен кандидатом (`declared`): заявленный помечен пунктирным бейджем без
 * фирменной заливки, чтобы его нельзя было принять за подтверждённый.
 */
export function CategoryChip({ title, size = 'md', declared = false, className }: CategoryChipProps) {
  const chip = (
    <span
      data-slot="category-chip"
      className={cn(
        'num inline-flex w-fit max-w-full shrink-0 items-center font-medium',
        size === 'lg'
          ? 'min-h-11 rounded-full bg-brand-50 px-5 text-xl leading-7 text-brand-700 md:text-[1.375rem]'
          : 'text-sm leading-5 text-ink',
        declared && size === 'lg' && 'border border-dashed border-line-strong bg-transparent text-ink',
        !declared && className,
      )}
    >
      {title}
    </span>
  )
  if (!declared) return chip
  return (
    <span
      data-slot="category-chip-declared"
      className={cn('inline-flex max-w-full min-w-0 flex-wrap items-center gap-x-2 gap-y-1', className)}
    >
      {chip}
      <span
        title={CATEGORY_DECLARED.title}
        className="type-caption inline-flex shrink-0 items-center rounded-full border border-dashed border-line-strong px-2 py-0.5 text-ink-muted"
      >
        {CATEGORY_DECLARED.badge}
        <span className="sr-only">: {CATEGORY_DECLARED.title}</span>
      </span>
    </span>
  )
}

export type CandidateCategoryChipProps = Omit<CategoryChipProps, 'title' | 'declared'> & {
  /** Категория кандидата; `basis` может отсутствовать — тогда основание берётся из справочника. */
  category: Pick<CategoryRef, 'title' | 'basis'> & { specialization: { code: string } }
}

/** Категория кандидата с пометкой «заявлен», когда грейд не подтверждён тестом (см. `lib/category.ts`). */
export function CandidateCategoryChip({ category, ...rest }: CandidateCategoryChipProps) {
  const catalog = useQuery(catalogQuery).data
  return <CategoryChip title={category.title} declared={isDeclared(category, catalog)} {...rest} />
}
