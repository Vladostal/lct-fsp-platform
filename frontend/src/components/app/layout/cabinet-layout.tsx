import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { LogOut, Menu } from 'lucide-react'
import type * as React from 'react'
import { useRef, useState } from 'react'
import type { MeView } from '@/client'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Sheet, SheetBody, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { COMMON, NAV, ROLE_LABELS, USER_MENU, VISIBILITY_LABELS } from '@/content/common'
import { initials } from '@/lib/format'
import { invitationSummaryQuery, polling, quotaQuery } from '@/lib/query'
import { cn } from '@/lib/utils'
import { AppLogo } from '../app-logo'
import { DemoChip } from '../demo-chip'
import { QuotaIndicator } from '../quota-indicator'
import { StatusBadge } from '../status-badge'
import { SkipLink } from './skip-link'

export type CabinetLayoutProps = {
  me: MeView
  onLogout: () => void
  loggingOut?: boolean
  children: React.ReactNode
}

type NavItem = { to: string; label: string; exact?: boolean; counter?: 'awaiting' }

function Counter({ value }: { value: number }) {
  if (value <= 0) return null
  return (
    <span className="num grid h-5 min-w-5 shrink-0 place-items-center rounded-full bg-brand-600 px-1.5 text-xs leading-none font-medium text-white">
      {value > 99 ? '99+' : value}
      <span className="sr-only"> ждут ответа</span>
    </span>
  )
}

/**
 * Каркас Cabinet (E §1.5): липкая шапка 64 px (56 при < 768) с навигацией роли, контейнер до 1340 px.
 * Шапка сама запрашивает сводку приглашений и видимость (кандидат) либо квоту (работодатель) и обновляет их
 * опросом раз в 20 с при видимой вкладке. Ниже 1280 px навигация уходит в панель «Меню».
 */
export function CabinetLayout({ me, onLogout, loggingOut = false, children }: CabinetLayoutProps) {
  const [menuOpen, setMenuOpen] = useState(false)
  const menuButtonRef = useRef<HTMLButtonElement>(null)
  const isCandidate = me.role === 'candidate'

  // Сбой сводки или квоты не ломает шапку: индикатор просто не показывается, экран сообщит об ошибке сам.
  const summary = useQuery({ ...invitationSummaryQuery, ...polling, enabled: isCandidate, retry: false })
  const quota = useQuery({ ...quotaQuery, ...polling, enabled: !isCandidate, retry: false })

  const items: readonly NavItem[] = NAV[me.role]
  const home = isCandidate ? '/candidate' : '/employer/needs'

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
          live
          className="h-9"
        />
      </Link>
    ) : null
  ) : quota.data ? (
    <Link to="/employer/invitations" className="inline-flex min-h-11 shrink-0 items-center rounded-full">
      <QuotaIndicator quota={quota.data} />
    </Link>
  ) : null

  const navLink = (item: NavItem, variant: 'bar' | 'sheet') => (
    <Link
      key={item.to}
      to={item.to}
      activeOptions={{ exact: item.exact ?? false }}
      onClick={() => setMenuOpen(false)}
      className={cn(
        'font-medium whitespace-nowrap text-ink transition-colors duration-(--dur-fast) hover:text-brand-700 aria-[current=page]:text-brand-700',
        variant === 'bar'
          ? 'relative inline-flex h-full items-center gap-2 text-base aria-[current=page]:after:absolute aria-[current=page]:after:inset-x-0 aria-[current=page]:after:bottom-0 aria-[current=page]:after:h-0.5 aria-[current=page]:after:bg-brand-600'
          : 'flex min-h-12 items-center gap-2 rounded-md border-l-2 border-transparent px-3 text-base hover:bg-fill aria-[current=page]:border-brand-600 aria-[current=page]:bg-brand-50',
      )}
    >
      {item.label}
      {item.counter === 'awaiting' ? <Counter value={summary.data?.awaiting ?? 0} /> : null}
    </Link>
  )

  return (
    <div className="flex min-h-dvh flex-col bg-canvas">
      <SkipLink />
      <header data-sticky="top" className="sticky top-0 z-20 border-b border-line bg-surface">
        <div className="page-container flex h-14 items-center gap-3 md:h-16 md:gap-4 xl:gap-8">
          <AppLogo href={home} compact />
          <nav aria-label={COMMON.mainNav} className="hidden h-full min-w-0 flex-1 items-center gap-6 xl:flex">
            {items.map((item) => navLink(item, 'bar'))}
          </nav>
          <Button
            ref={menuButtonRef}
            variant="ghost"
            size="sm"
            className="xl:hidden"
            aria-haspopup="dialog"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen(true)}
          >
            <Menu aria-hidden="true" />
            {COMMON.menu}
          </Button>
          <div className="ml-auto flex min-w-0 shrink-0 items-center gap-2 md:gap-3">
            {me.is_demo ? <DemoChip className="max-md:hidden" /> : null}
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
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                {USER_MENU[me.role].map((item) => (
                  <DropdownMenuItem key={item.to} asChild>
                    <Link to={item.to}>{item.label}</Link>
                  </DropdownMenuItem>
                ))}
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={onLogout} disabled={loggingOut}>
                  <LogOut aria-hidden="true" />
                  {COMMON.logout}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </header>

      <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
        <SheetContent
          side="left"
          // Панель открывается состоянием, а не SheetTrigger, поэтому фокус кнопке «Меню» возвращаем сами (E §7).
          onCloseAutoFocus={(event) => {
            event.preventDefault()
            menuButtonRef.current?.focus()
          }}
        >
          <SheetHeader>
            <SheetTitle>{COMMON.menu}</SheetTitle>
            <SheetDescription>{ROLE_LABELS[me.role]}</SheetDescription>
          </SheetHeader>
          <SheetBody className="gap-4">
            {/* На 375 px индикатор роли — первой строкой в меню (E §4.5). */}
            {indicator ? <div className="flex min-w-0 flex-wrap items-center gap-2 md:hidden">{indicator}</div> : null}
            <nav aria-label={COMMON.mainNav} className="flex flex-col gap-1">
              {items.map((item) => navLink(item, 'sheet'))}
            </nav>
          </SheetBody>
        </SheetContent>
      </Sheet>

      <main
        id="main"
        tabIndex={-1}
        data-focus-quiet
        className="page-container flex min-w-0 flex-1 flex-col py-6 outline-none md:py-8"
      >
        {children}
      </main>
    </div>
  )
}
