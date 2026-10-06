import { cn } from '@/lib/utils'

export type CategoryChipProps = {
  /** Название категории как пришло с сервера: «Backend · Middle». */
  title: string
  /** `lg` — 22 / 500 на экране результата. */
  size?: 'md' | 'lg'
  className?: string
}

/** Категория — специализация и подтверждённый грейд: mono, фон brand-50, текст brand-700, в одну строку. */
export function CategoryChip({ title, size = 'md', className }: CategoryChipProps) {
  return (
    <span
      data-slot="category-chip"
      className={cn(
        'num inline-flex w-fit max-w-full shrink-0 items-center rounded-full bg-brand-50 font-medium text-brand-700',
        size === 'lg' ? 'min-h-11 px-5 text-xl leading-7 md:text-[1.375rem]' : 'h-7 px-3 text-sm leading-5',
        className,
      )}
    >
      {title}
    </span>
  )
}
