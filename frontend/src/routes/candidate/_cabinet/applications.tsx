import { createFileRoute, notFound } from '@tanstack/react-router'
import { ScreenStub } from '@/components/app'
import { isFeatureEnabled } from '@/lib/features'

/** C15. Отклики — заглушка «экран в работе»; файл целиком заменяет пакет F70. */
export const Route = createFileRoute('/candidate/_cabinet/applications')({
  // Экран скрыт без флага `features.vacancies`.
  beforeLoad: ({ context }) => {
    if (!isFeatureEnabled(context.catalog, 'vacancies')) throw notFound()
  },
  component: Screen,
})

function Screen() {
  return <ScreenStub screen="C15" title="Отклики" description="Ваши отклики на вакансии (усиление P1)." />
}
