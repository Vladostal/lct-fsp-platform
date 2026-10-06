/**
 * TanStack Query: клиент, ключи запросов каркаса и опрос вместо сокетов (Арх. 11.4).
 *
 * Ключи ниже — для запросов, которые делает сам каркас (сессия, каталог, шапка кабинета, охрана маршрутов).
 * Экраны доменов берут ключи и `…Options()` из сгенерированного клиента (`src/client/@tanstack/react-query.gen.ts`);
 * чтобы обновить их после мутации, есть `invalidateOperations`.
 */
import { type Query, QueryClient, type QueryKey, queryOptions } from '@tanstack/react-query'
import type {
  AssessmentStateView,
  CandidateProfileView,
  Catalog,
  CompanyView,
  InvitationSummaryView,
  LegalDocView,
  MeView,
  NeedView,
  QuotaView,
} from '@/client'
import { api, hasStatus, isApiError } from '@/lib/api'
import { syncServerTime } from '@/lib/time'

/** Период опроса списков, статусов, сводки приглашений и квоты — раз в 20 с при видимой вкладке. */
export const POLL_MS = 20_000
/** Опрос состояния привязки ФСП ID при `sync_pending`: раз в 2 с, не дольше 30 с. */
export const FSP_SYNC_POLL_MS = 2_000
export const FSP_SYNC_POLL_MAX_MS = 30_000

const MINUTE = 60_000

/**
 * Параметры опроса для useQuery: `useQuery({ ...someOptions(), ...polling })`.
 * При скрытой вкладке опрос останавливается; при возврате фокуса данные обновляются сразу.
 */
export const polling = {
  refetchInterval: POLL_MS,
  refetchIntervalInBackground: false,
  // 'always', а не true: при возврате на вкладку статусы обновляются сразу, даже если данные ещё «свежие».
  refetchOnWindowFocus: 'always',
} as const

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        gcTime: 5 * MINUTE,
        refetchOnWindowFocus: false,
        // Повтор — только при сбое сети или сервера и один раз: ответы 4xx окончательны.
        retry: (failureCount, error) => isApiError(error) && error.isUnavailable && failureCount < 1,
      },
      mutations: {
        retry: false,
      },
    },
  })
}

/** Единственный клиент запросов приложения. */
export const queryClient = createQueryClient()

/** Ключи запросов каркаса. */
export const queryKeys = {
  me: ['me'] as const,
  catalog: ['catalog'] as const,
  legal: (doc: string) => ['legal', doc] as const,
  candidate: {
    all: ['candidate'] as const,
    profile: ['candidate', 'profile'] as const,
    assessmentState: ['candidate', 'assessment-state'] as const,
    invitationSummary: ['candidate', 'invitation-summary'] as const,
  },
  employer: {
    all: ['employer'] as const,
    company: ['employer', 'company'] as const,
    needs: ['employer', 'needs'] as const,
    quota: ['employer', 'quota'] as const,
  },
} as const

/**
 * Текущий пользователь. 401 означает «гость» (`null`), а не ошибку (Арх. 11.3). Кэш — 5 минут.
 * Каждое чтение синхронизирует время сервиса (`server_now`).
 */
export const meQuery = queryOptions({
  queryKey: queryKeys.me,
  queryFn: async ({ signal }): Promise<MeView | null> => {
    try {
      const me = await api.get<MeView>('/auth/me', { signal })
      syncServerTime(me.server_now)
      return me
    } catch (error) {
      if (hasStatus(error, 401)) return null
      throw error
    }
  },
  staleTime: 5 * MINUTE,
  retry: false,
})

/** Справочники, лимиты и флаги стенда: неизменны в пределах сеанса. */
export const catalogQuery = queryOptions({
  queryKey: queryKeys.catalog,
  queryFn: ({ signal }) => api.get<Catalog>('/catalog', { signal }),
  staleTime: Number.POSITIVE_INFINITY,
  gcTime: Number.POSITIVE_INFINITY,
})

export const legalDocQuery = (doc: string) =>
  queryOptions({
    queryKey: queryKeys.legal(doc),
    queryFn: ({ signal }) => api.get<LegalDocView>(`/legal/${encodeURIComponent(doc)}`, { signal }),
    staleTime: 10 * MINUTE,
  })

export const candidateProfileQuery = queryOptions({
  queryKey: queryKeys.candidate.profile,
  queryFn: ({ signal }) => api.get<CandidateProfileView>('/candidate/profile', { signal }),
})

export const assessmentStateQuery = queryOptions({
  queryKey: queryKeys.candidate.assessmentState,
  queryFn: ({ signal }) => api.get<AssessmentStateView>('/assessment/state', { signal }),
})

/** Сводка приглашений кандидата: счётчики, видимость, пропуски. Ничего не запускает на сервере (Арх. 4.14). */
export const invitationSummaryQuery = queryOptions({
  queryKey: queryKeys.candidate.invitationSummary,
  queryFn: ({ signal }) => api.get<InvitationSummaryView>('/candidate/invitations/summary', { signal }),
})

export const companyQuery = queryOptions({
  queryKey: queryKeys.employer.company,
  queryFn: ({ signal }) => api.get<CompanyView>('/employer/company', { signal }),
})

export const needsQuery = queryOptions({
  queryKey: queryKeys.employer.needs,
  queryFn: ({ signal }) => api.get<NeedView[]>('/employer/needs', { signal }),
})

export const quotaQuery = queryOptions({
  queryKey: queryKeys.employer.quota,
  queryFn: ({ signal }) => api.get<QuotaView>('/employer/invitations/quota', { signal }),
})

/** Идентификатор операции в ключе сгенерированного запроса (`[{ _id: 'operationId', … }]`). */
function operationId(key: QueryKey): string | null {
  const head = key[0]
  if (typeof head === 'object' && head !== null && '_id' in head) {
    const id = (head as { _id?: unknown })._id
    return typeof id === 'string' ? id : null
  }
  return null
}

/**
 * Обновить запросы сгенерированного клиента по идентификаторам операций (таблица «Что обновлять после мутации»,
 * E §10.1). Пример: `invalidateOperations(queryClient, ['getCandidateProfile', 'getCandidateConditions'])`.
 */
export function invalidateOperations(client: QueryClient, operationIds: readonly string[]): Promise<void> {
  const ids = new Set(operationIds)
  return client.invalidateQueries({
    predicate: (query: Query) => {
      const id = operationId(query.queryKey)
      return id !== null && ids.has(id)
    },
  })
}

/** Сбросить всё, что относится к сессии: вызывается при входе, выходе и 401. */
export function resetSessionCache(client: QueryClient, me: MeView | null): void {
  client.removeQueries({
    predicate: (query) =>
      query.queryKey[0] !== 'me' && query.queryKey[0] !== 'catalog' && query.queryKey[0] !== 'legal',
  })
  client.setQueryData(queryKeys.me, me)
  if (me) syncServerTime(me.server_now)
}
