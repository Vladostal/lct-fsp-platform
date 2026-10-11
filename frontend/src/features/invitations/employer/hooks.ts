import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo } from 'react'
import type { PairStateItem } from '@/client'
import { contactInvitationsPairStatesOptions } from '@/client/@tanstack/react-query.gen'
import { invalidateOperations, queryKeys } from '@/lib/query'

const OPS = [
  'contactListEmployerInvitations',
  'contactGetEmployerInvitation',
  'contactInvitationsStats',
  'contactInvitationsQuota',
  'contactInvitationsPairStates',
  'contactPrecheckInvitation',
  'matchingGetShortlist',
  'matchingListShortlists',
  'matchingListCandidates',
  'matchingListNeeds',
  'matchingGetCandidateCard',
]

// Экраны подбора держат те же данные под своими ключами (`matchingKeys`): без них строка подборки и карточка
// показывали бы «Пригласить» до следующего опроса. Банк не трогаем: его страницы расходуют дневной лимит.
const MATCHING_KEYS = [
  ['employer', 'pair-states'],
  ['employer', 'candidate-card'],
  ['employer', 'invitation-stats'],
  queryKeys.employer.needs,
] as const

/** Обновить списки приглашений, квоту, состояния пар и подборки после отправки или отзыва. */
export function useRefreshEmployerInvitations() {
  const queryClient = useQueryClient()
  return () =>
    Promise.all([
      invalidateOperations(queryClient, OPS),
      queryClient.invalidateQueries({ queryKey: queryKeys.employer.quota }),
      ...MATCHING_KEYS.map((queryKey) => queryClient.invalidateQueries({ queryKey })),
    ])
}

/**
 * Состояния пар «я — кандидат» для строк подборки и банка (до 100 идентификаторов за запрос).
 * Возвращает словарь по `candidate_id`; пока данные грузятся, он пустой.
 */
export function usePairStates(candidateIds: readonly string[]) {
  const ids = useMemo(() => [...new Set(candidateIds)].slice(0, 100).sort(), [candidateIds])
  const query = useQuery({
    ...contactInvitationsPairStatesOptions({ query: { candidate_ids: ids.join(',') } }),
    enabled: ids.length > 0,
  })
  const states = useMemo(() => {
    const map = new Map<string, PairStateItem>()
    for (const item of query.data?.items ?? []) map.set(item.candidate_id, item)
    return map
  }, [query.data])
  return { states, isPending: ids.length > 0 && query.isPending, isError: query.isError, refetch: query.refetch }
}
