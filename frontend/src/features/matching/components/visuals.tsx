import {
  BrainCircuit,
  Bug,
  ChevronsUp,
  ChevronUp,
  Code,
  Container,
  Database,
  type LucideIcon,
  Minus,
  MonitorSmartphone,
  Palette,
  Server,
  ShieldCheck,
  Smartphone,
  UserRound,
} from 'lucide-react'
import type * as React from 'react'
import type { FitBand, InvitationStatus, WorkFormat } from '@/client'
import {
  FORMAT_ICON,
  FormatPill,
  IconTile,
  type IconTileProps,
  SoftPill,
  StrengthPill,
  type TileTone,
  type Tone,
} from '@/components/app'
import { FIT_BAND_LABELS, type StrengthLabel } from '@/content/common'
import { cn } from '@/lib/utils'

/*
 * Локальные визуальные детали кабинета работодателя: собраны из общих примитивов (`@/components/app`),
 * чтобы экран потребности, банк и карточка кандидата выглядели как список потребностей и приглашений.
 */

type Look = { Icon: LucideIcon; tone: TileTone }

/* Та же карта, что на карточке в списке потребностей: плитка специализации одинакова на обоих экранах. */
const SPEC_LOOKS: readonly [string, Look][] = [
  ['back', { Icon: Server, tone: 'brand' }],
  ['front', { Icon: MonitorSmartphone, tone: 'solid' }],
  ['mobile', { Icon: Smartphone, tone: 'accent' }],
  ['android', { Icon: Smartphone, tone: 'accent' }],
  ['ios', { Icon: Smartphone, tone: 'accent' }],
  ['devops', { Icon: Container, tone: 'deep' }],
  ['sre', { Icon: Container, tone: 'deep' }],
  ['qa', { Icon: Bug, tone: 'success' }],
  ['test', { Icon: Bug, tone: 'success' }],
  ['ml', { Icon: BrainCircuit, tone: 'ink' }],
  ['data', { Icon: Database, tone: 'ink' }],
  ['analy', { Icon: Database, tone: 'ink' }],
  ['sec', { Icon: ShieldCheck, tone: 'deep' }],
  ['design', { Icon: Palette, tone: 'accent' }],
]

export function specLook(code: string): Look {
  const c = code.toLowerCase()
  return SPEC_LOOKS.find(([k]) => c.includes(k))?.[1] ?? { Icon: Code, tone: 'brand' }
}

export { FORMAT_ICON, StrengthPill }

/** Тон плитки кандидата по статусу приглашения — как в списке приглашений. */
const STATUS_TILE: Record<InvitationStatus, TileTone> = {
  sent: 'warning',
  viewed: 'brand',
  accepted: 'success',
  declined: 'danger',
  expired: 'warning',
  withdrawn: 'neutral',
  bounced: 'dashed',
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? '')
    .join('')
}

/** Плитка кандидата: инициалы, если имя раскрыто, иначе силуэт; тон — статус приглашения. */
export function CandidateTile({
  name,
  status,
  size = 'md',
  className,
}: {
  name?: string | null
  status?: InvitationStatus | null
  size?: IconTileProps['size']
  className?: string
}) {
  const shown = name?.trim()
  return (
    <IconTile
      tone={status ? STATUS_TILE[status] : 'soft'}
      size={size}
      icon={shown ? undefined : UserRound}
      className={className}
    >
      {shown ? initials(shown) : null}
    </IconTile>
  )
}

const BAND: Record<FitBand, { icon: LucideIcon; tone: Tone }> = {
  strong: { icon: ChevronsUp, tone: 'success' },
  good: { icon: ChevronUp, tone: 'brand' },
  partial: { icon: Minus, tone: 'neutral' },
}

/** Вердикт по строке: полоса совпадения с потребностью, а вне потребности — сила профиля. */
export function FitPill({
  band,
  strength,
  className,
}: {
  band?: FitBand | null
  strength?: StrengthLabel
  className?: string
}) {
  if (band) {
    const b = BAND[band]
    return (
      <SoftPill tone={b.tone} icon={b.icon} size="sm" className={cn('text-xs font-medium', className)}>
        {FIT_BAND_LABELS[band]}
      </SoftPill>
    )
  }
  return strength ? <StrengthPill strength={strength} className={className} /> : null
}

/** Пилюли формата работы со значками. */
export function FormatPills({ formats }: { formats: readonly WorkFormat[] }) {
  return (
    <>
      {formats.map((f) => (
        <FormatPill key={f} format={f} />
      ))}
    </>
  )
}

/** Заголовок панели: плитка со значком и название; справа — необязательное действие. */
export function PanelHead({
  icon,
  tone = 'soft',
  title,
  id,
  as: Heading = 'h2',
  count,
  action,
  className,
}: {
  icon: LucideIcon
  tone?: TileTone
  title: React.ReactNode
  id?: string
  as?: 'h2' | 'h3' | 'h4'
  count?: number
  action?: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex min-w-0 items-center gap-3', className)}>
      <IconTile icon={icon} tone={tone} size="sm" />
      <Heading id={id} className="type-h3 min-w-0 flex-1 [overflow-wrap:anywhere]">
        {title}
        {count !== undefined ? (
          <span className="num ml-2 rounded-full bg-fill px-2 py-0.5 text-xs font-medium text-ink-muted">{count}</span>
        ) : null}
      </Heading>
      {action ? <div className="flex shrink-0 items-center gap-2">{action}</div> : null}
    </div>
  )
}

/** Белая панель единого стиля: граница, радиус 16, внутренние отступы как у карточки списка. */
export const PANEL = 'surface-row flex min-w-0 flex-col gap-4 p-4 md:p-5'
