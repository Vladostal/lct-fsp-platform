import { Link } from '@tanstack/react-router'
import { EvidenceLegend, PageHeader } from '@/components/app'
import { Button } from '@/components/ui/button'
import { HOW } from '../content'
import { useValidationSummary } from '../hooks'
import { BlueprintDemo } from './blueprint-demo'
import { type Metric, Numbers } from './numbers'

type Props = { limits: Record<string, number | undefined>; demo: boolean }

function SectionTitle({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <h2 id={id} className="type-h2 scroll-mt-24">
      {children}
    </h2>
  )
}

export function HowItWorks({ limits, demo }: Props) {
  const summary = useValidationSummary()
  const s = summary.data
  const t = s?.testing
  const m = s?.matching
  const c = s?.contact
  const testMetrics: Metric[] = t
    ? [
        { label: 'Точность определения грейда', value: t.v1_accuracy },
        { label: 'Согласие результатов при повторе', value: t.v2_agreement },
        { label: 'Точное попадание в грейд', value: t.v3_exact },
        { label: 'Завышение грейда', value: t.v3_overgrade },
        { label: 'Корреляция с эталонным уровнем', value: t.v6_correlation, kind: 'plain' },
        { label: 'Ложное подтверждение при утечке заданий', value: t.leak_false_confirm_m5 },
      ]
    : []
  const matchMetrics: Metric[] = m
    ? [
        { label: 'Точность первой десятки: наш порядок', value: m.p10_ours },
        { label: 'Случайный порядок', value: m.p10_random },
        { label: 'Только сила профиля', value: m.p10_strength_only },
        { label: 'По заявленным навыкам', value: m.p10_declared },
        { label: 'Согласие ручной разметки (каппа)', value: m.manual_kappa, kind: 'plain' },
      ]
    : []
  const contactMetrics: Metric[] = c
    ? [
        { label: 'Приглашения доставлены', value: c.delivered_share },
        { label: 'Приглашения приняты', value: c.accept_share },
        { label: 'Ответ в срок', value: c.reply_in_time_share },
        { label: 'Потребности закрыты', value: c.needs_filled_share },
      ]
    : []

  return (
    <div className="page-container flex min-w-0 flex-col gap-12 py-8 md:py-12">
      <PageHeader title={HOW.title} description={HOW.description} />
      <div className="grid min-w-0 gap-10 lg:grid-cols-[180px_minmax(0,760px)] lg:gap-16">
        {/* Оглавление: на lg+ липкая колонка слева, ниже — строка ссылок над контентом */}
        <nav aria-label="Разделы страницы" className="min-w-0 lg:sticky lg:top-24 lg:self-start">
          <ul className="flex min-w-0 flex-wrap gap-x-6 gap-y-1 lg:flex-col lg:gap-y-0">
            {HOW.toc.map((x) => (
              <li key={x.id}>
                <a
                  href={`#${x.id}`}
                  className="type-sm tap-target inline-flex items-center text-ink-muted hover:text-brand-700"
                >
                  {x.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>
        <div className="flex min-w-0 flex-col gap-14">
          <section aria-labelledby="testing" className="flex min-w-0 flex-col gap-5">
            <SectionTitle id="testing">{HOW.testing.title}</SectionTitle>
            <p className="type-body max-w-[68ch]">{HOW.testing.lead}</p>
            <ol className="flex min-w-0 flex-col border-l-2 border-brand-600 pl-5">
              {HOW.testing.flow.map((step, i) => (
                <li key={step} className="type-body relative min-w-0 py-1.5">
                  <span className="absolute top-3.5 -left-[27px] size-2 rounded-full bg-brand-600" aria-hidden="true" />
                  <span className="num type-sm mr-3 text-ink-subtle">{String(i + 1).padStart(2, '0')}</span>
                  {step}
                </li>
              ))}
            </ol>
            <ul className="flex max-w-[72ch] min-w-0 flex-col gap-2 divide-y divide-line">
              {HOW.testing.rules.map((r) => (
                <li key={r} className="type-body min-w-0 break-words pt-2 first:pt-0">
                  {r}
                </li>
              ))}
            </ul>
            {demo ? (
              <BlueprintDemo
                min={limits.blueprint_preview_text_min ?? 30}
                max={limits.blueprint_preview_text_max ?? 5000}
              />
            ) : (
              <p className="type-sm text-ink-muted">
                Предпросмотр плана доступен на демо-стенде гостю и работодателю. Пример: «{HOW.examples[1].title}»
                проверяет Python, SQL, HTTP, Git и базы данных; Docker тестом не проверяется.
              </p>
            )}
            <Numbers title={HOW.testing.numbers} metrics={testMetrics} n={t?.n} expert={t?.expert} />
            <section className="flex min-w-0 flex-col gap-2" aria-label={HOW.testing.notClaimed}>
              <h3 className="type-eyebrow">{HOW.testing.notClaimed}</h3>
              <ul className="flex max-w-[72ch] min-w-0 flex-col gap-2 divide-y divide-line">
                {HOW.testing.notClaimedItems.map((x) => (
                  <li key={x} className="type-body min-w-0 break-words pt-2 first:pt-0">
                    {x}
                  </li>
                ))}
              </ul>
            </section>
            {summary.isError ? <p className="type-sm text-ink-muted">{HOW.noNumbers}</p> : null}
          </section>

          <section aria-labelledby="matching" className="flex min-w-0 flex-col gap-5">
            <SectionTitle id="matching">{HOW.matching.title}</SectionTitle>
            <p className="type-body max-w-[68ch]">{HOW.matching.lead}</p>
            <ol className="flex max-w-[72ch] min-w-0 flex-col gap-3">
              {HOW.matching.order.map(([k, v], i) => (
                <li key={k} className="flex min-w-0 gap-3 border-t border-line pt-3">
                  <span className="num type-sm shrink-0 pt-0.5 text-brand-700">{String(i + 1).padStart(2, '0')}</span>
                  <span className="type-body min-w-0 break-words">
                    <span className="font-medium">{k}.</span> {v}
                  </span>
                </li>
              ))}
            </ol>
            <EvidenceLegend />
            <p className="type-body max-w-[68ch]">{HOW.matching.versions}</p>
            <Numbers title={HOW.matching.numbers} metrics={matchMetrics} n={m?.n} />
          </section>

          <section aria-labelledby="contact" className="flex min-w-0 flex-col gap-5">
            <SectionTitle id="contact">{HOW.contact.title}</SectionTitle>
            <p className="type-body max-w-[68ch]">{HOW.contact.lead}</p>
            <ol className="grid min-w-0 gap-3 md:grid-cols-3">
              {HOW.contact.scheme.map(([k, v]) => (
                <li key={k} className="min-w-0 border-t border-line pt-3">
                  <p className="type-h3">{k}</p>
                  <p className="type-sm mt-1 min-w-0 break-words text-ink-muted">{v}</p>
                </li>
              ))}
            </ol>
            <p className="type-body max-w-[68ch]">{HOW.contact.hidden}</p>
            <Numbers title={HOW.contact.numbers} metrics={contactMetrics} n={c?.n} note={HOW.contact.caveat} />
          </section>

          <div className="flex min-w-0 flex-wrap items-center gap-x-6 gap-y-2">
            <Button asChild variant="primary">
              <Link to="/signup" search={{ role: 'candidate' }}>
                {HOW.ctaCandidate}
              </Link>
            </Button>
            <Link
              to="/signup"
              search={{ role: 'employer' }}
              className="type-body tap-target inline-flex items-center text-brand-700 hover:underline"
            >
              {HOW.ctaEmployer}
            </Link>
          </div>
        </div>
      </div>
    </div>
  )
}
