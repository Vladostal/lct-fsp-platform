import { Link } from '@tanstack/react-router'
import { LEGAL_DOCS } from '@/content/common'
import { APP_NAME } from '@/lib/config'

export type SiteFooterProps = {
  /** Показывать ссылку «Демо-доступ» (`features.demo`). */
  demo?: boolean
}

/** Подвал публичных страниц: полный логотип ФСП из брендбука, ссылки на документы и объяснение механик. */
export function SiteFooter({ demo = false }: SiteFooterProps) {
  return (
    <footer className="border-t border-line bg-surface">
      <div className="page-container flex flex-col gap-8 py-8 md:flex-row md:items-start md:justify-between md:py-10">
        <div className="flex min-w-0 max-w-md flex-col gap-4">
          <img
            src="/logo_head.svg"
            alt="ФСП — Федерация спортивного программирования России"
            width={256}
            height={32}
            className="h-8 w-auto max-w-full self-start"
          />
          <p className="type-sm text-ink-muted">
            {APP_NAME} — прототип платформы подбора ИТ-специалистов с обратной механикой. Сделан для спецтрека ФСП
            хакатона «Лидеры цифровой трансформации — 2026».
          </p>
        </div>
        <nav aria-label="Документы и справка" className="min-w-0">
          <ul className="flex flex-col gap-1">
            <li>
              <Link to="/how-it-works" className="text-link inline-flex min-h-11 items-center text-sm">
                Как это работает
              </Link>
            </li>
            {demo ? (
              <li>
                <Link to="/demo" className="text-link inline-flex min-h-11 items-center text-sm">
                  Демо-доступ
                </Link>
              </li>
            ) : null}
            {LEGAL_DOCS.map((item) => (
              <li key={item.doc}>
                <Link
                  to="/legal/$doc"
                  params={{ doc: item.doc }}
                  className="text-link inline-flex min-h-11 items-center text-sm"
                >
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      </div>
    </footer>
  )
}
