import type * as React from 'react'
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { APP_NAME } from '@/lib/config'
import { SkipLink } from './skip-link'

const SLOT_ID = 'focus-header-slot'

/**
 * Каркас Focus (E §1.2): узкая шапка 56 px с прогрессом и таймером, без навигации; колонка 880 px.
 * Логотип здесь не ссылка: уход со страницы во время теста не должен случаться от случайного нажатия.
 * Прогресс и таймер экран передаёт в шапку через <FocusHeaderSlot>.
 */
export function FocusLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col bg-canvas">
      <SkipLink />
      <header data-sticky="top" className="sticky top-0 z-20 border-b border-line bg-surface">
        <div className="mx-auto flex h-14 w-full max-w-[928px] min-w-0 items-center gap-4 px-4 md:px-6">
          <img
            src="/logo_mobile.svg"
            alt={`ФСП · ${APP_NAME}`}
            width={83}
            height={28}
            className="h-7 w-auto shrink-0"
          />
          <div id={SLOT_ID} className="flex min-w-0 flex-1 items-center justify-end gap-4" />
        </div>
      </header>
      <main
        id="main"
        tabIndex={-1}
        data-focus-quiet
        className="mx-auto flex w-full max-w-[928px] min-w-0 flex-1 flex-col px-4 py-6 outline-none md:px-6 md:py-8"
      >
        {children}
      </main>
    </div>
  )
}

/** Содержимое для шапки каркаса Focus: «7 из 14», полоса прогресса, таймер. */
export function FocusHeaderSlot({ children }: { children: React.ReactNode }) {
  const [target, setTarget] = useState<HTMLElement | null>(null)
  useEffect(() => {
    setTarget(document.getElementById(SLOT_ID))
  }, [])
  return target ? createPortal(children, target) : null
}
