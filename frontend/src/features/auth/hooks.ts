/**
 * Мутации сеанса. После входа и выхода кэш запросов сбрасывается целиком (кроме каталога и документов):
 * данные одного пользователя не должны достаться следующему в том же браузере.
 */
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useRouter } from '@tanstack/react-router'
import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import type { MeView } from '@/client'
import { resolveHome, safeNext } from '@/lib/guards'
import { resetSessionCache } from '@/lib/query'
import * as authApi from './api'
import { AUTH } from './content'

/** Завершить вход: записать `me`, сбросить чужой кэш и перейти на `next` либо на первый экран роли. */
export function useEnterSession() {
  const queryClient = useQueryClient()
  const router = useRouter()
  return useCallback(
    async (me: MeView, next?: string | null) => {
      resetSessionCache(queryClient, me)
      const target = safeNext(next) ?? (await resolveHome(queryClient, me))
      // Отдельно перезапускать охрану текущего маршрута не нужно: переход сам выполнит `beforeLoad` с новым `me`
      // (иначе экран входа сначала увёл бы на первый экран роли, а уже потом — на `next`).
      await router.navigate({ href: target, replace: true })
    },
    [queryClient, router],
  )
}

export function useLogin() {
  return useMutation({ mutationFn: authApi.login })
}

export function useSignup() {
  return useMutation({ mutationFn: authApi.signup })
}

export function useResendVerification() {
  return useMutation({ mutationFn: authApi.resendVerification })
}

export function useVerifyEmail() {
  return useMutation({ mutationFn: authApi.verifyEmail })
}

export function useForgotPassword() {
  return useMutation({ mutationFn: authApi.forgotPassword })
}

export function useResetPassword() {
  return useMutation({ mutationFn: authApi.resetPassword })
}

export function useChangePassword() {
  return useMutation({ mutationFn: authApi.changePassword })
}

/** Выход: сессия удаляется на сервере, кэш сбрасывается, пользователь попадает на лендинг. */
export function useLogout() {
  const queryClient = useQueryClient()
  const router = useRouter()
  return useMutation({
    mutationFn: authApi.logout,
    // Даже если запрос не прошёл (сеть), локально сеанс считаем завершённым: кабинет закрыт, cookie истечёт сама.
    onSettled: async () => {
      resetSessionCache(queryClient, null)
      await router.navigate({ to: '/' })
      toast.info(AUTH.loggedOut)
    },
  })
}

export function useDeleteAccount() {
  const queryClient = useQueryClient()
  const router = useRouter()
  return useMutation({
    mutationFn: authApi.deleteAccount,
    onSuccess: async () => {
      resetSessionCache(queryClient, null)
      await router.navigate({ to: '/' })
      toast.success(AUTH.account.deleted)
    },
  })
}

/**
 * Обратный отсчёт в секундах: «Отправить ещё раз» блокируется на 60 с (лимит писем на адрес, Арх. 10.1).
 * Считает от момента запуска по часам, а не по числу тиков, поэтому не отстаёт в фоновой вкладке.
 */
export function useCountdown() {
  const [left, setLeft] = useState(0)
  const until = useRef(0)

  useEffect(() => {
    if (left <= 0) return
    const timer = window.setInterval(() => {
      setLeft(Math.max(0, Math.ceil((until.current - Date.now()) / 1000)))
    }, 500)
    return () => window.clearInterval(timer)
  }, [left])

  const start = useCallback((seconds: number) => {
    until.current = Date.now() + seconds * 1000
    setLeft(seconds)
  }, [])

  return { left, active: left > 0, start }
}
