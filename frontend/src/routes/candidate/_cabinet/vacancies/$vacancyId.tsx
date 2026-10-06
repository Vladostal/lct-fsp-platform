import { createFileRoute, notFound } from '@tanstack/react-router'
import { ScreenStub } from '@/components/app'
import { isFeatureEnabled } from '@/lib/features'

/** C15. Вакансия — заглушка «экран в работе»; файл целиком заменяет пакет F70. */
export const Route = createFileRoute('/candidate/_cabinet/vacancies/$vacancyId')({
  // Экран скрыт без флага `features.vacancies`.
  beforeLoad: ({ context }) => {
    if (!isFeatureEnabled(context.catalog, 'vacancies')) throw notFound()
  },
  component: Screen,
})

function Screen() {
  return <ScreenStub screen="C15" title="Вакансия" description="Условия вакансии и отклик (усиление P1)." />
}
