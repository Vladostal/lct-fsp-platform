import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { PairStateItem } from '@/client'
import { polling, queryKeys } from '@/lib/query'
import { archiveNeed, createShortlist, matchingKeys, pairStatesQuery } from './api'

/**
 * Состояние пар «я — кандидат» для видимых строк (Арх. 11.4). Локальная реализация F50: когда пакет приглашений
 * (F41) выпустит `usePairStates` в `features/invitations`, достаточно заменить тело этого хука.
 */
export function usePairStates(candidateIds: readonly string[]): Map<string, PairStateItem> {
  const ids = [...new Set(candidateIds)].sort().slice(0, 100)
  const query = useQuery({ ...pairStatesQuery(ids), ...polling })
  return new Map((query.data?.items ?? []).map((item) => [item.candidate_id, item]))
}

export function useCreateShortlist(needId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Parameters<typeof createShortlist>[1]) => createShortlist(needId, body),
    onSuccess: async (snapshot) => {
      queryClient.setQueryData(matchingKeys.snapshot(snapshot.id), snapshot)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: matchingKeys.shortlists(needId) }),
        queryClient.invalidateQueries({ queryKey: matchingKeys.need(needId), exact: true }),
      ])
    },
  })
}

export function useArchiveNeed() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => archiveNeed(id),
    onSuccess: async (_need, id) => {
      await queryClient.invalidateQueries({ queryKey: matchingKeys.need(id) })
      await queryClient.invalidateQueries({ queryKey: queryKeys.employer.needs })
    },
  })
}
