/**
 * Запросы домена `assessment` (Арх. 9.7): опрос, грейд, брифинг, сессия теста, результат, история.
 * Все вызовы идут через сгенерированный клиент; ошибки приходят как `ApiError` (lib/api.ts).
 */
import { queryOptions } from '@tanstack/react-query'
import {
  type AnswerRequest,
  assessmentCreateSession,
  assessmentGetBlueprints,
  assessmentGetHistory,
  assessmentGetResult,
  assessmentGetSession,
  assessmentGetSurvey,
  assessmentPostAnswer,
  assessmentPutClaim,
  assessmentPutSurvey,
  matchingGetOwnEvidence,
  profileGetConsents,
  profilePostPublication,
  type SurveyUpdate,
  type TestResultView,
} from '@/client'

export const assessmentKeys = {
  survey: ['assessment', 'survey'] as const,
  blueprints: ['assessment', 'blueprints'] as const,
  history: ['assessment', 'history'] as const,
  evidence: ['assessment', 'evidence'] as const,
  consents: ['assessment', 'consents'] as const,
  session: (id: string) => ['assessment', 'session', id] as const,
  result: (id: string) => ['assessment', 'result', id] as const,
}

export const surveyQuery = queryOptions({
  queryKey: assessmentKeys.survey,
  queryFn: async () => (await assessmentGetSurvey({ throwOnError: true })).data,
  staleTime: 0,
})

export const blueprintsQuery = queryOptions({
  queryKey: assessmentKeys.blueprints,
  queryFn: async () => (await assessmentGetBlueprints({ throwOnError: true })).data,
  staleTime: 60_000,
})

export const historyQuery = queryOptions({
  queryKey: assessmentKeys.history,
  queryFn: async () => (await assessmentGetHistory({ throwOnError: true })).data,
})

/** Сила профиля и статусы навыков (Арх. 11.8: вместо `profile.strength` и `profile.skill_statuses`). */
export const evidenceQuery = queryOptions({
  queryKey: assessmentKeys.evidence,
  queryFn: async () => (await matchingGetOwnEvidence({ throwOnError: true })).data,
})

export const consentsQuery = queryOptions({
  queryKey: assessmentKeys.consents,
  queryFn: async () => (await profileGetConsents({ throwOnError: true })).data,
  staleTime: 0,
})

export const sessionQuery = (id: string) =>
  queryOptions({
    queryKey: assessmentKeys.session(id),
    queryFn: async () => (await assessmentGetSession({ path: { session_id: id }, throwOnError: true })).data,
    staleTime: 0,
    gcTime: 0,
  })

export type ResultOrPending = TestResultView | { status: 'in_progress' }

export function isResult(value: ResultOrPending | undefined): value is TestResultView {
  return value != null && 'outcome' in value
}

export const resultQuery = (id: string) =>
  queryOptions({
    queryKey: assessmentKeys.result(id),
    queryFn: async (): Promise<ResultOrPending> =>
      (await assessmentGetResult({ path: { session_id: id }, throwOnError: true })).data as ResultOrPending,
    staleTime: 0,
  })

export async function putSurvey(body: SurveyUpdate) {
  return (await assessmentPutSurvey({ body, throwOnError: true })).data
}

export async function putClaim(gradeCode: string) {
  return (await assessmentPutClaim({ body: { grade_code: gradeCode }, throwOnError: true })).data
}

export async function createSession(gradeCode: string) {
  return (await assessmentCreateSession({ body: { grade_code: gradeCode }, throwOnError: true })).data
}

export async function postAnswer(sessionId: string, body: AnswerRequest) {
  return (
    await assessmentPostAnswer({
      path: { session_id: sessionId },
      body,
      headers: { 'Idempotency-Key': `${sessionId}:${body.item_id}` },
      throwOnError: true,
    })
  ).data
}

export async function grantPublication(version: string) {
  return (await profilePostPublication({ body: { action: 'grant', version }, throwOnError: true })).data
}

/** Черновик ввода в sessionStorage; недоступное хранилище не ломает экран. */
export const draft = {
  read(key: string): string | null {
    try {
      return sessionStorage.getItem(key)
    } catch {
      return null
    }
  },
  write(key: string, value: string): void {
    try {
      sessionStorage.setItem(key, value)
    } catch {
      /* хранилище недоступно: черновик не сохранится */
    }
  },
  clear(key: string): void {
    try {
      sessionStorage.removeItem(key)
    } catch {
      /* ничего */
    }
  },
}
