import { createFileRoute } from '@tanstack/react-router'
import { ProfileCabinet } from '@/features/profile'

/** C11. Профиль и резюме в кабинете. */
export const Route = createFileRoute('/candidate/_cabinet/profile')({
  component: Screen,
})

function Screen() {
  const { me, catalog, homeData } = Route.useRouteContext()
  return <ProfileCabinet userId={me.id} catalog={catalog ?? null} category={homeData.state?.category?.code ?? null} />
}
