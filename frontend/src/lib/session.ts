/**
 * Сеанс пользователя на клиенте: реакция на 401 и выход (Арх. 11.3).
 *
 * 401 на любой запрос кабинета: кэш `me` очищается, пользователь уходит на вход с `next` и видит
 * «Сессия истекла. Войдите снова». В сессии демо-аккаунта 401 означает перезапуск сценария: переход на /demo
 * с текстом «сценарий перезапущен — войдите снова» (Арх. 11.8).
 */
import type { MeView } from '@/client'
import { type ApiError, setUnauthorizedHandler } from '@/lib/api'
import { loginHref } from '@/lib/guards'
import { queryClient, queryKeys, resetSessionCache } from '@/lib/query'

/** Запросы, для которых 401 — штатный ответ формы, а не потеря сессии. */
const PUBLIC_AUTH_PATHS = ['/auth/me', '/auth/login', '/auth/verify-email', '/auth/signup', '/demo/login']

type SessionLostListener = (target: { href: string; reason: 'expired' | 'demo_restarted' }) => void

let listener: SessionLostListener | null = null
let handling = false

/** Подключить реакцию на потерю сессии; `onLost` выполняет переход и показывает сообщение. */
export function installSessionGuard(onLost: SessionLostListener): void {
  listener = onLost
  setUnauthorizedHandler((_error: ApiError, request: Request | undefined) => {
    const url = request?.url ?? ''
    if (PUBLIC_AUTH_PATHS.some((path) => url.includes(path))) return
    const me = queryClient.getQueryData<MeView | null>(queryKeys.me)
    // Гость и так не в кабинете; параллельные 401 одной страницы обрабатываются один раз.
    if (!me || handling) return
    handling = true
    resetSessionCache(queryClient, null)
    const here = `${window.location.pathname}${window.location.search}`
    listener?.(
      me.is_demo
        ? { href: '/demo?restarted=1', reason: 'demo_restarted' }
        : { href: loginHref(here), reason: 'expired' },
    )
    window.setTimeout(() => {
      handling = false
    }, 1000)
  })
}
