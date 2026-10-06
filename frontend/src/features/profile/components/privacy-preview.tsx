import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import type { CandidateCardEmployerView } from '@/client'
import { CategoryChip, EmptyState, ErrorState, EvidenceChip, LevelScale } from '@/components/app'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { WORK_FORMAT_LABELS } from '@/content/common'
import { hasCode } from '@/lib/api'
import { previewQuery } from '../api'
import { PRIVACY } from '../content'

type PreviewState = 'before' | 'after'

/**
 * Локальная замена `MatchCardDetailed audience="preview"` (F50): карточка кандидата глазами работодателя.
 * Показывает только то, что вернул сервер: «О себе» и имя приходят лишь в состоянии «после согласия».
 */
function PreviewCard({ card, state }: { card: CandidateCardEmployerView; state: PreviewState }) {
  const declared = card.declared
  const fspText = card.fsp.summary?.headline ?? card.fsp.neutral_text ?? null
  return (
    <article className="surface-card flex min-w-0 flex-col gap-4" aria-label={PRIVACY.preview.title}>
      <header className="flex min-w-0 flex-col gap-1">
        <p className="type-caption text-ink-muted">
          {state === 'after' ? PRIVACY.preview.afterNote : PRIVACY.preview.beforeNote}
        </p>
        <h3 className="type-h3 min-w-0 [overflow-wrap:anywhere]">
          {card.display_name ?? <span className="num">{card.public_code}</span>}
        </h3>
        {card.display_name ? <span className="num type-caption text-ink-muted">{card.public_code}</span> : null}
        <CategoryChip title={card.category.title} />
      </header>
      <LevelScale level={card.level} ownGrade={card.category.grade.code} size="sm" />
      {card.skills.length ? (
        <ul className="flex min-w-0 flex-wrap gap-2" aria-label="Подтверждённые навыки">
          {card.skills.map((item) => (
            <li key={item.skill.code} className="min-w-0">
              <EvidenceChip
                kind={item.kind}
                skill={item.skill.title}
                label={item.kind_label}
                detail={item.detail}
                audience="self"
              />
            </li>
          ))}
        </ul>
      ) : null}
      <dl className="grid min-w-0 gap-x-4 gap-y-2 sm:grid-cols-[auto_minmax(0,1fr)]">
        <dt className="type-sm text-ink-muted">Формат работы</dt>
        <dd className="type-sm min-w-0 text-ink">
          {card.work_formats.map((f) => WORK_FORMAT_LABELS[f]).join(', ')}
          {card.relocation_ready ? ' · готов(а) к переезду' : ''}
        </dd>
        {declared?.city ? (
          <>
            <dt className="type-sm text-ink-muted">Город</dt>
            <dd className="type-sm min-w-0 text-ink [overflow-wrap:anywhere]">{declared.city}</dd>
          </>
        ) : null}
        {declared?.experience_years != null || declared?.roles?.length ? (
          <>
            <dt className="type-sm text-ink-muted">Стаж и роли</dt>
            <dd className="type-sm min-w-0 text-ink [overflow-wrap:anywhere]">
              {[
                declared?.experience_years != null ? `${declared.experience_years} лет` : null,
                ...(declared?.roles ?? []).map((r) => r.title),
              ]
                .filter(Boolean)
                .join(' · ')}
            </dd>
          </>
        ) : null}
        {card.custom_skills?.length ? (
          <>
            <dt className="type-sm text-ink-muted">Заявлено</dt>
            <dd className="type-sm min-w-0 text-ink [overflow-wrap:anywhere]">{card.custom_skills.join(', ')}</dd>
          </>
        ) : null}
        {fspText ? (
          <>
            <dt className="type-sm text-ink-muted">ФСП</dt>
            <dd className="type-sm min-w-0 text-ink [overflow-wrap:anywhere]">{fspText}</dd>
          </>
        ) : null}
        {declared?.about ? (
          <>
            <dt className="type-sm text-ink-muted">О себе</dt>
            <dd className="type-sm min-w-0 whitespace-pre-line text-ink [overflow-wrap:anywhere]">{declared.about}</dd>
          </>
        ) : null}
      </dl>
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
      <h2 id="privacy-preview-title" className="type-h3">
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
          <EmptyState compact title={T.noCategory} />
        ) : query.isError ? (
          <ErrorState
            headingLevel={3}
            compact
            error={query.error}
            onRetry={() => query.refetch()}
            retrying={query.isFetching}
          />
        ) : (
          <PreviewCard card={query.data} state={state} />
        )}
      </div>
    </section>
  )
}
