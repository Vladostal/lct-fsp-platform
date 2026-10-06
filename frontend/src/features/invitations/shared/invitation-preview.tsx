import { Mail } from 'lucide-react'
import type { ContactMethod, WorkFormat } from '@/client'
import { SalaryRange } from '@/components/app'
import { WORK_FORMAT_LABELS } from '@/content/common'
import { cn } from '@/lib/utils'
import { CONTACT_KIND_LABELS } from './content'

export type InvitationPreviewProps = {
  companyName: string
  trustLabel?: string | null
  title: string
  salaryFrom: number
  salaryTo: number
  workFormat: WorkFormat
  city?: string | null
  description: string
  contactMethod: ContactMethod
  message?: string | null
  className?: string
}

/** Приглашение так, как его видит кандидат: условия крупно, описание и способ связи ниже. */
export function InvitationPreview(props: InvitationPreviewProps) {
  const {
    companyName,
    trustLabel,
    title,
    salaryFrom,
    salaryTo,
    workFormat,
    city,
    description,
    contactMethod,
    message,
  } = props
  return (
    <article
      data-slot="invitation-preview"
      className={cn('surface-row flex min-w-0 flex-col gap-4 p-4', props.className)}
    >
      <header className="flex min-w-0 flex-col gap-1">
        <p className="type-eyebrow truncate text-ink-muted">{companyName}</p>
        {trustLabel ? <p className="type-caption text-ink-muted">{trustLabel}</p> : null}
        <h3 className="type-h3 [overflow-wrap:anywhere] text-ink">{title}</h3>
      </header>
      <div className="flex min-w-0 flex-col gap-2">
        <SalaryRange from={salaryFrom} to={salaryTo} size="lg" />
        <p className="type-sm text-ink-muted">
          {WORK_FORMAT_LABELS[workFormat]}
          {city ? ` · ${city}` : ''}
        </p>
      </div>
      <p className="type-body max-w-[72ch] whitespace-pre-line text-ink [overflow-wrap:anywhere]">{description}</p>
      {message ? (
        <blockquote className="type-sm border-line border-l-2 pl-3 whitespace-pre-line text-ink-muted [overflow-wrap:anywhere]">
          {message}
        </blockquote>
      ) : null}
      <p className="type-sm flex min-w-0 items-center gap-2 text-ink-muted">
        <Mail className="size-4 shrink-0" aria-hidden="true" />
        <span className="min-w-0 [overflow-wrap:anywhere]">
          Способ связи: {CONTACT_KIND_LABELS[contactMethod.kind]}, <span className="num">{contactMethod.value}</span>
        </span>
      </p>
    </article>
  )
}
