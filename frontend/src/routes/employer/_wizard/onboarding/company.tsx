import { createFileRoute } from '@tanstack/react-router'
import { CompanyScreen } from '@/features/company'
import { isDemoEnabled } from '@/lib/features'

/** E1. Профиль компании, первый запуск (мастер). */
export const Route = createFileRoute('/employer/_wizard/onboarding/company')({
  component: Screen,
})

function Screen() {
  const { catalog } = Route.useRouteContext()
  return <CompanyScreen mode="wizard" demo={isDemoEnabled(catalog)} />
}
