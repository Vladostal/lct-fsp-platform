import { ChevronRight, type LucideIcon } from 'lucide-react'
import type * as React from 'react'
import { cn } from '@/lib/utils'
import { SOFT_TONE, type Tone } from './tone'

type PillTone = Tone | 'solid'

const PILL_TONE: Record<PillTone, string> = { ...SOFT_TONE, solid: 'bg-brand-600 text-on-brand' }

export type SoftPillProps = {
  /** `success` — вилка, `neutral` — формат и прочие факты, `solid` — акцент на заливке бренда. */
  tone?: PillTone
  icon?: LucideIcon
  /** `md` 28 px (по умолчанию), `sm` 24 px — в таблицах и плотных строках. */
  size?: 'sm' | 'md'
  title?: string
  children: React.ReactNode
  className?: string
}

/** Мягкая плашка-пилюля: один факт в одно-два слова (вилка, формат работы, срок), со значком или без. */
export function SoftPill({ tone = 'neutral', icon: Icon, size = 'md', title, children, className }: SoftPillProps) {
  return (
    <span
      data-slot="soft-pill"
      title={title}
      className={cn(
        'inline-flex max-w-full min-w-0 shrink-0 items-center gap-1.5 rounded-full text-sm',
        size === 'sm' ? 'h-6 px-2.5' : Icon ? 'h-7 px-2.5' : 'h-7 px-3',
        PILL_TONE[tone],
        className,
      )}
    >
      {Icon ? <Icon aria-hidden="true" className="size-4" /> : null}
      {children}
    </span>
  )
}

export type CountChipProps = {
  icon: LucideIcon
  value: number
  /** Что считает число: всплывающая подсказка и текст для скринридера. */
  label: string
  tone?: PillTone
  /** Новое событие: пульсирующая точка и появление «хлопком». Обычно вместе с `tone="solid"`. */
  live?: boolean
  className?: string
}

/** Счётчик-чип: значок и число, смысл — в подсказке и для скринридера. Для второстепенных чисел карточки. */
export function CountChip({ icon: Icon, value, label, tone = 'neutral', live = false, className }: CountChipProps) {
  return (
    <span
      data-slot="count-chip"
      title={label}
      className={cn(
        'relative inline-flex h-7 shrink-0 items-center gap-1.5 rounded-full px-2.5 text-sm font-medium',
        live && 'animate-pop-in pr-3',
        PILL_TONE[tone],
        className,
      )}
    >
      {live ? <span aria-hidden="true" className="ping-dot size-2 rounded-full bg-current" /> : null}
      <Icon aria-hidden="true" className="size-4" />
      <span className="sr-only">{label}: </span>
      <span className="num">{value}</span>
    </span>
  )
}

/**
 * Кружок со стрелкой в углу кликабельной карточки: внутри `.lift-card` при наведении заливается брендом
 * и сдвигается вправо. Декоративен; на узком экране скрыт.
 */
export function GoChevron({ className }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      data-slot="go-chevron"
      className={cn(
        'go-chip hidden size-7 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-700 sm:flex',
        className,
      )}
    >
      <ChevronRight className="size-4" />
    </span>
  )
}
