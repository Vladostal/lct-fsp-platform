import { createFileRoute } from '@tanstack/react-router'
import { SignupForm, signupSearchSchema } from '@/features/auth'
import { redirectSignedIn } from '@/lib/guards'

/** P2. Регистрация `/signup?role=candidate|employer` — только для гостя. */
export const Route = createFileRoute('/_auth/signup/')({
  validateSearch: (search) => signupSearchSchema.parse(search),
  beforeLoad: ({ context }) => redirectSignedIn(context),
  component: SignupScreen,
})

function SignupScreen() {
  const { role } = Route.useSearch()
  return <SignupForm initialRole={role} />
}
