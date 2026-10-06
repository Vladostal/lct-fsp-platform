import { createFileRoute } from '@tanstack/react-router'
import { CategoryScreen } from '@/features/assessment'

/** C10. Категория и тесты. */
export const Route = createFileRoute('/candidate/_cabinet/category')({
  component: Screen,
})

function Screen() {
  const { catalog } = Route.useRouteContext()
  return <CategoryScreen catalog={catalog} />
}
