import {
  BrainCircuit,
  Bug,
  Code,
  Container,
  Crown,
  Database,
  Gem,
  type LucideIcon,
  MonitorSmartphone,
  Rocket,
  Server,
  ShieldCheck,
  Smartphone,
  Sprout,
} from 'lucide-react'
import type * as React from 'react'
import { IconTile, type TileTone } from '@/components/app'
import { cn } from '@/lib/utils'

/*
 * Местные части экранов тестирования в едином стиле кабинетов: шапка карточки с плиткой, строки правил
 * со значками, значки специализаций и грейдов. Общих примитивов для них нет — собраны из IconTile.
 */

/** Значок специализации или направления по коду: явная карта, как в карточке потребности работодателя. */
const SPEC_ICONS: readonly [string, LucideIcon][] = [
  ['back', Server],
  ['front', MonitorSmartphone],
  ['mobile', Smartphone],
  ['android', Smartphone],
  ['ios', Smartphone],
  ['devops', Container],
  ['infra', Container],
  ['sre', Container],
  ['qa', Bug],
  ['quality', Bug],
  ['test', Bug],
  ['ml', BrainCircuit],
  ['data', Database],
  ['analy', Database],
  ['sec', ShieldCheck],
]

export function specIcon(code: string | null | undefined): LucideIcon {
  const c = (code ?? '').toLowerCase()
  return SPEC_ICONS.find(([k]) => c.includes(k))?.[1] ?? Code
}

const GRADE_ICONS: readonly LucideIcon[] = [Sprout, Rocket, Crown, Gem]

/** Значок грейда по порядку в справочнике: росток, ракета, корона. */
export function gradeIcon(index: number): LucideIcon {
  return GRADE_ICONS[Math.min(Math.max(index, 0), GRADE_ICONS.length - 1)] ?? Gem
}

/** Шапка карточки: плитка со значком, заголовок и необязательный блок справа (пилюля, ссылка). */
export function CardHead({
  id,
  icon,
  tone = 'brand',
  title,
  aside,
  as: Heading = 'h2',
  className,
}: {
  id?: string
  icon: LucideIcon
  tone?: TileTone
  title: React.ReactNode
  aside?: React.ReactNode
  as?: 'h2' | 'h3'
  className?: string
}) {
  return (
    <div className={cn('flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2', className)}>
      <IconTile icon={icon} tone={tone} />
      <Heading id={id} className="type-h3 min-w-0 flex-1">
        {title}
      </Heading>
      {aside ? <div className="flex min-w-0 shrink-0 flex-wrap items-center gap-2">{aside}</div> : null}
    </div>
  )
}

export type RuleItem = { icon: LucideIcon; text: React.ReactNode; tone?: TileTone }

/** Правила строками «плитка + короткая фраза»: вместо абзаца и маркированного списка. */
export function RuleList({
  items,
  columns = 1,
  className,
}: {
  items: readonly RuleItem[]
  columns?: 1 | 2 | 3
  className?: string
}) {
  return (
    <ul
      className={cn(
        'grid min-w-0 gap-x-6 gap-y-3',
        columns === 2 && 'md:grid-cols-2',
        columns === 3 && 'md:grid-cols-3',
        className,
      )}
    >
      {items.map((item, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: порядок правил постоянен
        <li key={i} className="type-sm flex min-w-0 items-start gap-2.5 text-ink">
          <IconTile icon={item.icon} tone={item.tone ?? 'soft'} size="xs" />
          <span className="min-w-0 break-words pt-1">{item.text}</span>
        </li>
      ))}
    </ul>
  )
}
