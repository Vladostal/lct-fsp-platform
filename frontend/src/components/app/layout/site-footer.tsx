import { Link } from '@tanstack/react-router'
import { LEGAL_DOCS } from '@/content/common'
import { ThemeSwitch } from '../theme-switch'

export type SiteFooterProps = {
  /** Показывать ссылку «Демо-доступ» (`features.demo`). */
  demo?: boolean
}

const linkClass =
  'inline-flex min-h-11 items-center text-sm text-ink-muted transition-colors duration-(--dur-fast) hover:text-ink'

/** Подвал публичных страниц: знак ФСП и ссылки одной строкой приглушённым цветом. */
export function SiteFooter({ demo = false }: SiteFooterProps) {
  return (
    <footer className="border-t border-line bg-surface">
      <div className="page-container flex flex-col gap-3 py-4 md:flex-row md:items-center md:justify-between">
        <img
          src="/logo_head.svg"
          alt="ФСП — Федерация спортивного программирования России"
          width={256}
          height={32}
          className="only-light h-6 w-auto max-w-full self-start"
        />
        <img
          src="/logo_head_dark.svg"
          alt="ФСП — Федерация спортивного программирования России"
          width={256}
          height={32}
          className="only-dark h-6 w-auto max-w-full self-start"
        />
        <nav aria-label="Документы и справка" className="min-w-0">
          <ul className="flex flex-wrap gap-x-6">
            <li>
              <Link to="/how-it-works" className={linkClass}>
                Как это работает
              </Link>
            </li>
            {demo ? (
              <li>
                <Link to="/demo" className={linkClass}>
                  Демо-доступ
                </Link>
              </li>
            ) : null}
            {LEGAL_DOCS.map((item) => (
              <li key={item.doc}>
                <Link to="/legal/$doc" params={{ doc: item.doc }} className={linkClass}>
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <ThemeSwitch className="-ml-2.5 md:ml-0" />
      </div>
    </footer>
  )
}
