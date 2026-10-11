import {
  ArrowDown,
  ArrowUp,
  ChevronRight,
  EyeOff,
  History,
  ListChecks,
  type LucideIcon,
  Pin,
  Plane,
  Send,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
  Trophy,
  UserRoundX,
} from 'lucide-react'
import { useRef } from 'react'
import type { BankItemView, PairStateItem, ShortlistItemView } from '@/client'
import {
  CandidateCategoryChip,
  DemoChip,
  EvidenceChip,
  IconTile,
  LevelScale,
  SoftPill,
  StatusBadge,
  type Tone,
} from '@/components/app'
import { Button } from '@/components/ui/button'
import { CATEGORY_DECLARED, INVITATION_STATUS_LABELS } from '@/content/common'
import { formatDate } from '@/lib/format'
import { cn } from '@/lib/utils'
import { MATCHING } from '../content'
import { CandidateTile, FitPill } from './visuals'

const C = MATCHING.compact

/** Пометка изменения позиции относительно прежней версии: значок и тон вместо слова в серой строке. */
const DIFF_LOOK: Record<string, { icon: LucideIcon; tone: Tone }> = {
  new: { icon: Sparkles, tone: 'brand' },
  up: { icon: ArrowUp, tone: 'success' },
  down: { icon: ArrowDown, tone: 'neutral' },
}

export type MatchCardCompactProps = {
  variant: 'shortlist' | 'bank'
  item: ShortlistItemView | BankItemView
  /** Состояние пары: приходит пропом от контейнера (`usePairStates`). */
  pair?: PairStateItem | null
  onOpen: (candidateId: string) => void
  onPinToggle?: (candidateId: string, pinned: boolean) => void
  pinPending?: boolean
  /** Прогрев карточки при наведении мыши или фокусе; срабатывает один раз на кандидата. */
  onWarm?: (candidateId: string) => void
}

const INVITATION_LABELS: Record<string, string> = {
  sent: 'Приглашён',
  viewed: 'Просмотрено',
  accepted: 'Принято',
  declined: 'Отклонено',
  expired: 'Срок истёк',
  withdrawn: 'Отозвано',
  bounced: 'Условия не совпали',
}

/** Строка списка: источник каждого факта виден, процентов и баллов нет (Арх. 11.7). */
export function MatchCardCompact({
  variant,
  item,
  pair,
  onOpen,
  onPinToggle,
  pinPending,
  onWarm,
}: MatchCardCompactProps) {
  const warmed = useRef(false)
  const warm = () => {
    if (warmed.current || !onWarm) return
    warmed.current = true
    onWarm(item.candidate_id)
  }
  const isShortlist = 'position' in item
  const sItem = isShortlist ? (item as ShortlistItemView) : null
  const bItem = !isShortlist ? (item as BankItemView) : null
  const title = item.display_name?.trim() || `Кандидат ${item.public_code}`
  const evidence = sItem?.top_evidence ?? bItem?.confirmed_skills ?? []
  const more = sItem?.evidence_more ?? bItem?.confirmed_more ?? 0
  const unavailable = sItem?.unavailable_reason
  const status = pair?.invitation?.status
  const block = pair?.pair_block
  const pinned = Boolean(sItem?.pinned)

  if (unavailable === 'withdrawn') {
    return (
      <li className="flex min-w-0 items-center gap-3 rounded-md border border-dashed border-line-strong bg-surface p-4 text-ink-muted md:px-5">
        <IconTile icon={UserRoundX} tone="dashed" />
        <span className="num type-caption shrink-0">№ {sItem?.position}</span>
        <span className="type-sm min-w-0">{MATCHING.shortlist.withdrawn}</span>
      </li>
    )
  }

  const canInvite = !unavailable && !status && !block && sItem?.available !== false
  const mustTotal = sItem?.must_total ?? 0
  const mustCovered = sItem?.must_covered ?? 0
  const risk = sItem?.risk
  const mustGap = mustTotal > 0 && mustCovered < mustTotal
  const diff = sItem?.diff_mark && sItem.diff_mark !== 'same' ? DIFF_LOOK[sItem.diff_mark] : null

  return (
    <li
      className="lift-card surface-row flex min-w-0 flex-col gap-3 p-4 md:flex-row md:items-start md:gap-4 md:px-5"
      data-candidate={item.candidate_id}
      onPointerEnter={(e) => {
        if (e.pointerType === 'mouse') warm()
      }}
      onFocus={warm}
    >
      <div className="flex min-w-0 flex-1 items-start gap-3">
        <span className="relative shrink-0">
          <CandidateTile name={item.display_name} status={status} size="lg" />
          {sItem ? (
            <span className="num absolute -right-1.5 -bottom-1.5 flex h-5 min-w-5 items-center justify-center rounded-full border border-line bg-surface px-1 text-[0.6875rem] leading-none font-semibold text-ink">
              <span className="sr-only">№ </span>
              {sItem.position}
            </span>
          ) : null}
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-2.5">
          <div className="flex min-w-0 flex-col gap-1">
            <div className="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1.5">
              <button
                type="button"
                onClick={() => onOpen(item.candidate_id)}
                className="text-link tap-target type-h3 min-w-0 text-left [overflow-wrap:anywhere]"
              >
                {title}
              </button>
              {item.display_name ? <span className="num type-caption text-ink-muted">{item.public_code}</span> : null}
              {item.is_demo ? <DemoChip /> : null}
            </div>
            <div className="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1.5">
              <CandidateCategoryChip category={item.category} />
              {/* Оценка соответствия — вердикт по строке: полоса совпадения либо сила профиля. */}
              {sItem ? <FitPill band={sItem.fit_band ?? null} strength={sItem.strength_label} /> : null}
              {bItem ? <FitPill strength={bItem.strength_label} /> : null}
              {diff && sItem?.diff_mark ? (
                <SoftPill tone={diff.tone} icon={diff.icon} size="sm" className="text-xs font-medium">
                  {C.diff[sItem.diff_mark]}
                </SoftPill>
              ) : null}
            </div>
          </div>
          {/* Заявленный грейд: уровня по тесту нет, шкала не рисуется. */}
          {bItem?.level ? (
            // Вердикт стоит пилюлей ниже и в текстовой замене шкалы: заголовок над узкой шкалой не нужен.
            <LevelScale
              level={bItem.level}
              size="md"
              ownGrade={item.category.grade.code}
              showVerdict={false}
              className="max-w-80 min-w-0"
            />
          ) : bItem ? (
            <p className="type-caption min-w-0 text-ink-muted">{CATEGORY_DECLARED.card}</p>
          ) : null}
          {evidence.length > 0 ? (
            <ul className="flex min-w-0 flex-wrap gap-1.5" aria-label="Навыки и их источник">
              {evidence.slice(0, 3).map((e) => (
                <li key={e.skill.code} className="min-w-0 max-w-full">
                  <EvidenceChip kind={e.kind} skill={e.skill.title} size="sm" />
                </li>
              ))}
              {more > 0 ? (
                <li className="num type-caption self-center rounded-full bg-fill px-2 py-0.5 text-ink-muted">
                  <span className="sr-only">{C.moreEvidence} </span>+{more}
                </li>
              ) : null}
            </ul>
          ) : null}
          {mustTotal > 0 ||
          risk ||
          item.fsp_summary ||
          item.grade_margin ||
          item.stale ||
          unavailable === 'paused' ||
          bItem?.relocation_ready ? (
            <div className="flex min-w-0 flex-wrap items-center gap-1.5">
              {mustTotal > 0 ? (
                <SoftPill
                  tone={mustCovered >= mustTotal ? 'success' : 'warning'}
                  icon={ListChecks}
                  size="sm"
                  title={mustGap && risk ? risk : `${mustCovered} из ${mustTotal} ${C.must}`}
                >
                  <span className="num text-xs font-medium">
                    {mustCovered} из {mustTotal}
                  </span>
                  <span className="sr-only">
                    {' '}
                    {C.must}
                    {mustGap && risk ? `. ${risk}` : ''}
                  </span>
                </SoftPill>
              ) : null}
              {/* Риск повторяет чипы навыков: в строке — только знак, фраза целиком — в подсказке и в карточке. */}
              {risk && !mustGap ? (
                <SoftPill tone="warning" icon={TriangleAlert} size="sm" title={risk} className="gap-0">
                  <span className="sr-only">{risk}</span>
                </SoftPill>
              ) : null}
              {item.grade_margin ? (
                <SoftPill tone="success" icon={ShieldCheck} size="sm" className="text-xs">
                  {C.grade_margin}
                </SoftPill>
              ) : null}
              {item.fsp_summary ? (
                <SoftPill
                  icon={Trophy}
                  size="sm"
                  title={`ФСП: ${item.fsp_summary}`}
                  className="h-auto min-h-6 shrink bg-[color-mix(in_srgb,var(--color-fsp-red)_8%,var(--color-surface))] py-0.5 text-xs text-ink [&>svg]:shrink-0 [&>svg]:text-fsp-red"
                >
                  <span className="min-w-0 break-words">
                    <span className="sr-only">ФСП: </span>
                    {item.fsp_summary}
                  </span>
                </SoftPill>
              ) : null}
              {bItem?.relocation_ready ? (
                <SoftPill icon={Plane} size="sm" className="text-xs">
                  {C.relocation}
                </SoftPill>
              ) : null}
              {item.stale ? (
                <SoftPill tone="warning" icon={History} size="sm" className="text-xs">
                  {C.stale}
                </SoftPill>
              ) : null}
              {unavailable === 'paused' ? (
                <SoftPill icon={EyeOff} size="sm" className="text-xs">
                  {C.paused}
                </SoftPill>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
      <div className={cn('flex shrink-0 flex-wrap items-center gap-2 md:justify-end')}>
        {status ? (
          <StatusBadge
            status={status}
            label={INVITATION_STATUS_LABELS.employer[status] ?? INVITATION_LABELS[status] ?? status}
            size="sm"
            live
          />
        ) : null}
        {!status && block ? (
          <SoftPill icon={History} size="sm" className="text-xs">
            {block.code === 'conditions_mismatch' ? C.mismatch : C.again} ·{' '}
            <span className="num">{formatDate(block.until)}</span>
          </SoftPill>
        ) : null}
        {variant === 'shortlist' && onPinToggle && !unavailable ? (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-pressed={pinned}
            aria-label={pinned ? MATCHING.shortlist.unpin : MATCHING.shortlist.pin}
            title={pinned ? MATCHING.shortlist.unpin : MATCHING.shortlist.pin}
            disabled={pinPending}
            className={cn(pinned && 'bg-brand-50 text-brand-700')}
            onClick={() => onPinToggle(item.candidate_id, pinned)}
          >
            <Pin className={cn(pinned && 'fill-current')} aria-hidden="true" />
          </Button>
        ) : null}
        <Button type="button" variant="secondary" size="sm" onClick={() => onOpen(item.candidate_id)}>
          {canInvite ? <Send aria-hidden="true" /> : null}
          {canInvite ? C.invite : C.open}
          {canInvite ? null : <ChevronRight aria-hidden="true" />}
        </Button>
      </div>
    </li>
  )
}
