import { ExternalLink } from '@/components/app'
import { formatDate } from '@/lib/format'
import { COMPANY } from '../content'
import { type CompanyDraft, normalizeSite } from '../schema'

type Props = {
  draft: CompanyDraft
  since?: string | null
  trustLabel?: string | null
}

/** Предпросмотр: так компанию видит кандидат в приглашении. */
export function CompanyPreview({ draft, since, trustLabel }: Props) {
  const has = draft.name.trim() || draft.description.trim()
  const site = normalizeSite(draft.site)
  return (
    <section aria-labelledby="company-preview" className="flex min-w-0 flex-col gap-3">
      <h2 id="company-preview" className="type-eyebrow">
        {COMPANY.sections.preview}
      </h2>
      {has ? (
        <div className="flex min-w-0 flex-col gap-2">
          <p className="type-h3 min-w-0 font-semibold break-words">{draft.name.trim() || '—'}</p>
          {draft.sphere.trim() ? (
            <p className="type-sm min-w-0 break-words text-ink-muted">{draft.sphere.trim()}</p>
          ) : null}
          {draft.description.trim() ? (
            <p className="type-body line-clamp-6 min-w-0 whitespace-pre-line break-words">{draft.description.trim()}</p>
          ) : null}
          {site || draft.city.trim() ? (
            <p className="type-sm min-w-0 break-words text-ink-muted">
              {site ? <ExternalLink href={site}>{site.replace(/^https?:\/\//, '')}</ExternalLink> : null}
              {site && draft.city.trim() ? ' · ' : null}
              {draft.city.trim()}
            </p>
          ) : null}
          <p className="type-caption text-ink-muted">
            {COMPANY.preview.since} {since ? formatDate(since) : 'сегодняшнего дня'} ·{' '}
            {trustLabel ?? 'Компания подтвердила только e-mail'}
          </p>
        </div>
      ) : (
        <p className="type-sm text-ink-muted">{COMPANY.preview.empty}</p>
      )}
    </section>
  )
}
