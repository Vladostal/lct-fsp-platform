import { Link } from '@tanstack/react-router'
import type * as React from 'react'
import { Button } from '@/components/ui/button'
import { COMMON } from '@/content/common'
import { AppLogo } from '../app-logo'
import { SiteFooter } from './site-footer'
import { SkipLink } from './skip-link'

export type PublicLayoutProps = {
  /** Вошедший пользователь видит «В кабинет» вместо «Войти». */
  signedIn: boolean
  /** Адрес первого экрана роли для вошедшего. */
  homeHref: string
  /** Флаг `features.demo`: ссылки на демо-доступ. */
  demo: boolean
  children: React.ReactNode
}

const navLinkClass =
  'relative inline-flex h-full items-center text-base font-medium whitespace-nowrap text-ink transition-colors duration-(--dur-fast) hover:text-brand-700 aria-[current=page]:text-brand-700 aria-[current=page]:after:absolute aria-[current=page]:after:inset-x-0 aria-[current=page]:after:bottom-0 aria-[current=page]:after:h-0.5 aria-[current=page]:after:bg-brand-600'

/** Каркас Public (E §1.2): шапка с логотипом и «Войти», содержимое, подвал. */
export function PublicLayout({ signedIn, homeHref, demo, children }: PublicLayoutProps) {
  return (
    <div className="flex min-h-dvh flex-col bg-canvas">
      <SkipLink />
      <header data-sticky="top" className="sticky top-0 z-20 border-b border-line bg-surface">
        <div className="page-container flex h-14 items-center gap-4 md:h-16 md:gap-8">
          <AppLogo href="/" compact />
          <nav aria-label={COMMON.mainNav} className="hidden h-full min-w-0 flex-1 items-center gap-6 md:flex">
            <Link to="/how-it-works" className={navLinkClass}>
              Как это работает
            </Link>
            {demo ? (
              <Link to="/demo" className={navLinkClass} activeOptions={{ exact: true }}>
                Демо-доступ
              </Link>
            ) : null}
          </nav>
          <div className="ml-auto flex shrink-0 items-center gap-2">
            {signedIn ? (
              <Button variant="secondary" size="sm" asChild>
                <Link to={homeHref}>{COMMON.toCabinet}</Link>
              </Button>
            ) : (
              <Button variant="secondary" size="sm" asChild>
                <Link to="/login">{COMMON.login}</Link>
              </Button>
            )}
          </div>
        </div>
      </header>
      <main id="main" tabIndex={-1} className="flex min-w-0 flex-1 flex-col outline-none" data-focus-quiet>
        {children}
      </main>
      <SiteFooter demo={demo} />
    </div>
  )
}
