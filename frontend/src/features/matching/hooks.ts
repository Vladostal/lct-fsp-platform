import { keepPreviousData, useMutation, useQueries, useQueryClient } from '@tanstack/react-query'
import type { PairStateItem } from '@/client'
import { invalidateOperations, polling, queryKeys } from '@/lib/query'
import { archiveNeed, createShortlist, matchingKeys, NEED_OPS, pairStatesQuery } from './api'

const PAIR_STATES_CHUNK = 100

/**
 * Состояние пар «я — кандидат» для видимых строк (Арх. 11.4). Локальная реализация F50: когда пакет приглашений
 * (F41) выпустит `usePairStates` в `features/invitations`, достаточно заменить тело этого хука.
 */
export function usePairStates(candidateIds: readonly string[]): Map<string, PairStateItem> {
  // Запрос принимает до 100 идентификаторов. Пачки режутся в порядке появления строк: «Показать ещё» меняет
  // только последнюю пачку, а прежние статусы остаются на экране, пока она грузится.
  const ids = [...new Set(candidateIds)]
  const chunks: string[][] = []
  for (let i = 0; i < ids.length; i += PAIR_STATES_CHUNK) chunks.push(ids.slice(i, i + PAIR_STATES_CHUNK).sort())
  const results = useQueries({
    queries: chunks.map((chunk) => ({ ...pairStatesQuery(chunk), ...polling, placeholderData: keepPreviousData })),
  })
  return new Map(results.flatMap((r) => r.data?.items ?? []).map((item) => [item.candidate_id, item]))
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
      await invalidateOperations(queryClient, NEED_OPS)
    },
  })
}
