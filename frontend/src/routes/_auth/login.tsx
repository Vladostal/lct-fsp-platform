import { createFileRoute } from '@tanstack/react-router'
import { LoginForm, loginSearchSchema } from '@/features/auth'
import { isDemoEnabled } from '@/lib/features'
import { redirectSignedIn, safeNext } from '@/lib/guards'

/** P5. Вход `/login?next=` — только для гостя; `next` принимается, только если это путь внутри сайта. */
export const Route = createFileRoute('/_auth/login')({
  validateSearch: (search) => loginSearchSchema.parse(search),
  beforeLoad: ({ context }) => redirectSignedIn(context),
  component: LoginScreen,
})

function LoginScreen() {
  const { next } = Route.useSearch()
  const { catalog } = Route.useRouteContext()
  return <LoginForm next={safeNext(next)} demo={isDemoEnabled(catalog)} />
}
