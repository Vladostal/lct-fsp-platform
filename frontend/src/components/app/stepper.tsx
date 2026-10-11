import { Link } from '@tanstack/react-router'
import { Check } from 'lucide-react'
import { cn } from '@/lib/utils'

export type StepperStep = { id: string; label: string; href?: string }

export type StepperProps = {
  steps: readonly StepperStep[]
  /** Идентификатор текущего шага. */
  current: string
  /** Пройденные шаги — ссылки (пока тест не начат); false отключает переходы. */
  linkCompleted?: boolean
  /** Подпись для скринридера. */
  label?: string
  className?: string
}

/**
 * Шаги мастера (E §3.3). В широком контейнере — строка шагов, соединённых линией-пайплайном: круг 24 px,
 * пройденный — заливка и галочка, текущий — кольцо и номер (aria-current="step"), будущий — серое кольцо.
 * В узком (шагу не хватает 72 px) — «Шаг i из n · название» и полоса из n сегментов.
 * Вид переключается по ширине контейнера, а не окна.
 */
export function Stepper({ steps, current, linkCompleted = true, label = 'Шаги', className }: StepperProps) {
  const currentIndex = Math.max(
    0,
    steps.findIndex((step) => step.id === current),
  )
  const currentStep = steps[currentIndex]

  return (
    <nav data-slot="stepper" aria-label={label} className={cn('@container min-w-0', className)}>
      {/* Широкий вид */}
      <ol className="hidden min-w-0 items-start @xl:flex">
        {steps.map((step, index) => {
          const state = index < currentIndex ? 'done' : index === currentIndex ? 'current' : 'todo'
          const circle = (
            <span
              className={cn(
                'num grid size-6 shrink-0 place-items-center rounded-full border text-xs leading-none font-medium',
                state === 'done' && 'border-brand-600 bg-brand-600 text-white',
                state === 'current' && 'border-brand-600 bg-surface text-brand-700',
                state === 'todo' && 'border-line-strong bg-surface text-ink-muted',
              )}
            >
              {state === 'done' ? <Check className="size-4" strokeWidth={2.5} aria-hidden="true" /> : index + 1}
            </span>
          )
          const text = (
            <span
              className={cn(
                'min-w-[72px] px-1 text-center text-[13px] leading-5',
                state === 'current' ? 'font-medium text-ink' : 'text-ink-muted',
              )}
            >
              {step.label}
              {state === 'done' ? <span className="sr-only"> — пройден</span> : null}
            </span>
          )
          const body =
            state === 'done' && step.href && linkCompleted ? (
              <Link
                to={step.href}
                className="group flex min-h-11 flex-col items-center gap-2 rounded-md hover:[&>span:last-child]:text-brand-700"
              >
                {circle}
                {text}
              </Link>
            ) : (
              <span
                className="flex min-h-11 flex-col items-center gap-2"
                aria-current={state === 'current' ? 'step' : undefined}
              >
                {circle}
                {text}
              </span>
            )
          return (
            <li key={step.id} className="relative flex min-w-0 flex-1 flex-col items-center">
              {/* Линия-пайплайн до следующего шага: от центра круга до центра соседнего. */}
              {index < steps.length - 1 ? (
                <span
                  aria-hidden="true"
                  className={cn(
                    'absolute top-[12px] right-[calc(-50%+16px)] left-[calc(50%+16px)] border-t',
                    index < currentIndex ? 'border-brand-600' : 'border-line',
                  )}
                />
              ) : null}
              {body}
            </li>
          )
        })}
      </ol>

      {/* Компактный вид */}
      <div className="flex min-w-0 flex-col gap-2 @xl:hidden">
        <p className="type-sm min-w-0 text-ink">
          <span className="num text-ink-muted">
            Шаг {currentIndex + 1} из {steps.length}
          </span>
          <span className="text-ink-muted"> · </span>
          <span className="font-medium" aria-current="step">
            {currentStep?.label}
          </span>
        </p>
        <div className="flex gap-1" aria-hidden="true">
          {steps.map((step, index) => (
            <span
              key={step.id}
              className={cn('h-0.5 flex-1 rounded-full', index <= currentIndex ? 'bg-brand-600' : 'bg-line')}
            />
          ))}
        </div>
      </div>
    </nav>
  )
}
