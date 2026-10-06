import { createFileRoute } from '@tanstack/react-router'
import { z } from 'zod'
import { Briefing } from '@/features/assessment'

/** C4. Перед тестом: брифинг; `?grade=` — повторная попытка вне мастера. */
export const Route = createFileRoute('/candidate/_wizard/test/new')({
  validateSearch: z.object({ grade: z.string().optional().catch(undefined) }),
  component: Screen,
})

function Screen() {
  const { catalog } = Route.useRouteContext()
  const { grade } = Route.useSearch()
  return <Briefing catalog={catalog} grade={grade} />
}
