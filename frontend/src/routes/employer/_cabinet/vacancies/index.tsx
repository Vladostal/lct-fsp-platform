import { createFileRoute, notFound } from '@tanstack/react-router'
import { ScreenStub } from '@/components/app'
import { isFeatureEnabled } from '@/lib/features'

/** E9. Вакансии — заглушка «экран в работе»; файл целиком заменяет пакет F70. */
export const Route = createFileRoute('/employer/_cabinet/vacancies/')({
  // Экран скрыт без флага `features.vacancies`.
  beforeLoad: ({ context }) => {
    if (!isFeatureEnabled(context.catalog, 'vacancies')) throw notFound()
  },
  component: Screen,
})

function Screen() {
  return <ScreenStub screen="E9" title="Вакансии" description="Публикация вакансий и отклики (усиление P1)." />
}
