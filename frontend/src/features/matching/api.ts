/**
 * Запросы домена `matching` (Арх. 9.8). Типы — из `src/client`; вызовы идут через `api` каркаса,
 * как и в домене `auth` (так ошибки всегда приходят как `ApiError`).
 */
import { infiniteQueryOptions, queryOptions } from '@tanstack/react-query'
import type {
  BankPage,
  BlueprintPreview,
  BlueprintPreviewRequest,
  CandidateCardEmployerView,
  InvitationStatsView,
  NeedCreate,
  NeedDraft,
  NeedInsightsView,
  NeedUpdate,
  NeedView,
  PairStatesView,
  SalaryHint,
  ShortlistCreate,
  ShortlistSnapshotView,
  ShortlistVersionBrief,
} from '@/client'
import { api } from '@/lib/api'
import { queryKeys } from '@/lib/query'

const root = queryKeys.employer.needs

export const matchingKeys = {
  need: (id: string) => [...root, id] as const,
  shortlists: (id: string) => [...root, id, 'shortlists'] as const,
  snapshot: (id: string) => ['employer', 'shortlist', id] as const,
  insights: (id: string) => [...root, id, 'insights'] as const,
  card: (candidateId: string, needId?: string, snapshotId?: string) =>
    ['employer', 'candidate-card', candidateId, needId ?? null, snapshotId ?? null] as const,
  pairStates: (ids: readonly string[]) => ['employer', 'pair-states', ...ids] as const,
  stats: ['employer', 'invitation-stats'] as const,
  hint: (category: string) => ['contact', 'salary-hint', category] as const,
  bank: (filters: unknown) => ['employer', 'bank', filters] as const,
}

/** Те же данные потребности под ключами сгенерированного клиента (мастер приглашения, фильтр списка приглашений). */
export const NEED_OPS = ['matchingGetNeed', 'matchingListNeeds', 'contactPrecheckInvitation'] as const

export const needQuery = (id: string) =>
  queryOptions({
    queryKey: matchingKeys.need(id),
    queryFn: ({ signal }) => api.get<NeedView>(`/employer/needs/${id}`, { signal }),
  })

export const shortlistsQuery = (id: string) =>
  queryOptions({
    queryKey: matchingKeys.shortlists(id),
    queryFn: ({ signal }) => api.get<ShortlistVersionBrief[]>(`/employer/needs/${id}/shortlists`, { signal }),
  })

/** Версия подборки неизменяема: кэшируется надолго, живые поля обновляет опрос. */
export const snapshotQuery = (id: string) =>
  queryOptions({
    queryKey: matchingKeys.snapshot(id),
    queryFn: ({ signal }) => api.get<ShortlistSnapshotView>(`/employer/shortlists/${id}`, { signal }),
    staleTime: 5 * 60_000,
  })

export const insightsQuery = (id: string) =>
  queryOptions({
    queryKey: matchingKeys.insights(id),
    queryFn: ({ signal }) => api.get<NeedInsightsView>(`/employer/needs/${id}/insights`, { signal }),
  })

export const statsQuery = queryOptions({
  queryKey: matchingKeys.stats,
  queryFn: ({ signal }) => api.get<InvitationStatsView>('/employer/invitations/stats', { signal }),
})

export const cardQuery = (candidateId: string, needId?: string, snapshotId?: string) =>
  queryOptions({
    queryKey: matchingKeys.card(candidateId, needId, snapshotId),
    queryFn: ({ signal }) =>
      api.get<CandidateCardEmployerView>(`/employer/candidates/${candidateId}`, {
        query: { need_id: needId, snapshot_id: snapshotId },
        signal,
      }),
  })

export const pairStatesQuery = (ids: readonly string[]) =>
  queryOptions({
    queryKey: matchingKeys.pairStates(ids),
    queryFn: ({ signal }) =>
      api.get<PairStatesView>('/employer/invitations/pair-states', { query: { candidate_ids: ids.join(',') }, signal }),
    enabled: ids.length > 0,
  })

export const salaryHintQuery = (category: string) =>
  queryOptions({
    queryKey: matchingKeys.hint(category),
    queryFn: ({ signal }) => api.get<SalaryHint | null>('/contact/salary-hint', { query: { category }, signal }),
    staleTime: 10 * 60_000,
  })

export type BankFilters = {
  category?: string
  specialization?: string
  grade?: string
  skills?: string
  confirmed?: boolean
  fsp?: boolean
  code?: string
}

export const bankQuery = (f: BankFilters) =>
  infiniteQueryOptions({
    queryKey: matchingKeys.bank(f),
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) =>
      api.get<BankPage>('/employer/candidates', {
        query: {
          category: f.category,
          specialization: f.specialization,
          grade: f.grade,
          skills: f.skills,
          skills_confirmed_only: f.confirmed || undefined,
          has_fsp: f.fsp || undefined,
          code: f.code,
          cursor: pageParam,
          limit: 20,
        },
        signal,
      }),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  })

export const parseNeed = (text: string) => api.post<NeedDraft>('/employer/needs/parse', { text })
export const createNeed = (body: NeedCreate) => api.post<NeedView>('/employer/needs', body)
export const updateNeed = (id: string, body: NeedUpdate) => api.put<NeedView>(`/employer/needs/${id}`, body)
export const archiveNeed = (id: string) => api.post<NeedView>(`/employer/needs/${id}/archive`)
export const createShortlist = (id: string, body: ShortlistCreate) =>
  api.post<ShortlistSnapshotView>(`/employer/needs/${id}/shortlists`, body)
export const pinCandidate = (needId: string, candidateId: string) =>
  api.put(`/employer/needs/${needId}/pins/${candidateId}`)
export const unpinCandidate = (needId: string, candidateId: string) =>
  api.delete(`/employer/needs/${needId}/pins/${candidateId}`)
export const previewBlueprint = (body: BlueprintPreviewRequest, signal?: AbortSignal) =>
  api.post<BlueprintPreview>('/assessment/blueprints/preview', body, { signal })
