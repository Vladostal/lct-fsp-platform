import { createFileRoute, redirect } from '@tanstack/react-router'
import { CheckEmailPanel, checkEmailSearchSchema } from '@/features/auth'
import { redirectSignedIn } from '@/lib/guards'

/** P3. «Проверьте почту» `/signup/check-email?email=`; без адреса в параметре — обратно на регистрацию. */
export const Route = createFileRoute('/_auth/signup/check-email')({
  validateSearch: (search) => checkEmailSearchSchema.parse(search),
  beforeLoad: async ({ context, search }) => {
    await redirectSignedIn(context)
    if (!search.email) throw redirect({ to: '/signup' })
  },
  component: CheckEmailScreen,
})

function CheckEmailScreen() {
  const { email } = Route.useSearch()
  return <CheckEmailPanel email={email ?? ''} />
}
