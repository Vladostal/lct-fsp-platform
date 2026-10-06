import { createFileRoute } from '@tanstack/react-router'
import { ResultScreen } from '@/features/assessment'

/** C6. Результат теста. */
export const Route = createFileRoute('/candidate/_cabinet/test/$sessionId/result')({
  component: Screen,
})

function Screen() {
  const { sessionId } = Route.useParams()
  return <ResultScreen sessionId={sessionId} />
}
