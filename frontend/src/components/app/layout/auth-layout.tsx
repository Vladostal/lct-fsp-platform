import { Link } from '@tanstack/react-router'
import type * as React from 'react'
import { LEGAL_DOCS } from '@/content/common'
import { AppLogo } from '../app-logo'
import { SkipLink } from './skip-link'

/** Каркас Auth (E §1.2): одна карточка 480 px по центру; логотип ведёт на лендинг. */
export function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col bg-canvas">
      <SkipLink />
      <header className="page-container flex h-14 items-center md:h-16">
        <AppLogo href="/" />
      </header>
      <main
        id="main"
        tabIndex={-1}
        data-focus-quiet
        className="flex min-w-0 flex-1 flex-col items-center px-4 pt-4 pb-12 outline-none md:justify-center md:pt-8 md:pb-24"
      >
        <div className="w-full max-w-[480px] min-w-0">{children}</div>
      </main>
      <footer className="page-container py-6">
        <nav aria-label="Документы">
          <ul className="flex flex-wrap justify-center gap-x-6 gap-y-1">
            {LEGAL_DOCS.map((item) => (
              <li key={item.doc}>
                <Link
                  to="/legal/$doc"
                  params={{ doc: item.doc }}
                  className="inline-flex min-h-11 items-center text-sm text-ink-muted underline decoration-1 underline-offset-3 hover:text-ink"
                >
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      </footer>
    </div>
  )
}
