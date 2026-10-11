import { useMutation, useQuery } from '@tanstack/react-query'
import type { MeView } from '@/client'
import { api } from '@/lib/api'

export type DemoAccount = { key: string; title: string; role: string; state_label: string }

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
