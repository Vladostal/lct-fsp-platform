import { Link } from '@tanstack/react-router'
import { ChevronDown, Lock, LockOpen, Pin, TriangleAlert } from 'lucide-react'
import type { CandidateCardEmployerView, EvidenceItem, PairStateItem } from '@/client'
import {
  CandidateCategoryChip,
  ContributionBars,
  DemoChip,
  EvidenceChip,
  FitBadge,
  LevelScale,
  RevealOnce,
  Section,
  StatusBadge,
} from '@/components/app'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { CATEGORY_DECLARED, INVITATION_STATUS_LABELS } from '@/content/common'
import { formatDate, formatList, formatYears } from '@/lib/format'
import { MATCHING } from '../content'

const T = MATCHING.card
const FORMAT_LABELS = MATCHING.form.formats_

export type MatchCardDetailedProps = {
  audience?: 'employer'
  card: CandidateCardEmployerView
  pair?: PairStateItem | null
  /** Контекст потребности: показывает позицию и закрепление. */
  needContext?: { needId: string; snapshotId?: string } | null
  onPinToggle?: () => void
  contacts?: React.ReactNode
}

/** Лестница решения: те же величины и в том же порядке, что и в ранжировании (обязательные → подтверждённое → сила). */
function RankLadder({ match, strength }: { match: NonNullable<CandidateCardEmployerView['match']>; strength: string }) {
  const c = match.coverage
  const rungs: { label: string; value: string; ratio: number }[] = []
  if (c.must_total > 0) {
    rungs.push({
      label: 'Обязательные навыки закрыты',
      value: `${c.must_covered} из ${c.must_total}`,
      ratio: c.must_covered / c.must_total,
    })
    rungs.push({
      label: 'Из них подтверждено',
      value: `${c.must_confirmed} из ${c.must_total}`,
      ratio: c.must_confirmed / c.must_total,
    })
  }
  const strengthRatio = strength === 'high' ? 1 : strength === 'medium' ? 0.66 : 0.33
  rungs.push({ label: 'Сила профиля', value: MATCHING.compact.strength[strength as 'high'], ratio: strengthRatio })
  return (
    <ol className="flex min-w-0 flex-col gap-2" aria-label="Порядок ранжирования">
      {rungs.map((r, i) => (
        <li
          key={r.label}
          style={{ '--i': i } as React.CSSProperties}
          className="stagger animate-rise-in grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1"
        >
          <span className="type-sm min-w-0 break-words">
            <span className="num mr-2 text-ink-subtle">{i + 1}</span>
            {r.label}
          </span>
          <span className="num type-sm text-ink-muted">{r.value}</span>
          <span aria-hidden="true" className="col-span-2 h-1 overflow-hidden rounded-full bg-fill">
            <span
              className="animate-grow-x block h-full origin-left rounded-full bg-brand-600"
              style={{ width: `${Math.round(r.ratio * 100)}%` }}
            />
          </span>
        </li>
      ))}
    </ol>
  )
}

function SkillGroup({ title, items }: { title: string; items: EvidenceItem[] }) {
  if (items.length === 0) return null
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <h4 className="type-sm font-medium">{title}</h4>
      <ul className="flex min-w-0 flex-wrap gap-1.5">
        {items.map((s) => (
          <li key={s.skill.code} className="min-w-0 max-w-full">
            <EvidenceChip kind={s.kind} skill={s.skill.title} size="md" showLabel={false} />
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Карточка кандидата: чем подтверждён каждый факт, что неизвестно, что откроется после согласия. */
export function MatchCardDetailed({ card, pair, needContext, onPinToggle, contacts }: MatchCardDetailedProps) {
  const m = card.match
  const title = card.display_name?.trim() || `${T.candidate} ${card.public_code}`
  const skillsTest = card.skills.filter((s) => s.kind === 'test')
  const skillsOther = card.skills.filter((s) => s.kind === 'pulse' || s.kind === 'fsp')
  const skillsDeclared = card.skills.filter((s) => s.kind === 'declared')
  const declared = card.declared
  const hasDeclared =
    declared &&
    (declared.city || declared.experience_years != null || declared.about || (declared.roles?.length ?? 0) > 0)

  return (
    <article className="flex min-w-0 flex-col gap-5" aria-label={title}>
      <header className="flex min-w-0 flex-col gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
          <h2 className="type-h2 min-w-0 [overflow-wrap:anywhere]">{title}</h2>
          {card.display_name ? <span className="num type-caption text-ink-muted">{card.public_code}</span> : null}
          {card.is_demo ? <DemoChip /> : null}
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <CandidateCategoryChip category={card.category} />
          {m ? <FitBadge band={m.fit_band} strength={card.strength.label} size="sm" /> : null}
          {m?.position ? (
            <span className="type-sm text-ink-muted num">
              № {m.position} {T.position}
            </span>
          ) : null}
          {needContext && m && !m.in_snapshot ? (
            <span className="type-sm text-ink-muted">{T.outsideSnapshot}</span>
          ) : null}
          {needContext && onPinToggle ? (
            <Button type="button" variant="ghost" size="sm" aria-pressed={Boolean(card.pinned)} onClick={onPinToggle}>
              <Pin className={card.pinned ? 'fill-current' : undefined} aria-hidden="true" />
              {card.pinned ? MATCHING.shortlist.unpin : MATCHING.shortlist.pin}
            </Button>
          ) : null}
          {pair?.invitation ? (
            <StatusBadge
              status={pair.invitation.status}
              label={INVITATION_STATUS_LABELS.employer[pair.invitation.status] ?? pair.invitation.status}
              size="sm"
              live
            />
          ) : null}
        </div>
      </header>

      {m ? (
        <Section title={T.why}>
          <RankLadder match={m} strength={card.strength.label} />
          {m.reasons.length > 0 ? (
            <ul className="flex min-w-0 flex-col gap-2">
              {m.reasons.slice(0, 3).map((r) => (
                <li key={r.code} className="type-body min-w-0 break-words">
                  {r.text}
                </li>
              ))}
            </ul>
          ) : null}
          {m.risk ? (
            <p className="type-sm flex min-w-0 items-start gap-1.5 text-warning">
              <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              <span className="min-w-0 break-words">{m.risk.text}</span>
            </p>
          ) : null}
          <p className="type-sm text-ink-muted">
            {m.formats_common.length > 0
              ? `${T.formatsCommon}: ${formatList(
                  m.formats_common.map((f) => FORMAT_LABELS[f]),
                  3,
                )}. `
              : ''}
            {T.salaryLater}
          </p>
        </Section>
      ) : null}

      {m && m.requirements.length > 0 ? (
        <Section title={T.requirements}>
          <ul className="flex min-w-0 flex-col gap-2">
            {m.requirements.map((r) => (
              <li key={r.skill.code} className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                <span className="min-w-0 break-words font-medium">{r.skill.title}</span>
                {r.priority === 'must' ? <span className="type-caption text-ink-muted">{T.required}</span> : null}
                <EvidenceChip
                  kind={r.kind}
                  size="sm"
                  label={r.kind === 'none' ? T.noData : undefined}
                  detail={r.via_skill ? `${T.via} ${r.via_skill.title}` : r.detail}
                />
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      <Section title={T.level}>
        {card.level ? (
          <>
            <LevelScale level={card.level} size="md" ownGrade={card.category.grade.code} />
            <p className="type-sm text-ink-muted">
              Тест {formatDate(card.level.tested_at)}
              {card.level.stale ? <span className="ml-2 text-warning">{T.stale}</span> : null}
            </p>
          </>
        ) : (
          <>
            <p className="type-body min-w-0">{CATEGORY_DECLARED.card}</p>
            <p className="type-sm min-w-0 text-ink-muted">{T.levelDeclared}</p>
          </>
        )}
      </Section>

      <Collapsible className="min-w-0">
        <CollapsibleTrigger className="tap-target group flex w-full min-w-0 items-center justify-between gap-2 text-left type-eyebrow">
          {T.contribution}
          <ChevronDown
            className="size-5 shrink-0 transition-transform group-data-[state=open]:rotate-180"
            aria-hidden="true"
          />
        </CollapsibleTrigger>
        <CollapsibleContent className="flex min-w-0 flex-col gap-4 pt-3">
          {m && m.coverage.pct != null ? (
            <div className="flex min-w-0 flex-col gap-2">
              <p className="type-sm font-medium">
                {T.coverage}: <span className="num">{m.coverage.pct} %</span>
              </p>
              <ContributionBars items={m.contributions.filter((c) => c.group === 'coverage')} />
            </div>
          ) : null}
          <div className="flex min-w-0 flex-col gap-2">
            <p className="type-sm font-medium">
              {T.strength}: {MATCHING.compact.strength[card.strength.label]}
            </p>
            <ContributionBars items={card.strength.contributions} summary />
          </div>
          {m ? <p className="num type-caption text-ink-muted">{m.scorer_version}</p> : null}
          <Link to="/how-it-works" hash="matching" className="text-link tap-target type-sm w-fit">
            {T.calc}
          </Link>
        </CollapsibleContent>
      </Collapsible>

      {card.skills.length > 0 ? (
        <Section title={T.skills}>
          <SkillGroup title={T.skillsTest} items={skillsTest} />
          <SkillGroup title={T.skillsOther} items={skillsOther} />
          <SkillGroup title={T.skillsDeclared} items={skillsDeclared} />
        </Section>
      ) : null}

      <Section title={T.fsp}>
        {card.fsp.mode === 'none' || !card.fsp.mode ? (
          <p className="type-sm text-ink-muted">
            {card.fsp.neutral_text ?? 'Достижений ФСП нет или кандидат их не открыл.'}
          </p>
        ) : card.fsp.mode === 'summary' && card.fsp.summary ? (
          <div className="flex min-w-0 flex-col gap-1">
            <p className="type-body min-w-0 break-words font-medium">{card.fsp.summary.headline}</p>
            {card.fsp.summary.more ? <p className="type-sm text-ink-muted">и другие результаты</p> : null}
            {card.fsp.note ? <p className="type-sm text-ink-muted">{card.fsp.note}</p> : null}
          </div>
        ) : (
          <ul className="flex min-w-0 flex-col gap-2">
            {(card.fsp.achievements ?? []).map((a) => (
              <li key={a.id} className="type-sm min-w-0 break-words">
                <span className="font-medium">{a.competition_title}</span> · {a.place_label} · {a.level_label} ·{' '}
                {a.role_label}
              </li>
            ))}
            {(card.fsp.credentials ?? []).map((c) => (
              <li key={c.id} className="type-sm min-w-0 break-words">
                {c.label}
              </li>
            ))}
            {card.fsp.leadership ? <li className="type-sm">{card.fsp.leadership.label}</li> : null}
          </ul>
        )}
        {card.fsp.source ? (
          <p className="type-caption text-ink-muted">
            {card.fsp.source.label}, проверено {formatDate(card.fsp.source.checked_at)}
          </p>
        ) : null}
      </Section>

      {hasDeclared && declared ? (
        <Section title={T.declared}>
          <dl className="type-sm grid min-w-0 grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1">
            {declared.city ? (
              <>
                <dt className="text-ink-muted">Город</dt>
                <dd className="min-w-0 break-words">{declared.city}</dd>
              </>
            ) : null}
            {declared.experience_years != null ? (
              <>
                <dt className="text-ink-muted">Стаж</dt>
                <dd>{formatYears(declared.experience_years)}</dd>
              </>
            ) : null}
            {(declared.roles?.length ?? 0) > 0 ? (
              <>
                <dt className="text-ink-muted">Роли</dt>
                <dd className="min-w-0 break-words">{declared.roles?.map((r) => r.title).join(', ')}</dd>
              </>
            ) : null}
          </dl>
          {declared.about ? (
            <p className="type-body min-w-0 whitespace-pre-line break-words">{declared.about}</p>
          ) : null}
        </Section>
      ) : null}

      <div id="candidate-contacts" className="min-w-0">
        <Section title={T.contacts}>
          {card.disclosed ? (
            <RevealOnce
              storageKey={`contacts-revealed:${card.candidate_id}`}
              className="flex min-w-0 flex-col gap-3 p-3 -m-3"
            >
              <p className="type-caption flex min-w-0 items-center gap-2 text-ink-muted">
                <LockOpen className="animate-pop-in size-4 shrink-0 text-success" aria-hidden="true" />
                открыто после согласия кандидата
              </p>
              {contacts ?? <p className="type-sm text-ink-muted">{T.contactsOpen}</p>}
            </RevealOnce>
          ) : (
            <p className="type-sm flex min-w-0 items-start gap-2 text-ink-muted">
              <Lock className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              <span className="min-w-0">{T.contactsLocked}</span>
            </p>
          )}
        </Section>
      </div>
    </article>
  )
}
