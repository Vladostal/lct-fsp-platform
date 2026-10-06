import { createFileRoute, Outlet, useLocation } from '@tanstack/react-router'
import { WIZARD_STEPS } from '@/content/common'
import { WizardFrame } from '@/features/auth'
import { onboardingStep } from '@/lib/guards'

/**
 * Каркас Wizard кандидата: степпер «Профиль → Опрос → Грейд → Тест → Категория», колонка 720 px.
 * Пройденные шаги — ссылки, пока тест не начат. Если мастер уже пройден (повторная попытка с брифинга),
 * степпер не показывается: экран рисует хлебные крошки.
 */
export const Route = createFileRoute('/candidate/_wizard')({
  component: CandidateWizard,
})

const STEP_BY_PATH: Record<string, string> = {
  '/candidate/onboarding/profile': 'profile',
  '/candidate/onboarding/survey': 'survey',
  '/candidate/onboarding/grade': 'grade',
  '/candidate/test/new': 'test',
}

function CandidateWizard() {
  const { homeData } = Route.useRouteContext()
  const pathname = useLocation({ select: (location) => location.pathname })
  const current = STEP_BY_PATH[pathname.replace(/\/$/, '')] ?? 'profile'
  const done = homeData.profile && homeData.state ? onboardingStep(homeData.profile, homeData.state) === 'done' : false

  return (
    <WizardFrame
      homeHref="/candidate"
      stepper={done ? null : { steps: WIZARD_STEPS.candidate, current, linkCompleted: !homeData.state?.active_session }}
    >
      <Outlet />
    </WizardFrame>
  )
}
