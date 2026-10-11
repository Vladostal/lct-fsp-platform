import { createFileRoute, Link, redirect } from '@tanstack/react-router'
import { ArrowDown, ArrowRight, ClipboardCheck, Search, Send } from 'lucide-react'
import { EvidenceChip, usePageTitle } from '@/components/app'
import { Button } from '@/components/ui/button'
import { resolveHome } from '@/lib/guards'
import { HeroFlow } from './-hero-flow'

/** P1. Лендинг: за один экран объясняет обратную механику и разводит по ролям. Вошедший уходит на свой первый экран. */
export const Route = createFileRoute('/_public/')({
  beforeLoad: async ({ context }) => {
    if (context.me) throw redirect({ href: await resolveHome(context.queryClient, context.me) })
  },
  component: Landing,
})

const STEPS = [
  {
    icon: ClipboardCheck,
    title: 'Тест подтверждает грейд',
    text: 'Вы выбираете грейд — тест его проверяет. Где теста пока нет, грейд помечен как заявленный.',
  },
  {
    icon: Search,
    title: 'Работодатель находит вас',
    text: 'Описывает, кого ищет, и получает подборку. Видит код, а не имя.',
  },
  {
    icon: Send,
    title: 'Приглашение с вилкой',
    text: 'Зарплата и формат — сразу. Контакты — после вашего согласия.',
  },
] as const

/* Стрелки между шагами слегка «подталкивают» вперёд; без анимации (reduce) стоят на месте. */
const STEPS_CSS = `
@media (prefers-reduced-motion: no-preference){
  .st-x{animation:st-x 1.8s ease-in-out infinite}
  .st-y{animation:st-y 1.8s ease-in-out infinite}
}
@keyframes st-x{0%,100%{transform:none}50%{transform:translateX(4px)}}
@keyframes st-y{0%,100%{transform:none}50%{transform:translateY(4px)}}
`

function Landing() {
  usePageTitle(null)

  return (
    <>
      <section className="page-container grid items-center gap-10 pt-10 pb-4 md:pt-16 md:pb-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,440px)] lg:gap-16">
        <div className="flex min-w-0 flex-col gap-8">
          <h1 data-page-title tabIndex={-1} className="type-display text-ink outline-none">
            Платформа <span className="min-[360px]:whitespace-nowrap">ИТ-специалистов,</span> проверенных ФСП
          </h1>
          <div className="flex min-w-0 flex-col gap-3 min-[480px]:flex-row min-[480px]:flex-wrap">
            <Button variant="primary" size="lg" asChild>
              <Link to="/signup" search={{ role: 'candidate' }}>
                Я ИТ-специалист
                <ArrowRight aria-hidden="true" />
              </Link>
            </Button>
            <Button variant="secondary" size="lg" asChild>
              <Link to="/signup" search={{ role: 'employer' }}>
                Я работодатель
              </Link>
            </Button>
          </div>
        </div>
        <HeroFlow />
      </section>

      <section aria-labelledby="steps-title" className="page-container flex flex-col gap-8 py-10 md:py-14">
        <h2 id="steps-title" className="type-h1 text-ink">
          Три шага от теста до приглашения
        </h2>
        <style>{STEPS_CSS}</style>
        <ol className="grid min-w-0 gap-10 lg:grid-cols-3 lg:gap-12">
          {STEPS.map((step, index) => (
            <li
              key={step.title}
              style={{ '--i': index } as React.CSSProperties}
              className="surface-row stagger group relative flex min-w-0 animate-rise-in flex-col gap-3 rounded-lg p-5 transition-[border-color,translate] duration-200 hover:-translate-y-1 hover:border-brand-600 md:rounded-xl md:p-6"
            >
              <div className="flex items-center justify-between gap-3">
                <span className="flex size-11 items-center justify-center rounded-md bg-brand-50 text-brand-700 transition-colors duration-200 group-hover:bg-brand-600 group-hover:text-on-brand">
                  <step.icon className="size-5" aria-hidden="true" />
                </span>
                <span aria-hidden="true" className="num text-[2rem] leading-none font-semibold text-brand-600">
                  {String(index + 1).padStart(2, '0')}
                </span>
              </div>
              <h3 className="type-h3 text-ink">{step.title}</h3>
              <p className="type-body text-ink-muted">{step.text}</p>
              {index < STEPS.length - 1 ? (
                <span
                  aria-hidden="true"
                  className="absolute -bottom-8 left-1/2 flex size-6 -translate-x-1/2 items-center justify-center text-brand-600 lg:top-1/2 lg:-right-9 lg:bottom-auto lg:left-auto lg:translate-x-0 lg:-translate-y-1/2"
                >
                  <ArrowDown className="st-y size-5 lg:hidden" />
                  <ArrowRight className="st-x hidden size-5 lg:block" />
                </span>
              ) : null}
            </li>
          ))}
        </ol>
      </section>

      <section aria-label="Источники сведений" className="page-container pb-12 md:pb-16">
        <div className="flex min-w-0 flex-col gap-4 border-t border-line pt-8 md:flex-row md:items-center md:justify-between">
          <ul className="flex min-w-0 flex-wrap gap-x-5 gap-y-2">
            <li>
              <EvidenceChip kind="test" />
            </li>
            <li>
              <EvidenceChip kind="fsp" />
            </li>
            <li>
              <EvidenceChip kind="declared" />
            </li>
          </ul>
          <Link
            to="/how-it-works"
            className="type-body inline-flex min-h-11 items-center gap-2 text-brand-700 hover:underline"
          >
            Как считается грейд и строится подборка
            <ArrowRight className="size-4" aria-hidden="true" />
          </Link>
        </div>
      </section>
    </>
  )
}
