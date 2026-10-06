import { createFileRoute } from '@tanstack/react-router'
import { CompanyScreen } from '@/features/company'
import { isDemoEnabled } from '@/lib/features'

/** E1. Профиль компании в кабинете. */
export const Route = createFileRoute('/employer/_cabinet/company')({
  component: Screen,
})

function Screen() {
  const { catalog } = Route.useRouteContext()
  return <CompanyScreen mode="cabinet" demo={isDemoEnabled(catalog)} />
}
