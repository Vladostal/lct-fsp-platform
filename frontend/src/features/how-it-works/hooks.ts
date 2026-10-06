import { useMutation, useQuery } from '@tanstack/react-query'
import type { BlueprintPreview, MethodologyView, ValidationSummary } from '@/client'
import { api } from '@/lib/api'

export function useValidationSummary() {
  return useQuery({
    queryKey: ['validation', 'summary'],
    queryFn: ({ signal }) => api.get<ValidationSummary>('/validation/summary', { signal }),
    staleTime: 10 * 60_000,
    retry: false,
  })
}

export function useMethodology() {
  return useQuery({
    queryKey: ['assessment', 'methodology'],
    queryFn: ({ signal }) => api.get<MethodologyView>('/assessment/methodology', { signal }),
    staleTime: 10 * 60_000,
    retry: false,
  })
}

export function useTextPreview() {
  return useMutation({
    mutationFn: (text: string) => api.post<BlueprintPreview>('/assessment/blueprints/preview', { text }),
  })
}
