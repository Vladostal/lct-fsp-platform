import { Link } from '@tanstack/react-router'
import type * as React from 'react'
import { Button } from '@/components/ui/button'
import { COMMON } from '@/content/common'
import { AppLogo } from '../app-logo'
import { AppHeader } from './app-header'
import { NavPill } from './nav-pill'
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

/** Каркас Public (E §1.2): шапка с логотипом и «Войти», содержимое, подвал. */
export function PublicLayout({ signedIn, homeHref, demo, children }: PublicLayoutProps) {
  return (
    <div className="flex min-h-dvh flex-col bg-canvas">
      <SkipLink />
      <AppHeader
        logo={<AppLogo href="/" compact />}
        nav={
          <div className="flex min-w-0 flex-1">
            <NavPill
              items={[
                { to: '/how-it-works', label: 'Как это работает' },
                ...(demo ? [{ to: '/demo', label: 'Демо-доступ', exact: true }] : []),
              ]}
              label={COMMON.mainNav}
              variant="bar"
              barClassName="hidden md:flex"
            />
          </div>
        }
        actions={
          <Button variant="secondary" size="sm" asChild>
            <Link to={signedIn ? homeHref : '/login'}>{signedIn ? COMMON.toCabinet : COMMON.login}</Link>
          </Button>
        }
      />
      <main id="main" tabIndex={-1} className="flex min-w-0 flex-1 flex-col outline-none" data-focus-quiet>
        {children}
      </main>
      <SiteFooter demo={demo} />
    </div>
  )
}
