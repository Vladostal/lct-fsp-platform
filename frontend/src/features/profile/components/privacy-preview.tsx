import { useQuery } from '@tanstack/react-query'
import { Briefcase, Lock, LockOpen, MapPin, PencilLine, Plane, ScanEye, Trophy, UserRound } from 'lucide-react'
import { useState } from 'react'
import type { CandidateCardEmployerView, EvidenceKind } from '@/client'
import {
  CandidateCategoryChip,
  EmptyState,
  ErrorState,
  EvidenceChip,
  EvidenceLegend,
  FormatPill,
  IconTile,
  LevelScale,
  SoftPill,
} from '@/components/app'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { CATEGORY_DECLARED } from '@/content/common'
import { hasCode } from '@/lib/api'
import { formatYears } from '@/lib/format'
import { cn } from '@/lib/utils'
import { previewQuery } from '../api'
import { PRIVACY } from '../content'

type PreviewState = 'before' | 'after'

const EVIDENCE_ORDER: readonly EvidenceKind[] = ['test', 'pulse', 'fsp', 'declared', 'none']
/** Пилюля с произвольным текстом (город, роль, свой навык): длинное значение переносится, а не вылезает. */
const WRAP_PILL = 'h-auto min-h-7 shrink rounded-xl py-0.5 [overflow-wrap:anywhere] [&>svg]:shrink-0'
const FACT_LABEL = 'type-caption font-semibold tracking-wide text-ink-muted uppercase'

const nameInitials = (name: string) =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0]?.toUpperCase() ?? '')
    .join('')

/**
 * Локальная замена `MatchCardDetailed audience="preview"` (F50): карточка кандидата глазами работодателя.
 * Показывает только то, что вернул сервер: «О себе» и имя приходят лишь в состоянии «после согласия».
 */
function PreviewCard({ card, state }: { card: CandidateCardEmployerView; state: PreviewState }) {
  const declared = card.declared
  const fspText = card.fsp.summary?.headline ?? card.fsp.neutral_text ?? null
  const kinds = EVIDENCE_ORDER.filter((kind) => card.skills.some((item) => item.kind === kind))
  const after = state === 'after'
  return (
    <article
      className="accent-card surface-row flex min-w-0 animate-rise-in flex-col gap-4 p-4 md:p-5"
      aria-label={PRIVACY.preview.title}
    >
      <header className="flex min-w-0 items-start gap-3">
        <IconTile icon={card.display_name ? undefined : UserRound} tone={after ? 'success' : 'solid'} size="lg">
          {card.display_name ? nameInitials(card.display_name) : null}
        </IconTile>
        <div className="flex min-w-0 flex-1 flex-col items-start gap-1">
          <h3 className="type-h2 min-w-0 [overflow-wrap:anywhere]">
            {card.display_name ?? <span className="num">{card.public_code}</span>}
          </h3>
          {card.display_name ? <span className="num type-caption text-ink-muted">{card.public_code}</span> : null}
          <CandidateCategoryChip category={card.category} />
        </div>
      </header>
      {card.level ? (
        <LevelScale level={card.level} ownGrade={card.category.grade.code} size="sm" />
      ) : (
        <p className="type-sm min-w-0 text-ink-muted">{CATEGORY_DECLARED.card}</p>
      )}
      <ul className="flex min-w-0 flex-wrap gap-1.5" aria-label="Условия и заявленный опыт">
        {card.work_formats.map((format) => (
          <li key={format} className="max-w-full min-w-0">
            <FormatPill format={format} title="Формат работы" />
          </li>
        ))}
        {card.relocation_ready ? (
          <li className="max-w-full min-w-0">
            <SoftPill icon={Plane}>готов(а) к переезду</SoftPill>
          </li>
        ) : null}
        {declared?.city ? (
          <li className="max-w-full min-w-0">
            <SoftPill icon={MapPin} title="Город" className={WRAP_PILL}>
              {declared.city}
            </SoftPill>
          </li>
        ) : null}
        {declared?.experience_years != null ? (
          <li className="max-w-full min-w-0">
            <SoftPill icon={Briefcase} title="Стаж">
              <span className="num">{formatYears(declared.experience_years)}</span>
            </SoftPill>
          </li>
        ) : null}
        {(declared?.roles ?? []).map((role) => (
          <li key={role.title} className="max-w-full min-w-0">
            <SoftPill title="Роль" className={WRAP_PILL}>
              {role.title}
            </SoftPill>
          </li>
        ))}
      </ul>
      {card.skills.length ? (
        <div className="flex min-w-0 flex-col gap-2">
          <ul className="flex min-w-0 flex-wrap gap-1.5" aria-label="Навыки и их источник">
            {card.skills.map((item) => (
              <li key={item.skill.code} className="max-w-full min-w-0" title={item.detail ?? undefined}>
                <EvidenceChip
                  kind={item.kind}
                  skill={item.skill.title}
                  label={item.kind_label}
                  showLabel={false}
                  audience="self"
                />
              </li>
            ))}
          </ul>
          <EvidenceLegend kinds={kinds} audience="self" className="border-t border-line pt-2" />
        </div>
      ) : null}
      {card.custom_skills?.length ? (
        <div className="flex min-w-0 flex-col gap-1.5">
          <p className={FACT_LABEL}>Заявлено</p>
          <ul className="flex min-w-0 flex-wrap gap-1.5">
            {card.custom_skills.map((skill) => (
              <li key={skill} className="max-w-full min-w-0">
                <SoftPill size="sm" icon={PencilLine} className={cn(WRAP_PILL, '[&>svg]:size-3.5')}>
                  {skill}
                </SoftPill>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {fspText ? (
        <div className="flex min-w-0 items-start gap-3">
          <IconTile icon={Trophy} tone={card.fsp.summary ? 'accent' : 'neutral'} size="xs" />
          <p className="type-sm min-w-0 flex-1 text-ink [overflow-wrap:anywhere]">
            <span className="sr-only">ФСП: </span>
            {fspText}
          </p>
        </div>
      ) : null}
      {declared?.about ? (
        <div className="flex min-w-0 flex-col gap-1.5 rounded-md bg-fill p-3">
          <p className={FACT_LABEL}>О себе</p>
          <p className="type-sm min-w-0 whitespace-pre-line text-ink [overflow-wrap:anywhere]">{declared.about}</p>
        </div>
      ) : null}
    </article>
  )
}

export type PrivacyPreviewProps = {
  /** Начальная вкладка. */
  initial?: PreviewState
}

/** Предпросмотр «Как меня видит работодатель»: вкладки «До согласия» и «После согласия». */
export function PrivacyPreview({ initial = 'before' }: PrivacyPreviewProps) {
  const [state, setState] = useState<PreviewState>(initial)
  const query = useQuery({ ...previewQuery({ query: { state } }), retry: false })
  const T = PRIVACY.preview

  return (
    <section className="flex min-w-0 flex-col gap-3" aria-labelledby="privacy-preview-title">
      <h2 id="privacy-preview-title" className="type-h3 flex min-w-0 items-center gap-2.5">
        <IconTile icon={ScanEye} tone="solid" size="sm" />
        {T.title}
      </h2>
      <Tabs value={state} onValueChange={(value) => setState(value as PreviewState)}>
        <TabsList>
          <TabsTrigger value="before">{T.before}</TabsTrigger>
          <TabsTrigger value="after">{T.after}</TabsTrigger>
        </TabsList>
      </Tabs>
      <div aria-live="polite" className="min-w-0">
        {query.isPending ? (
          <Skeleton className="h-64 w-full" />
        ) : hasCode(query.error, 'no_category') ? (
          <EmptyState compact title={T.noCategory} className="surface-row border-dashed" />
        ) : query.isError ? (
          <ErrorState
            headingLevel={3}
            compact
            error={query.error}
            onRetry={() => query.refetch()}
            retrying={query.isFetching}
          />
        ) : (
          <div className="flex min-w-0 flex-col gap-2">
            <p className="type-caption flex min-w-0 items-start gap-1.5 text-ink-muted">
              {state === 'after' ? (
                <LockOpen className="mt-px size-3.5 shrink-0 text-success" aria-hidden="true" />
              ) : (
                <Lock className="mt-px size-3.5 shrink-0" aria-hidden="true" />
              )}
              <span className="min-w-0">{state === 'after' ? T.afterNote : T.beforeNote}</span>
            </p>
            <PreviewCard card={query.data} state={state} />
          </div>
        )}
      </div>
    </section>
  )
}
