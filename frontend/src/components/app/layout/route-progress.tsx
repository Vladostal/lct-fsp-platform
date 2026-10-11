import { useRouterState } from '@tanstack/react-router'
import { useEffect, useState } from 'react'

/** Тонкая полоса сверху при загрузке маршрута; показывается после 120 мс, чтобы быстрые переходы не мигали. */
export function RouteProgress() {
  const pending = useRouterState({ select: (s) => s.status === 'pending' })
  const [shown, setShown] = useState(false)
  const [done, setDone] = useState(false)

  useEffect(() => {
    if (pending) {
      setDone(false)
      const t = window.setTimeout(() => setShown(true), 120)
      return () => window.clearTimeout(t)
    }
    if (!shown) return
    setDone(true)
    const t = window.setTimeout(() => setShown(false), 260)
    return () => window.clearTimeout(t)
  }, [pending, shown])

  if (!shown) return null
  return (
    <div
      aria-hidden="true"
      data-done={done ? '' : undefined}
      className="route-progress pointer-events-none fixed inset-x-0 top-0 z-50 h-0.5 bg-brand-600"
    />
  )
}
