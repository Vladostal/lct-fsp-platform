import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { contactResumeInvitationsMutation, profilePostVisibilityMutation } from '@/client/@tanstack/react-query.gen'
import { errorMessage, isApiError } from '@/lib/api'
import { invalidateOperations, queryKeys } from '@/lib/query'

const OPS = [
  'contactListCandidateInvitations',
  'contactGetCandidateInvitation',
  'contactCandidateFunnel',
  'contactCandidateInvitationsSummary',
  'profileGetConsents',
  'assessmentGetState',
]

/** Обновить всё, что зависит от приглашений кандидата: списки, сводку шапки, воронку, видимость. */
export function useRefreshCandidateInvitations() {
  const queryClient = useQueryClient()
  return () =>
    Promise.all([
      invalidateOperations(queryClient, OPS),
      queryClient.invalidateQueries({ queryKey: queryKeys.candidate.invitationSummary }),
    ])
}

/** «Я на связи» (снимает автопаузу) и «Возобновить показ» (снимает ручную паузу). */
export function useResumeVisibility(kind: 'resume' | 'visible') {
  const refresh = useRefreshCandidateInvitations()
  const resume = useMutation(contactResumeInvitationsMutation())
  const visible = useMutation(profilePostVisibilityMutation())
  const mutation = kind === 'resume' ? resume : visible
  const run = () => {
    const onSuccess = () => {
      void refresh()
      toast.success('Показ профиля возобновлён')
    }
    const onError = (error: unknown) =>
      toast.error(isApiError(error) ? errorMessage(error) : 'Не удалось выполнить действие')
    if (kind === 'resume') resume.mutate({}, { onSuccess, onError })
    else visible.mutate({ body: { state: 'visible' } }, { onSuccess, onError })
  }
  return { run, pending: mutation.isPending }
}
