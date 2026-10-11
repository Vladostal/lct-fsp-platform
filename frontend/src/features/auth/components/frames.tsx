import type * as React from 'react'
import type { MeView } from '@/client'
import { CabinetLayout, type StepperStep, WizardLayout } from '@/components/app'
import { useLogout } from '../hooks'

/** Каркас кабинета с подключённым выходом из аккаунта — для маршрутов `_cabinet` и их 404. */
export function CabinetFrame({ me, children }: { me: MeView; children: React.ReactNode }) {
  const logout = useLogout()
  return (
    <CabinetLayout me={me} onLogout={() => logout.mutate()} loggingOut={logout.isPending}>
      {children}
    </CabinetLayout>
  )
}

/** Каркас мастера с подключённым выходом из аккаунта. */
export function WizardFrame({
  stepper,
  homeHref,
  children,
}: {
  stepper: { steps: readonly StepperStep[]; current: string; linkCompleted?: boolean } | null
  homeHref: string
  children: React.ReactNode
}) {
  const logout = useLogout()
  return (
    <WizardLayout stepper={stepper} homeHref={homeHref} onLogout={() => logout.mutate()} loggingOut={logout.isPending}>
      {children}
    </WizardLayout>
  )
}
