import { BadgeCheck, type LucideIcon, Minus, PencilLine, Trophy, Zap } from 'lucide-react'
import type { EvidenceKind } from '@/client'
import { EVIDENCE_LABELS } from '@/content/common'
import { cn } from '@/lib/utils'

/**
 * Вид доказательства различается иконкой, типом границы и подписью — цвет лишь дублирует (E §3.3):
 *   test, pulse — сплошная граница brand-600; fsp — полоса слева fsp-red; declared — пунктир; none — без границы.
 */
const KIND_VIEW: Record<EvidenceKind, { icon: LucideIcon; chip: string; iconClass: string }> = {
  test: { icon: BadgeCheck, chip: 'border border-brand-600 bg-brand-50 text-brand-700', iconClass: 'text-brand-700' },
  pulse: { icon: Zap, chip: 'border border-brand-600 bg-brand-50 text-brand-700', iconClass: 'text-brand-700' },
  fsp: {
    icon: Trophy,
    chip: 'border border-l-[3px] border-line-strong border-l-fsp-red bg-surface text-ink',
    iconClass: 'text-fsp-red',
  },
  declared: {
    icon: PencilLine,
    chip: 'border border-dashed border-line-strong bg-surface text-ink-muted',
    iconClass: 'text-ink-muted',
  },
  none: { icon: Minus, chip: 'border border-transparent bg-fill text-ink-muted', iconClass: 'text-ink-muted' },
}

export type EvidenceChipProps = {
  kind: EvidenceKind
  /** Название навыка; без него чип показывает только вид доказательства. */
  skill?: string
  /** Подпись вида с сервера (`kind_label`); запасная — из словаря. */
  label?: string
  /** Уточнение («через смежный навык», дата): выводится рядом текстом, а не в подсказке. */
  detail?: string | null
  /** `md` (28 px) — «навык · подпись»; `sm` (24 px) — иконка и навык, подпись в aria-label и title. */
  size?: 'sm' | 'md'
  /** Показать подпись вида в чипе `md` (по умолчанию да). */
  showLabel?: boolean
  /** Кому показывается: кандидату о своём «заявлено кандидатом» звучит как «указано вами». */
  audience?: 'employer' | 'self'
  className?: string
}

/**
 * Источник факта о навыке. Чип `md` не усекается: длинное название переносит чип на новую строку целиком,
 * а если он шире контейнера — текст переносится внутри чипа. В `sm` название усекается только в контейнере
 * уже самого чипа; полное значение всегда есть в title.
 */
export function EvidenceChip({
  kind,
  skill,
  label,
  detail,
  size = 'md',
  showLabel = true,
  audience = 'employer',
  className,
}: EvidenceChipProps) {
  const view = KIND_VIEW[kind]
  const Icon = view.icon
  const kindLabel = label ?? EVIDENCE_LABELS[kind][audience]
  const fullText = skill ? `${skill} · ${kindLabel}` : kindLabel
  const labelVisible = size === 'md' && showLabel

  const chip = (
    <span
      data-slot="evidence-chip"
      data-kind={kind}
      title={labelVisible ? undefined : fullText}
      className={cn(
        'inline-flex max-w-full min-w-0 items-center gap-1.5 font-medium',
        size === 'md'
          ? 'min-h-7 rounded-[14px] px-3 py-1 text-sm leading-5'
          : 'h-6 rounded-full px-2.5 text-xs leading-4',
        view.chip,
        !detail && className,
      )}
    >
      <Icon className={cn(size === 'md' ? 'size-4' : 'size-3.5', view.iconClass)} aria-hidden="true" />
      {labelVisible ? (
        <span className="min-w-0">
          {skill ? (
            <>
              {skill}
              <span className="font-normal"> · {kindLabel}</span>
            </>
          ) : (
            kindLabel
          )}
        </span>
      ) : (
        <>
          <span className="min-w-0 truncate" title={fullText}>
            {skill ?? kindLabel}
          </span>
          {skill ? <span className="sr-only"> · {kindLabel}</span> : null}
        </>
      )}
    </span>
  )

  if (!detail) return chip
  return (
    <span className={cn('inline-flex max-w-full min-w-0 flex-wrap items-center gap-x-2 gap-y-1', className)}>
      {chip}
      <span className="type-sm min-w-0 text-ink-muted">{detail}</span>
    </span>
  )
}

export type EvidenceLegendProps = {
  /** Какие виды показать; по умолчанию три основных. */
  kinds?: readonly EvidenceKind[]
  audience?: 'employer' | 'self'
  className?: string
}

/** Легенда над списком с `sm`-чипами: чипы `md` с полными подписями в одну строку (с переносом). */
export function EvidenceLegend({
  kinds = ['test', 'fsp', 'declared'],
  audience = 'employer',
  className,
}: EvidenceLegendProps) {
  return (
    <ul
      data-slot="evidence-legend"
      aria-label="Источники сведений о навыках"
      className={cn('flex min-w-0 flex-wrap items-center gap-2', className)}
    >
      {kinds.map((kind) => (
        <li key={kind} className="max-w-full min-w-0">
          <EvidenceChip kind={kind} audience={audience} size="md" />
        </li>
      ))}
    </ul>
  )
}
