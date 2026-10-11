import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { CompanyUpdate, CompanyView } from '@/client'
import { api } from '@/lib/api'
import { invalidateGuardData } from '@/lib/guards'
import { invalidateOperations, queryKeys } from '@/lib/query'

export function useSaveCompany() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: CompanyUpdate) => api.put<CompanyView>('/employer/company', body),
    onSuccess: async (company) => {
      queryClient.setQueryData(queryKeys.employer.company, company)
      // Мастер приглашения читает компанию и проверку отправки через ключи сгенерированного клиента.
      await Promise.all([
        invalidateOperations(queryClient, ['companyGetCompany', 'contactPrecheckInvitation']),
        invalidateGuardData(queryClient),
      ])
    },
  })
}
