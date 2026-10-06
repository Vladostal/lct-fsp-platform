import { Link } from '@tanstack/react-router'
import { PRIVACY } from '../content'

const TABS = [
  { to: '/candidate/settings/privacy', label: PRIVACY.tabs.privacy },
  { to: '/candidate/settings/fsp', label: PRIVACY.tabs.fsp },
  { to: '/candidate/settings/account', label: PRIVACY.tabs.account },
] as const

/** Вкладки-маршруты настроек кандидата: «Приватность» / «ФСП ID» / «Аккаунт». Прокручиваются внутри себя. */
export function SettingsTabs() {
  return (
    <nav aria-label="Настройки" className="min-w-0 overflow-x-auto border-b border-line">
      <ul className="flex min-w-max gap-1">
        {TABS.map((tab) => (
          <li key={tab.to}>
            <Link
              to={tab.to}
              className="type-body tap-target inline-flex h-11 items-center border-b-2 border-transparent px-4 font-medium text-ink-muted hover:text-ink"
              activeProps={{ className: 'border-brand-600 text-ink', 'aria-current': 'page' }}
            >
              {tab.label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  )
}
