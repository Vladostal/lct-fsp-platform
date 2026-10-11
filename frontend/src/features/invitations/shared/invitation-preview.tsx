import { AtSign, type LucideIcon, Mail, Phone, Send } from 'lucide-react'
import type { ContactKind, ContactMethod, WorkFormat } from '@/client'
import { IconTile, SalaryRange } from '@/components/app'
import { cn } from '@/lib/utils'
import { CompanyTile, OfferPills } from '../candidate/parts'
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
  isDemo?: boolean
  className?: string
}

const CONTACT_ICON: Record<ContactKind, LucideIcon> = { email: Mail, phone: Phone, telegram: Send, other: AtSign }

/**
 * Приглашение так, как его видит кандидат. Собрано из тех же частей, что экран кандидата: плитка компании,
 * вилка крупно, плашки формата и города, сообщение на тонированном фоне, плитка способа связи.
 */
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
    isDemo = false,
  } = props
  return (
    <article
      data-slot="invitation-preview"
      className={cn('accent-card surface-row flex min-w-0 flex-col gap-4 p-4 md:p-5', props.className)}
    >
      <header className="relative flex min-w-0 items-start gap-3">
        <CompanyTile name={companyName} />
        <div className="flex min-w-0 flex-col gap-0.5">
          <p className="type-eyebrow truncate text-ink-muted">
            {companyName}
            {trustLabel ? ` · ${trustLabel}` : ''}
          </p>
          <h3 className="type-h3 [overflow-wrap:anywhere] text-ink">{title}</h3>
        </div>
      </header>
      <div className="relative flex min-w-0 flex-col gap-3">
        <SalaryRange from={salaryFrom} to={salaryTo} size="lg" />
        <OfferPills
          salary={false}
          offer={{
            salary_from: salaryFrom,
            salary_to: salaryTo,
            work_format: workFormat,
            city,
            is_demo: isDemo,
            below_my_min: false,
          }}
        />
      </div>
      <p className="type-body max-w-[72ch] whitespace-pre-line text-ink [overflow-wrap:anywhere]">{description}</p>
      {message ? (
        <p className="type-body max-w-[72ch] rounded-md bg-brand-50 p-4 whitespace-pre-line [overflow-wrap:anywhere] text-ink">
          {message}
        </p>
      ) : null}
      <div className="flex min-w-0 items-center gap-3 rounded-md border border-line p-3">
        <IconTile icon={CONTACT_ICON[contactMethod.kind]} tone="brand" />
        <p className="flex min-w-0 flex-1 flex-col">
          <span className="type-caption text-ink-muted">
            <span className="sr-only">Способ связи: </span>
            {CONTACT_KIND_LABELS[contactMethod.kind]}
          </span>
          <span className="num type-body font-medium [overflow-wrap:anywhere] text-ink">{contactMethod.value}</span>
        </p>
      </div>
    </article>
  )
}
