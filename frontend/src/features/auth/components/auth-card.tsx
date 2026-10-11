import { KeyRound, type LucideIcon } from 'lucide-react'
import type * as React from 'react'
import { IconTile, usePageTitle } from '@/components/app'

export type AuthCardProps = {
  title: string
  description?: React.ReactNode
  /** Иконка состояния в шапке карточки (письмо, галочка, предупреждение). */
  icon?: LucideIcon
  iconTone?: 'brand' | 'success' | 'warning'
  children?: React.ReactNode
  footer?: React.ReactNode
}

/*
 * Шапка-полоса с градиентом бренда, как у героя лендинга: фон задан и цветом, и градиентом — контраст
 * белого заголовка считается по цвету.
 */
const BAND_CSS = `
.auth-band{background-color:var(--color-brand-600);background-image:
  radial-gradient(60% 140% at 100% 0%,color-mix(in srgb,var(--color-fsp-red) 30%,transparent),transparent 70%),
  linear-gradient(115deg,var(--color-brand-600),var(--color-brand-900))}
`

const TILE_TONE = { brand: 'plain', success: 'success', warning: 'warning' } as const

/** Карточка каркаса Auth: единственный h1 экрана — в градиентной шапке, содержимое и строка ссылок под карточкой. */
export function AuthCard({ title, description, icon = KeyRound, iconTone = 'brand', children, footer }: AuthCardProps) {
  usePageTitle(title)
  const hasBody = Boolean(description) || Boolean(children)
  return (
    <div className="flex min-w-0 animate-rise-in flex-col gap-4">
      <style>{BAND_CSS}</style>
      <div data-slot="card" className="min-w-0 overflow-hidden rounded-lg bg-surface text-ink shadow-pop md:rounded-xl">
        <div className="auth-band flex min-w-0 items-center gap-3 px-5 py-4 md:gap-4 md:px-8 md:py-5">
          <IconTile
            icon={icon}
            tone={TILE_TONE[iconTone]}
            size="lg"
            className={iconTone === 'brand' ? 'text-brand-700' : undefined}
          />
          <h1 data-page-title tabIndex={-1} className="type-h1 min-w-0 break-words text-on-brand outline-none">
            {title}
          </h1>
        </div>
        {hasBody ? (
          <div className="flex min-w-0 flex-col gap-6 p-5 md:p-8">
            {description ? <div className="type-body min-w-0 text-ink-muted">{description}</div> : null}
            {children}
          </div>
        ) : null}
      </div>
      {footer ? (
        <div className="type-body flex min-w-0 flex-wrap items-center justify-center gap-x-2 gap-y-1 text-center text-ink-muted">
          {footer}
        </div>
      ) : null}
    </div>
  )
}
