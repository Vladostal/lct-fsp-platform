import { createFileRoute, notFound } from '@tanstack/react-router'
import { ScreenStub } from '@/components/app'
import { isFeatureEnabled } from '@/lib/features'

/** C16. Короткое задание — заглушка «экран в работе»; файл целиком заменяет пакет F70. */
export const Route = createFileRoute('/candidate/_focus/pulse/$assignmentId')({
  // Экран скрыт без флага `features.pulse`.
  beforeLoad: ({ context }) => {
    if (!isFeatureEnabled(context.catalog, 'pulse')) throw notFound()
  },
  component: Screen,
})

function Screen() {
  return (
    <ScreenStub
      screen="C16"
      title="Короткое задание"
      description="Задание под требование работодателя (усиление P1)."
    />
  )
}
