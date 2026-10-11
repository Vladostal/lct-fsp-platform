import { Link } from '@tanstack/react-router'
import { ShieldCheck, Trophy, UserRound } from 'lucide-react'
import { PRIVACY } from '../content'

const TABS = [
  { to: '/candidate/settings/privacy', label: PRIVACY.tabs.privacy, icon: ShieldCheck },
  { to: '/candidate/settings/fsp', label: PRIVACY.tabs.fsp, icon: Trophy },
  { to: '/candidate/settings/account', label: PRIVACY.tabs.account, icon: UserRound },
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
              className="type-body tap-target inline-flex h-11 items-center gap-1.5 border-b-2 border-transparent px-2 font-medium text-ink-muted hover:text-ink data-[status=active]:border-brand-600 data-[status=active]:font-semibold data-[status=active]:text-brand-700 sm:px-4"
              activeProps={{ 'aria-current': 'page' }}
            >
              <tab.icon className="size-4" aria-hidden="true" />
              {tab.label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  )
}
