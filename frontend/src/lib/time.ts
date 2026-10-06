/**
 * Время сервиса (Арх. 11.4): остаток любого срока считается от времени сервера, а не от часов браузера —
 * на стенде время сервиса может быть сдвинуто демо-часами. clockOffset = me.server_now − Date.now() обновляется
 * при каждом чтении `me`, после сдвига демо-часов и из ответов сессии теста (`server_now`).
 */
import { useEffect, useState } from 'react'

let clockOffsetMs = 0

/** Запомнить время сервиса из ответа API (`server_now`, ISO 8601 в UTC). Некорректное значение игнорируется. */
export function syncServerTime(serverNowIso: string | null | undefined): void {
  if (!serverNowIso) return
  const serverMs = Date.parse(serverNowIso)
  if (Number.isNaN(serverMs)) return
  clockOffsetMs = serverMs - Date.now()
}

/** Сдвиг часов сервиса относительно часов браузера, мс. */
export function clockOffset(): number {
  return clockOffsetMs
}

/** Текущее время сервиса. */
export function serverNow(): Date {
  return new Date(Date.now() + clockOffsetMs)
}

/** Сколько миллисекунд осталось до момента `iso` по времени сервиса (отрицательное — срок прошёл). */
export function msUntil(iso: string): number {
  return Date.parse(iso) - (Date.now() + clockOffsetMs)
}

/**
 * Время сервиса, обновляемое с заданным шагом (по умолчанию раз в 30 с) — для подписей «осталось 3 дня».
 * При скрытой вкладке таймер не идёт; при возврате значение обновляется сразу.
 */
export function useServerNow(stepMs = 30_000): Date {
  const [now, setNow] = useState(() => serverNow())
  useEffect(() => {
    let timer: number | undefined
    const tick = () => setNow(serverNow())
    const start = () => {
      tick()
      timer = window.setInterval(tick, stepMs)
    }
    const stop = () => {
      if (timer !== undefined) window.clearInterval(timer)
      timer = undefined
    }
    const onVisibility = () => {
      stop()
      if (document.visibilityState === 'visible') start()
    }
    start()
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      stop()
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [stepMs])
  return now
}
