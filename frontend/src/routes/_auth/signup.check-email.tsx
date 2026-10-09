import { createFileRoute, redirect } from '@tanstack/react-router'
import { CheckEmailPanel, checkEmailSearchSchema, pendingEmail } from '@/features/auth'
import { redirectSignedIn } from '@/lib/guards'

/**
 * P3. «Проверьте почту» `/signup/check-email`. Адрес берётся из хранилища вкладки (его кладёт форма регистрации),
 * а не из адресной строки: почта не должна оседать в истории браузера и журналах сервера. Параметр `?email=`
 * по-прежнему принимается — для прямых ссылок и тестов вёрстки. Без адреса — обратно на регистрацию.
 */
export const Route = createFileRoute('/_auth/signup/check-email')({
  validateSearch: (search) => checkEmailSearchSchema.parse(search),
  beforeLoad: async ({ context, search }) => {
    await redirectSignedIn(context)
    if (!search.email && !pendingEmail()) throw redirect({ to: '/signup' })
  },
  component: CheckEmailScreen,
})

function CheckEmailScreen() {
  const { email } = Route.useSearch()
  return <CheckEmailPanel email={email ?? pendingEmail() ?? ''} />
}
