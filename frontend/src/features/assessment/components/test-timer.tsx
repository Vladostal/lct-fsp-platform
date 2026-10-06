import { Clock } from 'lucide-react'
import { useEffect, useState } from 'react'
import { formatTimer } from '@/lib/format'
import { cn } from '@/lib/utils'
import { ASSESSMENT } from '../content'

/**
 * Остаток времени от абсолютного момента `expiresAt` по часам сервера: `offset = server_now − Date.now()`
 * считается в момент каждого ответа сервера, пересчёт — каждые 250 мс.
 */
export function useTestRemaining(expiresAt: string | null, offsetMs: number): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 250)
    return () => window.clearInterval(id)
  }, [])
  if (!expiresAt) return Number.POSITIVE_INFINITY
  return new Date(expiresAt).getTime() - (now + offsetMs)
}

/** Таймер теста: MM:SS, tabular-nums; при ≤ 300 и ≤ 60 с — подпись и одно объявление на порог. */
export function TestTimer({ remainingMs }: { remainingMs: number }) {
  const [announce, setAnnounce] = useState('')
  const seconds = remainingMs / 1000
  const hint = seconds <= 60 ? ASSESSMENT.test.oneMin : seconds <= 300 ? ASSESSMENT.test.fiveMin : null
  useEffect(() => {
    setAnnounce(hint ?? '')
  }, [hint])
  return (
    <div className="flex min-w-0 shrink-0 items-center gap-2">
      {hint ? (
        <span className="type-caption hidden text-warning sm:inline" aria-hidden="true">
          {hint}
        </span>
      ) : null}
      <span
        className={cn(
          'num type-body flex items-center gap-1.5 font-medium tabular-nums',
          hint ? 'text-warning' : 'text-ink',
        )}
      >
        <Clock className="size-4" aria-hidden="true" />
        <span className="sr-only">Осталось </span>
        {formatTimer(remainingMs)}
      </span>
      <span className="sr-only" aria-live="polite">
        {announce}
      </span>
    </div>
  )
}
