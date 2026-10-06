import { createFileRoute } from '@tanstack/react-router'
import { TestScreen } from '@/features/assessment'

/** C5. Тест: задание, таймер по времени сервера, ответ. */
export const Route = createFileRoute('/candidate/_focus/test/$sessionId')({
  component: Screen,
})

function Screen() {
  const { sessionId } = Route.useParams()
  return <TestScreen sessionId={sessionId} />
}
