import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { LogOut } from 'lucide-react'
import type * as React from 'react'
import { useEffect } from 'react'
import type { InvitationSummaryView, MeView } from '@/client'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { COMMON, NAV, ROLE_LABELS, USER_MENU, VISIBILITY_LABELS, visibilityTitle } from '@/content/common'
import { CommandPalette } from '@/features/command/command-palette'
import { api } from '@/lib/api'
import type { CatalogFeatures } from '@/lib/features'
import { initials } from '@/lib/format'
import { invitationSummaryQuery, polling, queryKeys, quotaQuery } from '@/lib/query'
import { AppLogo } from '../app-logo'
import { DemoChip } from '../demo-chip'
import { QuotaIndicator } from '../quota-indicator'
import { StatusBadge } from '../status-badge'
import { ThemeMenuItems } from '../theme-switch'
import { AppHeader } from './app-header'
import { NavPill } from './nav-pill'
import { SkipLink } from './skip-link'

export type CabinetLayoutProps = {
  me: MeView
  /** Флаги каталога; null — каталог недоступен (демо-приглашение не запрашивается). */
  features: CatalogFeatures | null
  onLogout: () => void
  loggingOut?: boolean
  children: React.ReactNode
}

const DEMO_INVITATION_MARK = 'demo-invitation-requested'

/**
 * Демо-приглашение (Арх. 4.14, 11.8): при `features.demo`, не-демо аккаунте, состоянии `visible` и нуле
 * приглашений шапка кандидата один раз за сессию браузера вызывает `POST /demo/invitation` и обновляет сводку.
 * Сама сводка ничего не запускает. Отметка в sessionStorage ставится до запроса, чтобы параллельные вкладки и
 * повторные рендеры не отправили его дважды; при сбое отметка остаётся — повтор будет в новой сессии браузера.
 */
function useDemoInvitation(me: MeView, demoEnabled: boolean, summary: InvitationSummaryView | undefined) {
  const queryClient = useQueryClient()
  const { mutate } = useMutation({
    mutationFn: () => api.post<{ sent: boolean }>('/demo/invitation'),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.candidate.invitationSummary }),
  })

  useEffect(() => {
    if (!demoEnabled || me.role !== 'candidate' || me.is_demo || !summary) return
    const total = summary.awaiting + summary.accepted + summary.archived
    if (summary.visibility.state !== 'visible' || total > 0) return
    const key = `${DEMO_INVITATION_MARK}:${me.id}`
    try {
      if (window.sessionStorage.getItem(key)) return
      window.sessionStorage.setItem(key, '1')
    } catch {
      // sessionStorage недоступен (приватный режим со строгими настройками) — запрос не отправляем вовсе:
      // без отметки он повторялся бы при каждом опросе.
      return
    }
    mutate()
  }, [demoEnabled, me.id, me.is_demo, me.role, summary, mutate])
}

/**
 * Каркас Cabinet (E §1.5): липкая шапка 56 px с пилюлей навигации роли (xl+), ниже — нижний таб-бар, контейнер до 1340 px.
 * Шапка сама запрашивает сводку приглашений и видимость (кандидат) либо квоту (работодатель) и обновляет их
 * опросом раз в 20 с при видимой вкладке.
 */
export function CabinetLayout({ me, features, onLogout, loggingOut = false, children }: CabinetLayoutProps) {
  const isCandidate = me.role === 'candidate'

  // Сбой сводки или квоты не ломает шапку: индикатор просто не показывается, экран сообщит об ошибке сам.
  const summary = useQuery({ ...invitationSummaryQuery, ...polling, enabled: isCandidate, retry: false })
  const quota = useQuery({ ...quotaQuery, ...polling, enabled: !isCandidate, retry: false })
  useDemoInvitation(me, features?.demo ?? false, summary.data)

  const home = isCandidate ? '/candidate' : '/employer/needs'
  const awaiting = summary.data?.awaiting ?? 0
  const barItems = NAV[me.role].map((item) => ({
    to: item.to,
    label: item.label,
    exact: 'exact' in item ? item.exact : false,
    badge: 'counter' in item ? awaiting : undefined,
  }))
  const tabItems = NAV[me.role].map((item) => ({
    to: item.to,
    label: item.short,
    icon: item.icon,
    exact: 'exact' in item ? item.exact : false,
    badge: 'counter' in item ? awaiting : undefined,
  }))

  const indicator = isCandidate ? (
    summary.data ? (
      <Link
        to="/candidate/settings/privacy"
        className="inline-flex min-h-11 shrink-0 items-center rounded-full"
        aria-label={`${VISIBILITY_LABELS[summary.data.visibility.state]} — настройки приватности`}
      >
        <StatusBadge
          status={summary.data.visibility.state}
          label={VISIBILITY_LABELS[summary.data.visibility.state]}
          title={visibilityTitle(summary.data.visibility.state)}
          live
          className="h-8 px-3"
        />
      </Link>
    ) : null
  ) : quota.data?.frozen ? (
    <Link to="/employer/invitations" className="inline-flex min-h-11 shrink-0 items-center rounded-full">
      <QuotaIndicator quota={quota.data} />
    </Link>
  ) : null

  return (
    <div className="flex min-h-dvh flex-col bg-canvas">
      <SkipLink />
      <AppHeader
        logo={<AppLogo href={home} compact />}
        nav={
          <div className="flex min-w-0 flex-1 justify-center">
            <NavPill items={barItems} label={COMMON.mainNav} variant="bar" />
          </div>
        }
        actions={
          <>
            <CommandPalette role={me.role} onLogout={onLogout} />
            <div className="hidden md:flex">{indicator}</div>
            <DropdownMenu>
              <DropdownMenuTrigger
                aria-label={COMMON.userMenu}
                className="grid size-11 shrink-0 place-items-center rounded-full transition-opacity duration-(--dur-fast) hover:opacity-80"
              >
                <Avatar>
                  <AvatarFallback>{initials(me.email)}</AvatarFallback>
                </Avatar>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-64">
                <DropdownMenuLabel className="flex flex-col gap-0.5">
                  <span className="type-caption text-ink-muted">{ROLE_LABELS[me.role]}</span>
                  <span className="text-sm font-medium text-ink [overflow-wrap:anywhere]">{me.email}</span>
                  {/* Ниже 768 px индикатор роли и демо-метка живут здесь, а не в шапке. */}
                  {indicator ? (
                    <span className="mt-1 flex flex-wrap items-center gap-2 md:hidden">{indicator}</span>
                  ) : null}
                  {me.is_demo ? <DemoChip className="mt-1 self-start" /> : null}
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                {USER_MENU[me.role].map((item) => (
                  <DropdownMenuItem key={item.to} asChild>
                    <Link to={item.to}>{item.label}</Link>
                  </DropdownMenuItem>
                ))}
                <DropdownMenuSeparator />
                <ThemeMenuItems />
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={onLogout} disabled={loggingOut}>
                  <LogOut aria-hidden="true" />
                  {COMMON.logout}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </>
        }
      />

      <main
        id="main"
        tabIndex={-1}
        data-focus-quiet
        className="page-container flex min-w-0 flex-1 flex-col py-6 outline-none md:py-8"
      >
        {children}
      </main>

      <NavPill items={tabItems} label={COMMON.mainNav} variant="tabbar" />
    </div>
  )
}
