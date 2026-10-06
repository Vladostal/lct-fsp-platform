import { useMutation, useQuery } from '@tanstack/react-query'
import type { MeView } from '@/client'
import { api } from '@/lib/api'

export type DemoAccount = { key: string; title: string; role: string; state_label: string }
export type DemoClock = { now: string; offset_seconds: number }

export function useDemoAccounts() {
  return useQuery({
    queryKey: ['demo', 'accounts'],
    queryFn: ({ signal }) => api.get<DemoAccount[]>('/demo/accounts', { signal }),
    retry: false,
  })
}

export function useDemoLogin() {
  return useMutation({
    mutationFn: (accountKey: string) => api.post<MeView>('/demo/login', { account_key: accountKey }),
  })
}

export function useRestartScenario() {
  return useMutation({ mutationFn: () => api.post<{ restarted_at: string }>('/demo/scenario/restart') })
}

export function useDemoClock(enabled: boolean, hostKey: string) {
  return useQuery({
    queryKey: ['demo', 'clock', hostKey],
    queryFn: ({ signal }) => api.get<DemoClock>('/demo/clock', { signal }),
    enabled,
    retry: false,
  })
}

export function useAdvanceClock(hostKey: string) {
  return useMutation({
    mutationFn: ({ hours, force }: { hours: number; force?: boolean }) =>
      api.post<DemoClock>('/demo/clock/advance', { hours, force }, { headers: { 'X-Admin-Token': hostKey } }),
  })
}

export function useResetDemo(hostKey: string) {
  return useMutation({
    mutationFn: () => api.post('/demo/reset', undefined, { headers: { 'X-Admin-Token': hostKey } }),
  })
}
