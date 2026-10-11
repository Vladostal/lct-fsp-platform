import { Building2, CalendarCheck, Eye, Globe, MapPin, ShieldCheck } from 'lucide-react'
import { ExternalLink, IconTile, SoftPill } from '@/components/app'
import { formatDate } from '@/lib/format'
import { COMPANY } from '../content'
import { type CompanyDraft, normalizeSite } from '../schema'

type Props = {
  draft: CompanyDraft
  since?: string | null
  trustLabel?: string | null
}

/** Монограмма компании: первые буквы до двух слов названия. */
function monogram(name: string): string {
  return name
    .split(/[\s«»"'.,-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? '')
    .join('')
}

/** Предпросмотр: так компанию видит кандидат в приглашении. */
export function CompanyPreview({ draft, since, trustLabel }: Props) {
  const name = draft.name.trim()
  const has = name || draft.description.trim()
  const site = normalizeSite(draft.site)
  return (
    <section aria-labelledby="company-preview" className="flex min-w-0 flex-col gap-3">
      <h2 id="company-preview" className="type-eyebrow flex items-center gap-1.5">
        <Eye aria-hidden="true" className="size-3.5 text-brand-700" />
        {COMPANY.sections.preview}
      </h2>
      {has ? (
        <div className="accent-card surface-row flex min-w-0 flex-col gap-3 p-4 md:p-5">
          <div className="flex min-w-0 items-center gap-3">
            <IconTile tone="solid" size="xl" icon={name ? undefined : Building2} className="text-base">
              {name ? monogram(name) : null}
            </IconTile>
            <div className="flex min-w-0 flex-col gap-0.5">
              <p className="type-h3 min-w-0 font-semibold break-words">{name || '—'}</p>
              {draft.sphere.trim() ? (
                <p className="type-sm min-w-0 break-words text-ink-muted">{draft.sphere.trim()}</p>
              ) : null}
            </div>
          </div>
          {draft.description.trim() ? (
            <p className="type-body line-clamp-6 min-w-0 whitespace-pre-line break-words">{draft.description.trim()}</p>
          ) : null}
          {site || draft.city.trim() ? (
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              {draft.city.trim() ? (
                <SoftPill icon={MapPin} className="h-auto min-h-7 shrink py-0.5 [&>svg]:shrink-0">
                  <span className="min-w-0 break-words">{draft.city.trim()}</span>
                </SoftPill>
              ) : null}
              {site ? (
                <p className="type-sm flex min-w-0 items-center gap-1.5 break-all">
                  <Globe aria-hidden="true" className="size-4 shrink-0 text-ink-muted" />
                  <ExternalLink href={site}>{site.replace(/^https?:\/\//, '')}</ExternalLink>
                </p>
              ) : null}
            </div>
          ) : null}
          <div className="flex min-w-0 flex-wrap items-center gap-2 border-t border-line pt-3">
            <SoftPill icon={CalendarCheck} size="sm" className="h-auto min-h-6 shrink py-0.5 text-xs [&>svg]:shrink-0">
              <span className="min-w-0">
                {COMPANY.preview.since} {since ? formatDate(since) : 'сегодняшнего дня'}
              </span>
            </SoftPill>
            <SoftPill icon={ShieldCheck} size="sm" className="h-auto min-h-6 shrink py-0.5 text-xs [&>svg]:shrink-0">
              <span className="min-w-0">{trustLabel ?? 'Компания подтвердила только e-mail'}</span>
            </SoftPill>
          </div>
        </div>
      ) : (
        <p className="type-sm flex min-w-0 items-center gap-3 rounded-md border border-dashed border-line-strong bg-surface p-4 text-ink-muted">
          <IconTile icon={Building2} tone="dashed" />
          <span className="min-w-0">{COMPANY.preview.empty}</span>
        </p>
      )}
    </section>
  )
}
