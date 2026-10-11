import type * as React from 'react'
import { cn } from '@/lib/utils'
import { useScrolled } from './use-scrolled'

export type AppHeaderProps = {
  logo: React.ReactNode
  nav?: React.ReactNode
  actions?: React.ReactNode
  /** `focus` — узкая колонка теста. */
  width?: 'page' | 'focus'
}

/** Единая шапка всех каркасов: стекло, высота 56 px, линия появляется только при прокрутке. */
export function AppHeader({ logo, nav, actions, width = 'page' }: AppHeaderProps) {
  const scrolled = useScrolled()
  return (
    <header
      data-sticky="top"
      data-scrolled={scrolled}
      className="glass sticky top-0 z-20 border-b border-transparent transition-[border-color] duration-(--dur-base) data-[scrolled=true]:border-line"
    >
      <div
        className={cn(
          'flex h-14 min-w-0 items-center gap-3 md:gap-4',
          width === 'page' ? 'page-container xl:gap-6' : 'mx-auto w-full max-w-[928px] px-4 md:px-6',
        )}
      >
        {logo}
        {nav}
        <div
          className={cn('ml-auto flex min-w-0 items-center gap-2 md:gap-3', width === 'focus' ? 'flex-1' : 'shrink-0')}
        >
          {actions}
        </div>
      </div>
    </header>
  )
}
