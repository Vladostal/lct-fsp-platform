import { createFileRoute, Link, redirect } from '@tanstack/react-router'
import { ArrowRight, BadgeCheck, Lock, MailCheck, Search } from 'lucide-react'
import { CategoryChip, EvidenceChip, PipelineLine, SalaryRange, StatusBadge, usePageTitle } from '@/components/app'
import { Button } from '@/components/ui/button'
import { resolveHome } from '@/lib/guards'

/** P1. Лендинг: за один экран объясняет обратную механику и разводит по ролям. Вошедший уходит на свой первый экран. */
export const Route = createFileRoute('/_public/')({
  beforeLoad: async ({ context }) => {
    if (context.me) throw redirect({ href: await resolveHome(context.queryClient, context.me) })
  },
  component: Landing,
})

const STEPS = [
  {
    icon: BadgeCheck,
    title: 'Тест подтверждает грейд',
    text: 'Вы сами выбираете грейд, тест его проверяет. Категория — специализация и подтверждённый грейд — появляется только после теста.',
  },
  {
    icon: Search,
    title: 'Работодатель находит категорию',
    text: 'Он описывает, кого ищет, и получает подборку кандидатов нужной категории. До вашего согласия он видит код, а не имя.',
  },
  {
    icon: MailCheck,
    title: 'Приглашение с зарплатой',
    text: 'Вилка и формат названы сразу. Контакты откроются работодателю только после того, как вы примете приглашение.',
  },
] as const

const EVIDENCE = [
  {
    kind: 'test',
    skill: 'Python',
    text: 'Навык проверен заданиями теста. Такие сведения весят в подборе больше всего.',
  },
  {
    kind: 'fsp',
    skill: 'Алгоритмы',
    text: 'Результат соревнований из реестра ФСП — с согласия кандидата. Без истории ФСП штрафа нет.',
  },
  {
    kind: 'declared',
    skill: 'Kafka',
    text: 'Кандидат указал навык сам. Учитывается, но категорию не определяет.',
  },
] as const

function Landing() {
  usePageTitle(null)

  return (
    <>
      {/* 1. Hero */}
      <section className="page-container grid items-center gap-10 py-10 md:py-16 lg:grid-cols-[minmax(0,1fr)_minmax(0,440px)] lg:gap-16 lg:py-20">
        <div className="flex min-w-0 flex-col gap-6">
          <p className="type-eyebrow flex items-center gap-2 text-brand-700">
            <span className="size-2 shrink-0 rounded-full bg-fsp-red" aria-hidden="true" />
            подбор с обратной механикой
          </p>
          <h1 data-page-title tabIndex={-1} className="type-display text-ink outline-none">
            Работодатель приходит к вам с вилкой — после того, как тест подтвердил ваш грейд
          </h1>
          <p className="type-body max-w-[60ch] text-ink-muted md:text-lg md:leading-7">
            Откликаться не нужно: категорию определяет тест, а не резюме, и приглашение приходит сразу с зарплатой.
          </p>
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

        {/* Пример приглашения: собран из тех же компонентов, что и кабинет. */}
        <figure className="flex min-w-0 flex-col gap-3">
          <div className="relative flex min-w-0 flex-col gap-5 rounded-lg bg-surface p-5 shadow-pop md:rounded-xl md:p-6">
            <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
              <CategoryChip title="Backend · Middle" />
              <StatusBadge status="sent" label="Новое" size="sm" />
            </div>
            <div className="flex min-w-0 flex-col gap-1">
              <p className="type-sm text-ink-muted">Backend-разработчик в платёжный сервис</p>
              <SalaryRange from={180000} to={240000} size="lg" />
            </div>
            <ul className="flex min-w-0 flex-wrap gap-2" aria-label="Чем вы подходите">
              <li>
                <EvidenceChip kind="test" skill="Python" size="sm" />
              </li>
              <li>
                <EvidenceChip kind="test" skill="PostgreSQL" size="sm" />
              </li>
              <li>
                <EvidenceChip kind="fsp" skill="Алгоритмы" size="sm" />
              </li>
              <li>
                <EvidenceChip kind="declared" skill="Kafka" size="sm" />
              </li>
            </ul>
            <p className="type-sm flex items-start gap-2 border-t border-line pt-4 text-ink-muted">
              <Lock className="mt-0.5 size-4 text-brand-700" aria-hidden="true" />
              <span className="min-w-0">Имя и контакты работодатель увидит только после вашего согласия</span>
            </p>
          </div>
          <figcaption className="type-caption text-center text-ink-muted">
            Пример приглашения: вилка и формат названы до ответа
          </figcaption>
        </figure>
      </section>

      {/* 2. Три шага с линией-пайплайном */}
      <section aria-labelledby="steps-title" className="border-y border-line bg-surface">
        <div className="page-container flex flex-col gap-8 py-10 md:gap-12 md:py-16">
          <div className="flex max-w-[64ch] flex-col gap-3">
            <p className="type-eyebrow text-ink-muted">как это устроено</p>
            <h2 id="steps-title" className="type-h1 text-ink">
              Три шага от теста до приглашения
            </h2>
          </div>
          <ol className="grid min-w-0 gap-0 lg:grid-cols-3 lg:gap-8">
            {STEPS.map((step, index) => {
              const Icon = step.icon
              const last = index === STEPS.length - 1
              return (
                <li
                  key={step.title}
                  className="grid min-w-0 grid-cols-[auto_minmax(0,1fr)] gap-x-4 lg:grid-cols-1 lg:gap-y-5"
                >
                  {/* Узел шага и линия: на узком экране линия идёт вниз, на широком — вправо к следующему шагу. */}
                  <div className="flex flex-col items-center gap-2 lg:flex-row lg:gap-4">
                    <span className="grid size-12 shrink-0 place-items-center rounded-full border-2 border-brand-600 bg-brand-50 text-brand-700">
                      <Icon className="size-6" aria-hidden="true" />
                    </span>
                    {last ? null : (
                      <>
                        <PipelineLine shape="vertical" className="min-h-10 flex-1 lg:hidden" />
                        <PipelineLine shape="horizontal" className="hidden flex-1 lg:block" />
                      </>
                    )}
                  </div>
                  <div className={last ? 'flex min-w-0 flex-col gap-2' : 'flex min-w-0 flex-col gap-2 pb-8 lg:pb-0'}>
                    <p className="type-eyebrow text-brand-700">шаг {index + 1}</p>
                    <h3 className="type-h3 text-ink">{step.title}</h3>
                    <p className="type-body text-ink-muted">{step.text}</p>
                  </div>
                </li>
              )
            })}
          </ol>
        </div>
      </section>

      {/* 3. Источники сведений */}
      <section aria-labelledby="evidence-title" className="page-container flex flex-col gap-8 py-10 md:py-16">
        <div className="flex max-w-[64ch] flex-col gap-3">
          <p className="type-eyebrow text-ink-muted">откуда известно</p>
          <h2 id="evidence-title" className="type-h1 text-ink">
            У каждого факта о кандидате виден источник
          </h2>
          <p className="type-body text-ink-muted">
            Три вида сведений различаются иконкой, рамкой и подписью — и по-разному весят в подборе.
          </p>
        </div>
        <ul className="grid min-w-0 gap-4 md:grid-cols-3 md:gap-6">
          {EVIDENCE.map((item) => (
            <li
              key={item.kind}
              className="flex min-w-0 flex-col items-start gap-4 rounded-lg bg-surface p-4 shadow-card md:rounded-xl md:p-6"
            >
              <EvidenceChip kind={item.kind} skill={item.skill} />
              <p className="type-body text-ink-muted">{item.text}</p>
            </li>
          ))}
        </ul>
      </section>

      {/* 4. Объяснение механик */}
      <section aria-labelledby="how-title" className="page-container pb-12 md:pb-20">
        <div className="flex min-w-0 flex-col items-start gap-6 rounded-lg bg-brand-50 p-6 md:flex-row md:items-center md:justify-between md:rounded-xl md:p-10">
          <div className="flex max-w-[60ch] min-w-0 flex-col gap-2">
            <h2 id="how-title" className="type-h2 text-ink">
              Как считается грейд и как строится подборка
            </h2>
            <p className="type-body text-ink-muted">
              Правила теста, порядок подбора и числа проверки — на отдельной странице, без входа.
            </p>
          </div>
          <Button variant="secondary" asChild className="max-[479px]:w-full">
            <Link to="/how-it-works">
              Как это работает
              <ArrowRight aria-hidden="true" />
            </Link>
          </Button>
        </div>
      </section>
    </>
  )
}
