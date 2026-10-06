import type { LucideIcon } from 'lucide-react'
import type * as React from 'react'
import { usePageTitle } from '@/components/app'
import { Card } from '@/components/ui/card'

export type AuthCardProps = {
  title: string
  description?: React.ReactNode
  /** Иконка состояния над заголовком (письмо, галочка, предупреждение). */
  icon?: LucideIcon
  iconTone?: 'brand' | 'success' | 'warning'
  children?: React.ReactNode
  footer?: React.ReactNode
}

const ICON_TONE = {
  brand: 'bg-brand-50 text-brand-700',
  success: 'bg-success-bg text-success',
  warning: 'bg-warning-bg text-warning',
} as const

/** Карточка каркаса Auth: единственный h1 экрана, содержимое и строка ссылок под карточкой. */
export function AuthCard({ title, description, icon: Icon, iconTone = 'brand', children, footer }: AuthCardProps) {
  usePageTitle(title)
  return (
    <div className="flex min-w-0 animate-fade-in flex-col gap-4">
      <Card className="gap-6 md:p-8">
        <div className="flex min-w-0 flex-col gap-3">
          {Icon ? (
            <span
              className={`grid size-14 shrink-0 place-items-center rounded-full ${ICON_TONE[iconTone]}`}
              aria-hidden="true"
            >
              <Icon className="size-8" strokeWidth={1.5} />
            </span>
          ) : null}
          <h1 data-page-title tabIndex={-1} className="type-h1 text-ink outline-none">
            {title}
          </h1>
          {description ? <div className="type-body min-w-0 text-ink-muted">{description}</div> : null}
        </div>
        {children}
      </Card>
      {footer ? (
        <div className="type-body flex min-w-0 flex-wrap items-center justify-center gap-x-2 gap-y-1 text-center text-ink-muted">
          {footer}
        </div>
      ) : null}
    </div>
  )
}
