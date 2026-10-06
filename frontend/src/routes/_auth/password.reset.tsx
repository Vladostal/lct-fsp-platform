import { createFileRoute } from '@tanstack/react-router'
import { ResetPasswordForm, tokenSearchSchema } from '@/features/auth'

/** P5a. Новый пароль по ссылке из письма `/password/reset?token=`. */
export const Route = createFileRoute('/_auth/password/reset')({
  validateSearch: (search) => tokenSearchSchema.parse(search),
  component: ResetPasswordScreen,
})

function ResetPasswordScreen() {
  const { token } = Route.useSearch()
  return <ResetPasswordForm token={token} />
}
