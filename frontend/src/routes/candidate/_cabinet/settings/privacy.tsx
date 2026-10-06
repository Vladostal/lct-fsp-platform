import { createFileRoute } from '@tanstack/react-router'
import { PrivacySettings } from '@/features/profile'

/** C12. Приватность и согласия: показ профиля, предпросмотр глазами работодателя, журнал доступа. */
export const Route = createFileRoute('/candidate/_cabinet/settings/privacy')({
  component: Screen,
})

function Screen() {
  return <PrivacySettings />
}
