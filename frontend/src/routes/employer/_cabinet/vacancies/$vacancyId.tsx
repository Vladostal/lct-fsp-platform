import { createFileRoute, notFound } from '@tanstack/react-router'
import { ScreenStub } from '@/components/app'
import { isFeatureEnabled } from '@/lib/features'

/** E9. Вакансия — заглушка «экран в работе»; файл целиком заменяет пакет F70. */
export const Route = createFileRoute('/employer/_cabinet/vacancies/$vacancyId')({
  // Экран скрыт без флага `features.vacancies`.
  beforeLoad: ({ context }) => {
    if (!isFeatureEnabled(context.catalog, 'vacancies')) throw notFound()
  },
  component: Screen,
})

function Screen() {
  return <ScreenStub screen="E9" title="Вакансия" description="Отклики и интересующиеся (усиление P1)." />
}
