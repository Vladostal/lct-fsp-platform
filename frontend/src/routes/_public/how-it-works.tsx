import { createFileRoute } from '@tanstack/react-router'
import { HowItWorks } from '@/features/how-it-works'
import { isDemoEnabled } from '@/lib/features'

/** P6. Как это работает: три механики и числа валидации. */
export const Route = createFileRoute('/_public/how-it-works')({
  component: Screen,
})

function Screen() {
  const { catalog, me } = Route.useRouteContext()
  // Предпросмотр плана сервер отдаёт гостю и работодателю; кандидату — 403, ему показываем готовый пример.
  return <HowItWorks limits={catalog?.limits ?? {}} demo={isDemoEnabled(catalog) && me?.role !== 'candidate'} />
}
