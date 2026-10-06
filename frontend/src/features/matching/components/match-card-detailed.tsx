import { Link } from '@tanstack/react-router'
import { ChevronDown, Lock, Pin, TriangleAlert } from 'lucide-react'
import type { CandidateCardEmployerView, EvidenceItem, PairStateItem } from '@/client'
import {
  CategoryChip,
  ContributionBars,
  DemoChip,
  EvidenceChip,
  FitBadge,
  LevelScale,
  StatusBadge,
} from '@/components/app'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { formatDate, formatList } from '@/lib/format'
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

function Section({ title, children, id }: { title: string; children: React.ReactNode; id?: string }) {
  return (
    <section id={id} className="flex min-w-0 flex-col gap-3 border-t border-line pt-4 first:border-t-0 first:pt-0">
      <h3 className="type-h3">{title}</h3>
      {children}
    </section>
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
          <CategoryChip title={card.category.title} />
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
            <StatusBadge status={pair.invitation.status} label={pair.invitation.status} size="sm" live />
          ) : null}
        </div>
      </header>

      {m ? (
        <Section title={T.why}>
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
                <span className="type-caption text-ink-muted">{r.priority === 'must' ? T.required : T.desirable}</span>
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
        <LevelScale level={card.level} size="md" ownGrade={card.category.grade.code} />
        <p className="type-sm text-ink-muted">
          Тест {formatDate(card.level.tested_at)}
          {card.level.stale ? <span className="ml-2 rounded-full bg-fill px-2 py-0.5">{T.stale}</span> : null}
        </p>
      </Section>

      <Collapsible className="min-w-0 border-t border-line pt-4">
        <CollapsibleTrigger className="tap-target group flex w-full min-w-0 items-center justify-between gap-2 text-left type-h3">
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
            <ContributionBars items={card.strength.contributions} />
          </div>
          {m ? <p className="num type-caption text-ink-muted">{m.scorer_version}</p> : null}
          <Link to="/how-it-works" hash="matching" className="text-link type-sm">
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
            Источник: {card.fsp.source.label}, проверено {formatDate(card.fsp.source.checked_at)}
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
                <dd>{declared.experience_years} лет</dd>
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

      <Section title={T.contacts} id="candidate-contacts">
        {card.disclosed ? (
          (contacts ?? <p className="type-sm text-ink-muted">{T.contactsOpen}</p>)
        ) : (
          <p className="type-sm flex min-w-0 items-start gap-2 text-ink-muted">
            <Lock className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            <span className="min-w-0">{T.contactsLocked}</span>
          </p>
        )}
      </Section>
    </article>
  )
}
