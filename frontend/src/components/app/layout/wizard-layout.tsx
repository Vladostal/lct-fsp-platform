import { LogOut } from 'lucide-react'
import type * as React from 'react'
import { Button } from '@/components/ui/button'
import { COMMON } from '@/content/common'
import { AppLogo } from '../app-logo'
import { type Crumb, PageHeader } from '../page-header'
import { Stepper, type StepperStep } from '../stepper'
import { SkipLink } from './skip-link'

export type WizardLayoutProps = {
  /** Шаги мастера и текущий шаг; null — степпер не показывается (повторная попытка теста: вместо него крошки). */
  stepper: { steps: readonly StepperStep[]; current: string; linkCompleted?: boolean } | null
  /** Куда ведёт логотип. */
  homeHref: string
  onLogout: () => void
  loggingOut?: boolean
  children: React.ReactNode
}

/**
 * Каркас Wizard (E §1.2, §2.2): шапка с логотипом и «Выйти» (навигации кабинета нет), степпер,
 * колонка 720 px. Липкую панель действий (StickyActionBar) рисует сам шаг.
 */
export function WizardLayout({ stepper, homeHref, onLogout, loggingOut = false, children }: WizardLayoutProps) {
  return (
    <div className="flex min-h-dvh flex-col bg-canvas">
      <SkipLink />
      <header data-sticky="top" className="sticky top-0 z-20 border-b border-line bg-surface">
        <div className="page-container flex h-14 items-center justify-between gap-4 md:h-16">
          <AppLogo href={homeHref} compact />
          <Button variant="ghost" size="sm" onClick={onLogout} loading={loggingOut}>
            <LogOut aria-hidden="true" />
            {COMMON.logout}
          </Button>
        </div>
      </header>
      <div className="mx-auto flex w-full max-w-[768px] min-w-0 flex-1 flex-col gap-6 px-4 py-6 md:gap-8 md:px-6 md:py-8">
        {stepper ? (
          <Stepper
            steps={stepper.steps}
            current={stepper.current}
            linkCompleted={stepper.linkCompleted}
            label="Шаги регистрации"
          />
        ) : null}
        <main id="main" tabIndex={-1} data-focus-quiet className="flex min-w-0 flex-1 flex-col outline-none">
          {children}
        </main>
      </div>
    </div>
  )
}

export type WizardStepProps = {
  title: string
  description?: React.ReactNode
  breadcrumbs?: readonly Crumb[]
  children: React.ReactNode
}

/** Содержимое шага мастера: заголовок шага и блоки столбцом. */
export function WizardStep({ title, description, breadcrumbs, children }: WizardStepProps) {
  return (
    <div className="flex min-w-0 animate-fade-in flex-col gap-6">
      <PageHeader title={title} description={description} breadcrumbs={breadcrumbs} />
      {children}
    </div>
  )
}
