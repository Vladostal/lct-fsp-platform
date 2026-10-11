import { Link } from '@tanstack/react-router'
import {
  BadgeCheck,
  Briefcase,
  ChevronDown,
  CircleDashed,
  Gauge,
  ListChecks,
  ListOrdered,
  Lock,
  LockOpen,
  type LucideIcon,
  MapPin,
  PenLine,
  Pin,
  Scale,
  Star,
  TriangleAlert,
  Trophy,
  UserRound,
  Wrench,
} from 'lucide-react'
import type { CandidateCardEmployerView, EvidenceItem, PairStateItem } from '@/client'
import {
  CandidateCategoryChip,
  ContributionBars,
  DemoChip,
  EvidenceChip,
  IconTile,
  LevelScale,
  RevealOnce,
  SoftPill,
  StatusBadge,
  type TileTone,
} from '@/components/app'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { CATEGORY_DECLARED, INVITATION_STATUS_LABELS, STRENGTH_LABELS } from '@/content/common'
import { formatDate, formatYears } from '@/lib/format'
import { cn } from '@/lib/utils'
import { MATCHING } from '../content'
import { CandidateTile, FitPill, FORMAT_ICON, PanelHead } from './visuals'

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

/** Блок карточки: белая панель с плиткой-заголовком. В боковой панели и на странице выглядит одинаково. */
function Block({
  icon,
  tone,
  title,
  children,
  className,
}: {
  icon: LucideIcon
  tone?: TileTone
  title: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <section className={cn('surface-row flex min-w-0 flex-col gap-3 p-4', className)}>
      <PanelHead icon={icon} tone={tone} title={title} as="h3" />
      {children}
    </section>
  )
}

/** Лестница решения: те же величины и в том же порядке, что и в ранжировании (обязательные → подтверждённое → сила). */
function RankLadder({ match, strength }: { match: NonNullable<CandidateCardEmployerView['match']>; strength: string }) {
  const c = match.coverage
  const rungs: { label: string; value: string; ratio: number; bar: string }[] = []
  if (c.must_total > 0) {
    rungs.push({
      label: 'Обязательные навыки закрыты',
      value: `${c.must_covered} из ${c.must_total}`,
      ratio: c.must_covered / c.must_total,
      bar: 'bg-brand-600',
    })
    rungs.push({
      label: 'Из них подтверждено',
      value: `${c.must_confirmed} из ${c.must_total}`,
      ratio: c.must_confirmed / c.must_total,
      bar: 'bg-success',
    })
  }
  const strengthRatio = strength === 'high' ? 1 : strength === 'medium' ? 0.66 : 0.33
  rungs.push({
    label: 'Сила профиля',
    value: STRENGTH_LABELS[strength as 'high'],
    ratio: strengthRatio,
    bar: 'bg-brand-900 dark:bg-brand-700',
  })
  return (
    <ol className="flex min-w-0 flex-col gap-2" aria-label="Порядок ранжирования">
      {rungs.map((r, i) => (
        <li
          key={r.label}
          style={{ '--i': i } as React.CSSProperties}
          className="stagger animate-rise-in flex min-w-0 items-center gap-3 rounded-md bg-fill p-2.5"
        >
          <span
            aria-hidden="true"
            className="num flex size-7 shrink-0 items-center justify-center rounded-md bg-surface text-sm font-semibold text-brand-700"
          >
            {i + 1}
          </span>
          <span className="flex min-w-0 flex-1 flex-col gap-1.5">
            <span className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-3">
              <span className="type-sm min-w-0 break-words">
                <span className="sr-only">{i + 1}. </span>
                {r.label}
              </span>
              <span className="num type-sm font-semibold text-ink">{r.value}</span>
            </span>
            <span aria-hidden="true" className="h-1.5 overflow-hidden rounded-full bg-surface">
              <span
                className={cn('animate-grow-x block h-full origin-left rounded-full', r.bar)}
                style={{ width: `${Math.round(r.ratio * 100)}%` }}
              />
            </span>
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
      <h4 className="type-eyebrow">
        {title} <span className="num ml-1">{items.length}</span>
      </h4>
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
/** Числовые даты в доводах сервера («07.08.2026») — тем же видом, что остальные даты экрана: «7 авг.». */
function humanDates(text: string): string {
  return text.replace(/\b(\d{2})\.(\d{2})\.(\d{4})\b/g, (_, d, m, y) =>
    formatDate(new Date(Number(y), Number(m) - 1, Number(d))),
  )
}

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
  const fspEmpty = card.fsp.mode === 'none' || !card.fsp.mode

  return (
    <article className="flex min-w-0 flex-col gap-3" aria-label={title}>
      <header className="accent-card surface-row flex min-w-0 flex-col gap-3 p-4">
        <div className="flex min-w-0 items-start gap-3">
          <CandidateTile name={card.display_name} status={pair?.invitation?.status} size="xl" />
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <div className="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1">
              <h2 className="type-h2 min-w-0 [overflow-wrap:anywhere]">{title}</h2>
              {card.display_name ? <span className="num type-caption text-ink-muted">{card.public_code}</span> : null}
              {card.is_demo ? <DemoChip /> : null}
            </div>
            <CandidateCategoryChip category={card.category} />
          </div>
          {needContext && onPinToggle ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              aria-pressed={Boolean(card.pinned)}
              onClick={onPinToggle}
              className={cn('relative z-10 shrink-0', card.pinned && 'bg-brand-50 text-brand-700')}
            >
              <Pin className={card.pinned ? 'fill-current' : undefined} aria-hidden="true" />
              <span className="max-[479px]:sr-only">
                {card.pinned ? MATCHING.shortlist.unpin : MATCHING.shortlist.pin}
              </span>
            </Button>
          ) : null}
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <FitPill band={m?.fit_band} strength={card.strength.label} />
          {m?.fit_band ? <FitPill strength={card.strength.label} /> : null}
          {m?.position ? (
            <SoftPill icon={ListOrdered} size="sm" className="text-xs">
              <span className="num">
                № {m.position} {T.position}
              </span>
            </SoftPill>
          ) : null}
          {needContext && m && !m.in_snapshot ? (
            <SoftPill icon={CircleDashed} size="sm" className="text-xs">
              {T.outsideSnapshot}
            </SoftPill>
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
        <Block icon={ListOrdered} tone="brand" title={T.why}>
          <RankLadder match={m} strength={card.strength.label} />
          {m.reasons.length > 0 ? (
            <ul className="flex min-w-0 flex-col gap-1.5">
              {m.reasons.slice(0, 3).map((r) => (
                <li key={r.code} className="type-sm flex min-w-0 items-start gap-2 break-words">
                  <BadgeCheck className="mt-0.5 size-4 shrink-0 text-success" aria-hidden="true" />
                  <span className="min-w-0">{humanDates(r.text)}</span>
                </li>
              ))}
            </ul>
          ) : null}
          {m.risk ? (
            <p className="type-sm flex min-w-0 items-start gap-1.5 rounded-md bg-warning-bg px-2.5 py-1.5 text-warning">
              <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              <span className="min-w-0 break-words">{m.risk.text}</span>
            </p>
          ) : null}
          <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1.5">
            {m.formats_common.length > 0 ? (
              <span className="flex min-w-0 flex-wrap items-center gap-1.5">
                <span className="sr-only">{T.formatsCommon}: </span>
                {m.formats_common.slice(0, 3).map((f) => (
                  <SoftPill key={f} tone="success" icon={FORMAT_ICON[f]} size="sm" title={T.formatsCommon}>
                    <span className="text-xs">{FORMAT_LABELS[f]}</span>
                  </SoftPill>
                ))}
              </span>
            ) : null}
            <p className="type-caption min-w-0 text-ink-muted">{T.salaryLater}</p>
          </div>
        </Block>
      ) : null}

      {m && m.requirements.length > 0 ? (
        <Block icon={ListChecks} title={T.requirements}>
          <ul className="flex min-w-0 flex-col divide-y divide-line">
            {m.requirements.map((r) => (
              <li
                key={r.skill.code}
                className="flex min-w-0 flex-wrap items-center justify-between gap-x-3 gap-y-1.5 py-2 first:pt-0 last:pb-0"
              >
                <span className="flex min-w-0 items-center gap-2">
                  {r.priority === 'must' ? (
                    <Star className="size-4 shrink-0 fill-current text-brand-600" aria-hidden="true" />
                  ) : (
                    <span aria-hidden="true" className="size-4 shrink-0" />
                  )}
                  <span className="min-w-0 break-words font-medium">{r.skill.title}</span>
                  {r.priority === 'must' ? <span className="type-caption text-ink-muted">{T.required}</span> : null}
                </span>
                <EvidenceChip
                  kind={r.kind}
                  size="sm"
                  label={r.kind === 'none' ? T.noData : undefined}
                  // Пояснение, слово в слово повторяющее подпись чипа, не выводится.
                  detail={
                    r.via_skill
                      ? `${T.via} ${r.via_skill.title}`
                      : r.detail && r.detail.toLowerCase() !== r.kind_label?.toLowerCase()
                        ? r.detail
                        : undefined
                  }
                />
              </li>
            ))}
          </ul>
        </Block>
      ) : null}

      <Block icon={Gauge} tone={card.level ? 'brand' : 'dashed'} title={T.level}>
        {card.level ? (
          <>
            <LevelScale level={card.level} size="md" ownGrade={card.category.grade.code} />
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <SoftPill size="sm" className="text-xs">
                Тест <span className="num">{formatDate(card.level.tested_at)}</span>
              </SoftPill>
              {card.level.stale ? (
                <SoftPill tone="warning" size="sm" className="text-xs">
                  {T.stale}
                </SoftPill>
              ) : null}
            </div>
          </>
        ) : (
          <div className="flex min-w-0 flex-col gap-1 rounded-md border border-dashed border-line-strong p-3">
            <p className="type-body min-w-0 font-medium">{CATEGORY_DECLARED.card}</p>
            <p className="type-sm min-w-0 text-ink-muted">{T.levelDeclared}</p>
          </div>
        )}
      </Block>

      <Collapsible className="surface-row min-w-0 px-4">
        <CollapsibleTrigger className="tap-target group flex min-h-16 w-full min-w-0 items-center gap-3 text-left">
          <IconTile icon={Scale} tone="soft" size="sm" />
          <span className="type-h3 min-w-0 flex-1">{T.contribution}</span>
          <ChevronDown
            className="size-5 shrink-0 text-ink-muted transition-transform group-data-[state=open]:rotate-180"
            aria-hidden="true"
          />
        </CollapsibleTrigger>
        <CollapsibleContent className="flex min-w-0 flex-col gap-4 pb-4">
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
              {T.strength}: {STRENGTH_LABELS[card.strength.label]}
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
        <Block icon={Wrench} title={T.skills}>
          <SkillGroup title={T.skillsTest} items={skillsTest} />
          <SkillGroup title={T.skillsOther} items={skillsOther} />
          <SkillGroup title={T.skillsDeclared} items={skillsDeclared} />
        </Block>
      ) : null}

      <Block icon={Trophy} tone={fspEmpty ? 'dashed' : 'accent'} title={T.fsp}>
        {fspEmpty ? (
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
              <li key={a.id} className="flex min-w-0 flex-col gap-1.5 rounded-md bg-fill p-2.5">
                <span className="type-sm min-w-0 break-words font-medium">{a.competition_title}</span>
                <span className="flex min-w-0 flex-wrap gap-1.5">
                  <SoftPill size="sm" icon={Trophy} className="bg-surface text-xs text-ink [&>svg]:text-fsp-red">
                    {a.place_label}
                  </SoftPill>
                  <SoftPill size="sm" className="bg-surface text-xs">
                    {a.level_label}
                  </SoftPill>
                  <SoftPill size="sm" className="bg-surface text-xs">
                    {a.role_label}
                  </SoftPill>
                </span>
              </li>
            ))}
            {(card.fsp.credentials ?? []).map((c) => (
              <li key={c.id} className="type-sm min-w-0 break-words rounded-md bg-fill p-2.5">
                {c.label}
              </li>
            ))}
            {card.fsp.leadership ? (
              <li className="type-sm rounded-md bg-fill p-2.5">{card.fsp.leadership.label}</li>
            ) : null}
          </ul>
        )}
        {card.fsp.source ? (
          <p className="type-caption text-ink-muted">
            {card.fsp.source.label}, проверено {formatDate(card.fsp.source.checked_at)}
          </p>
        ) : null}
      </Block>

      {hasDeclared && declared ? (
        <Block icon={PenLine} tone="dashed" title={T.declared}>
          <dl className="flex min-w-0 flex-wrap gap-2">
            {declared.city ? (
              <div className="flex min-w-0 max-w-full items-center gap-2 rounded-md bg-fill px-2.5 py-1.5">
                <MapPin className="size-4 shrink-0 text-ink-muted" aria-hidden="true" />
                <dt className="sr-only">Город</dt>
                <dd className="type-sm min-w-0 break-words">{declared.city}</dd>
              </div>
            ) : null}
            {declared.experience_years != null ? (
              <div className="flex min-w-0 max-w-full items-center gap-2 rounded-md bg-fill px-2.5 py-1.5">
                <Briefcase className="size-4 shrink-0 text-ink-muted" aria-hidden="true" />
                <dt className="type-sm text-ink-muted">Стаж</dt>
                <dd className="num type-sm font-medium">{formatYears(declared.experience_years)}</dd>
              </div>
            ) : null}
            {(declared.roles?.length ?? 0) > 0 ? (
              <div className="flex min-w-0 max-w-full items-center gap-2 rounded-md bg-fill px-2.5 py-1.5">
                <UserRound className="size-4 shrink-0 text-ink-muted" aria-hidden="true" />
                <dt className="sr-only">Роли</dt>
                <dd className="type-sm min-w-0 break-words">{declared.roles?.map((r) => r.title).join(', ')}</dd>
              </div>
            ) : null}
          </dl>
          {declared.about ? (
            <p className="type-body min-w-0 whitespace-pre-line break-words">{declared.about}</p>
          ) : null}
        </Block>
      ) : null}

      <div id="candidate-contacts" className="min-w-0">
        <Block icon={card.disclosed ? LockOpen : Lock} tone={card.disclosed ? 'success' : 'neutral'} title={T.contacts}>
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
            <p className="type-sm min-w-0 text-ink-muted">{T.contactsLocked}</p>
          )}
        </Block>
      </div>
    </article>
  )
}
