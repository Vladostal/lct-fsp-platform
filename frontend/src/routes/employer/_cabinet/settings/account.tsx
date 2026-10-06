import { createFileRoute } from '@tanstack/react-router'
import { AccountSettings } from '@/features/auth'

/** E10. Аккаунт работодателя: адрес, смена пароля, выход, отзыв согласия и удаление данных. */
export const Route = createFileRoute('/employer/_cabinet/settings/account')({
  component: AccountScreen,
})

function AccountScreen() {
  const { me, catalog } = Route.useRouteContext()
  return <AccountSettings me={me} reregisterCooldownDays={catalog?.limits.reregister_cooldown_days} />
}
