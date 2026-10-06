/** Запросы домена `fsp` и хук состояния привязки (C13). */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { fspDeleteLink, fspPostSync, fspStartLink } from '@/client'
import {
  fspGetCalendarOptions,
  fspGetConsentOptions,
  fspGetLinkOptions,
  profileGetPrivacyOptions,
} from '@/client/@tanstack/react-query.gen'
import { FSP_SYNC_POLL_MAX_MS, FSP_SYNC_POLL_MS } from '@/lib/query'

export const fspLinkQuery = fspGetLinkOptions
export const fspConsentQuery = fspGetConsentOptions
export const fspCalendarQuery = fspGetCalendarOptions
export const fspPrivacyQuery = profileGetPrivacyOptions

/**
 * Состояние привязки ФСП ID. При `sync_pending` опрашивает сервер раз в 2 с, но не дольше 30 с:
 * дальше экран остаётся в ожидании без запросов, пока пользователь не обновит страницу.
 */
export function useFspLink() {
  const startedAt = useRef<number | null>(null)
  const query = useQuery({
    ...fspLinkQuery(),
    retry: false,
    refetchInterval: (q) => {
      if (q.state.data?.history_status !== 'sync_pending') return false
      startedAt.current ??= Date.now()
      return Date.now() - startedAt.current < FSP_SYNC_POLL_MAX_MS ? FSP_SYNC_POLL_MS : false
    },
  })
  const pending = query.data?.history_status === 'sync_pending'
  useEffect(() => {
    if (!pending) startedAt.current = null
  }, [pending])
  return query
}

function useLinkRefresh() {
  const queryClient = useQueryClient()
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: fspLinkQuery().queryKey }),
      queryClient.invalidateQueries({ queryKey: [{ _id: 'matchingPreviewProfile' }] }),
      queryClient.invalidateQueries({ queryKey: ['candidate'] }),
    ])
}

/** Начать привязку: после ответа браузер уходит на `authorize_url`. */
export function useStartFspLink() {
  return useMutation({
    mutationFn: async (consentVersion: string) => {
      const { data } = await fspStartLink({
        body: { accept: true, consent_version: consentVersion },
        throwOnError: true,
      })
      return data
    },
    onSuccess: (data) => window.location.assign(data.authorize_url),
  })
}

export function useFspSync() {
  const refresh = useLinkRefresh()
  return useMutation({
    mutationFn: async () => {
      const { data } = await fspPostSync({ throwOnError: true })
      return data
    },
    onSettled: () => refresh(),
  })
}

export function useFspUnlink() {
  const refresh = useLinkRefresh()
  return useMutation({
    mutationFn: async () => {
      await fspDeleteLink({ throwOnError: true })
    },
    onSuccess: () => refresh(),
  })
}
