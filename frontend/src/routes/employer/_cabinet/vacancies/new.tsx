import { createFileRoute, notFound } from '@tanstack/react-router'
import { ScreenStub } from '@/components/app'
import { isFeatureEnabled } from '@/lib/features'

/** E9. Новая вакансия — заглушка «экран в работе»; файл целиком заменяет пакет F70. */
export const Route = createFileRoute('/employer/_cabinet/vacancies/new')({
  // Экран скрыт без флага `features.vacancies`.
  beforeLoad: ({ context }) => {
    if (!isFeatureEnabled(context.catalog, 'vacancies')) throw notFound()
  },
  component: Screen,
})

function Screen() {
  return (
    <ScreenStub screen="E9" title="Новая вакансия" description="Публикация вакансии из потребности (усиление P1)." />
  )
}
