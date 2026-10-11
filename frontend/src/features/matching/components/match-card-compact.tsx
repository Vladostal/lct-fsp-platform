import { Pin, TriangleAlert } from 'lucide-react'
import { useRef } from 'react'
import type { BankItemView, PairStateItem, ShortlistItemView } from '@/client'
import { CandidateCategoryChip, DemoChip, EvidenceChip, FitBadge, LevelScale, StatusBadge } from '@/components/app'
import { Button } from '@/components/ui/button'
import { CATEGORY_DECLARED, INVITATION_STATUS_LABELS } from '@/content/common'
import { formatDate } from '@/lib/format'
import { cn } from '@/lib/utils'
import { MATCHING } from '../content'

const C = MATCHING.compact

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
      <li className="surface-row flex min-w-0 items-center gap-3 p-4 text-ink-muted md:px-5">
        <span className="num type-caption shrink-0">№ {sItem?.position}</span>
        <span className="type-sm min-w-0">{MATCHING.shortlist.withdrawn}</span>
      </li>
    )
  }

  const canInvite = !unavailable && !status && !block && sItem?.available !== false

  return (
    <li
      className="surface-row flex min-w-0 flex-col gap-3 p-4 transition-colors hover:border-line-strong md:flex-row md:items-start md:gap-4 md:px-5"
      data-candidate={item.candidate_id}
      onPointerEnter={(e) => {
        if (e.pointerType === 'mouse') warm()
      }}
      onFocus={warm}
    >
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1.5">
          <button
            type="button"
            onClick={() => onOpen(item.candidate_id)}
            className="text-link type-h3 min-w-0 text-left [overflow-wrap:anywhere]"
          >
            {title}
          </button>
          {item.display_name ? <span className="num type-caption text-ink-muted">{item.public_code}</span> : null}
          <CandidateCategoryChip category={item.category} />
          {/* Оценка соответствия стоит рядом со статусом справа по смыслу: это вердикт по строке */}
          {sItem ? <FitBadge band={sItem.fit_band ?? null} strength={sItem.strength_label} size="sm" /> : null}
          {bItem ? <FitBadge band={null} strength={bItem.strength_label} size="sm" /> : null}
        </div>
        {/* Заявленный грейд: уровня по тесту нет, шкала не рисуется. */}
        {bItem?.level ? (
          <LevelScale level={bItem.level} size="sm" ownGrade={item.category.grade.code} />
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
              <li className="type-caption self-center text-ink-muted">
                {C.moreEvidence} {more}
              </li>
            ) : null}
          </ul>
        ) : null}
        <p className="type-caption flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-ink-muted">
          {sItem ? <span className="num">№ {sItem.position}</span> : null}
          {item.is_demo ? <DemoChip /> : null}
          {sItem?.diff_mark && sItem.diff_mark !== 'same' ? <span>{C.diff[sItem.diff_mark]}</span> : null}
          {sItem?.must_total ? (
            <span>
              <span className="num">
                {sItem.must_covered ?? 0} из {sItem.must_total}
              </span>{' '}
              {C.must}
            </span>
          ) : null}
          {item.fsp_summary ? <span className="min-w-0 break-words">ФСП: {item.fsp_summary}</span> : null}
          {item.grade_margin ? <span>{C.grade_margin}</span> : null}
          {item.stale ? <span>{C.stale}</span> : null}
          {unavailable === 'paused' ? <span>{C.paused}</span> : null}
          {bItem?.relocation_ready ? <span>{C.relocation}</span> : null}
        </p>
        {sItem?.risk ? (
          <p className="type-sm flex min-w-0 items-start gap-1.5 text-warning">
            <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            <span className="min-w-0 break-words">{sItem.risk}</span>
          </p>
        ) : null}
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
          <span className="type-sm text-ink-muted">
            {block.code === 'conditions_mismatch' ? C.mismatch : C.again} · {formatDate(block.until)}
          </span>
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
            onClick={() => onPinToggle(item.candidate_id, pinned)}
          >
            <Pin className={cn(pinned && 'fill-current')} aria-hidden="true" />
          </Button>
        ) : null}
        <Button type="button" variant="secondary" size="sm" onClick={() => onOpen(item.candidate_id)}>
          {canInvite ? C.invite : C.open}
        </Button>
      </div>
    </li>
  )
}
