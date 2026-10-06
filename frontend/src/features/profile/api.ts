/** Запросы домена `profile`: тонкие обёртки над сгенерированным клиентом и хуки состояния. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { CandidateProfileUpdate, ConditionsUpdate, PrivacySettings, ResumeParseResult } from '@/client'
import {
  contactResumeInvitations,
  profilePostPublication,
  profilePostResume,
  profilePostVisibility,
  profilePutConditions,
  profilePutPrivacy,
  profilePutProfile,
} from '@/client'
import {
  contactSalaryHintOptions,
  matchingPreviewProfileOptions,
  profileGetAccessLogInfiniteOptions,
  profileGetConditionsOptions,
  profileGetConsentsOptions,
  profileGetPrivacyOptions,
} from '@/client/@tanstack/react-query.gen'
import { candidateProfileQuery, invitationSummaryQuery, queryKeys } from '@/lib/query'

export { candidateProfileQuery, invitationSummaryQuery }

export const conditionsQuery = profileGetConditionsOptions
export const privacyQuery = profileGetPrivacyOptions
export const consentsQuery = profileGetConsentsOptions
export const previewQuery = matchingPreviewProfileOptions
export const salaryHintQuery = contactSalaryHintOptions
export const accessLogQuery = profileGetAccessLogInfiniteOptions

export const profileQueryKey = queryKeys.candidate.profile

export async function saveProfile(body: CandidateProfileUpdate) {
  const { data } = await profilePutProfile({ body, throwOnError: true })
  return data
}

export async function saveConditions(body: ConditionsUpdate) {
  const { data } = await profilePutConditions({ body, throwOnError: true })
  return data
}

export async function uploadResume(file: File): Promise<ResumeParseResult> {
  const { data } = await profilePostResume({ body: { file }, throwOnError: true })
  return data
}

/** Ориентир вилки: `null`, когда данных для медианы мало. */
export function useSalaryHint(category?: string | null) {
  return useQuery({
    ...salaryHintQuery({ query: category ? { category } : {} }),
    staleTime: 5 * 60_000,
  })
}

/** Переключатели приватности: оптимистично, с откатом; после сохранения предпросмотр перечитывается. */
export function usePrivacyMutation(onError: (error: unknown) => void) {
  const queryClient = useQueryClient()
  const key = privacyQuery().queryKey
  return useMutation({
    mutationFn: async (patch: PrivacySettings) => {
      const { data } = await profilePutPrivacy({ body: patch, throwOnError: true })
      return data
    },
    onMutate: async (patch) => {
      await queryClient.cancelQueries({ queryKey: key })
      const previous = queryClient.getQueryData<PrivacySettings>(key)
      queryClient.setQueryData<PrivacySettings>(key, (current) => ({ ...current, ...patch }))
      return { previous }
    },
    onError: (error, _patch, context) => {
      queryClient.setQueryData(key, context?.previous)
      onError(error)
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: [{ _id: 'matchingPreviewProfile' }] })
    },
  })
}

function refreshAfterVisibility(queryClient: ReturnType<typeof useQueryClient>) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: invitationSummaryQuery.queryKey }),
    queryClient.invalidateQueries({ queryKey: consentsQuery().queryKey }),
    queryClient.invalidateQueries({ queryKey: [{ _id: 'matchingPreviewProfile' }] }),
  ])
}

export function useVisibilityMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (state: 'visible' | 'paused') => {
      const { data } = await profilePostVisibility({ body: { state }, throwOnError: true })
      return data
    },
    onSuccess: () => refreshAfterVisibility(queryClient),
  })
}

/** «Я на связи»: снять автопаузу. */
export function useResumeInvitations() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      await contactResumeInvitations({ throwOnError: true })
    },
    onSuccess: () => refreshAfterVisibility(queryClient),
  })
}

export function usePublicationConsent() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (input: { action: 'grant' | 'revoke'; version: string }) => {
      const { data } = await profilePostPublication({ body: input, throwOnError: true })
      return data
    },
    onSuccess: () => refreshAfterVisibility(queryClient),
  })
}
