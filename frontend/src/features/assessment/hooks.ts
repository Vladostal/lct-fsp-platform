import { useQuery } from '@tanstack/react-query'
import { assessmentStateQuery } from '@/lib/query'
import { sessionQuery } from './api'

/** Состояние опроса, грейда, категории и действий (для блоков обзора, F40). */
export function useAssessmentState() {
  return useQuery(assessmentStateQuery)
}

/** Сессия теста по идентификатору. */
export function useTestSession(id: string) {
  return useQuery(sessionQuery(id))
}
