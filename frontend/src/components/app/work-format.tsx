import { Building2, Laptop, type LucideIcon, Shuffle } from 'lucide-react'
import type { WorkFormat } from '@/client'
import { Checkbox } from '@/components/ui/checkbox'
import { WORK_FORMAT_LABELS } from '@/content/common'
import { cn } from '@/lib/utils'
import { SoftPill, type SoftPillProps } from './soft-pill'

/** Значок формата работы: один на все экраны (пилюли, чипы выбора, карточки). */
export const FORMAT_ICON: Record<WorkFormat, LucideIcon> = { office: Building2, hybrid: Shuffle, remote: Laptop }

/** Подпись формата работы с заглавной буквы: «Офис», «Гибрид», «Удалённо». */
export function FormatLabel({ format }: { format: WorkFormat }) {
  return <span className="inline-block first-letter:uppercase">{WORK_FORMAT_LABELS[format]}</span>
}

export type FormatPillProps = Pick<SoftPillProps, 'tone' | 'size' | 'title' | 'className'> & { format: WorkFormat }

/** Пилюля формата работы: значок и подпись с заглавной. */
export function FormatPill({ format, ...pill }: FormatPillProps) {
  return (
    <SoftPill icon={FORMAT_ICON[format] ?? Laptop} {...pill}>
      <FormatLabel format={format} />
    </SoftPill>
  )
}

export type FormatChoiceProps = {
  format: WorkFormat
  checked: boolean
  onCheckedChange: (checked: boolean) => void
  /** `id` чекбокса: по нему подпись связана с полем. */
  id: string
  className?: string
}

/** Чип-чекбокс формата работы в формах: флажок, значок и подпись; выбранный — заливка бренда. */
export function FormatChoice({ format, checked, onCheckedChange, id, className }: FormatChoiceProps) {
  const Icon = FORMAT_ICON[format] ?? Laptop
  return (
    <label
      htmlFor={id}
      data-slot="format-choice"
      className={cn(
        'type-body flex min-h-11 cursor-pointer items-center gap-2 rounded-full border border-line bg-surface pr-4 pl-3 transition-colors hover:border-brand-200 has-[[data-state=checked]]:border-brand-600 has-[[data-state=checked]]:bg-brand-50 has-[[data-state=checked]]:text-brand-700',
        className,
      )}
    >
      <Checkbox id={id} checked={checked} onCheckedChange={(on) => onCheckedChange(on === true)} />
      <Icon className="size-4" aria-hidden="true" />
      <FormatLabel format={format} />
    </label>
  )
}
