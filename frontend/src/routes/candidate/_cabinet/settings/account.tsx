import { createFileRoute } from '@tanstack/react-router'
import { AccountSettings } from '@/features/auth'

/** C14. Аккаунт кандидата: адрес, смена пароля, выход, отзыв согласия и удаление данных. */
export const Route = createFileRoute('/candidate/_cabinet/settings/account')({
  component: AccountScreen,
})

function AccountScreen() {
  const { me, catalog } = Route.useRouteContext()
  return <AccountSettings me={me} reregisterCooldownDays={catalog?.limits.reregister_cooldown_days} />
}
