import type * as React from 'react'
import { useState } from 'react'
import { cn } from '@/lib/utils'

export type RevealOnceProps = {
  /** Ключ в sessionStorage: подсветка играет один раз за сессию. */
  storageKey: string
  children: React.ReactNode
  className?: string
}

/** При первом показе в сессии даёт data-reveal="first" (фон brand-50 → transparent), потом ничего. */
export function RevealOnce({ storageKey, children, className }: RevealOnceProps) {
  const [first] = useState(() => {
    try {
      const key = `reveal:${storageKey}`
      if (sessionStorage.getItem(key)) return false
      sessionStorage.setItem(key, '1')
      return true
    } catch {
      return false
    }
  })
  return (
    <div data-reveal={first ? 'first' : undefined} className={cn('rounded-md', className)}>
      {children}
    </div>
  )
}
