import { createFileRoute, Outlet } from '@tanstack/react-router'
import { WIZARD_STEPS } from '@/content/common'
import { WizardFrame } from '@/features/auth'

/** Каркас Wizard работодателя: первый запуск «Компания → Потребность → Подборка» (E §2.3). */
export const Route = createFileRoute('/employer/_wizard')({
  component: EmployerWizard,
})

function EmployerWizard() {
  return (
    <WizardFrame homeHref="/employer/needs" stepper={{ steps: WIZARD_STEPS.employer, current: 'company' }}>
      <Outlet />
    </WizardFrame>
  )
}
