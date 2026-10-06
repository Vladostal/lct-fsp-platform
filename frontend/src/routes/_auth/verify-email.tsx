import { createFileRoute } from '@tanstack/react-router'
import { tokenSearchSchema, VerifyEmailPanel } from '@/features/auth'

/** P4. Подтверждение адреса `/verify-email?token=` — доступно всем (ссылку из письма открывают в любом браузере). */
export const Route = createFileRoute('/_auth/verify-email')({
  validateSearch: (search) => tokenSearchSchema.parse(search),
  component: VerifyEmailScreen,
})

function VerifyEmailScreen() {
  const { token } = Route.useSearch()
  return <VerifyEmailPanel token={token} />
}
