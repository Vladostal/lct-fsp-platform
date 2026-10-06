import { Link } from '@tanstack/react-router'
import { EvidenceLegend, PageHeader, PipelineLine } from '@/components/app'
import { Button } from '@/components/ui/button'
import { HOW } from '../content'
import { useValidationSummary } from '../hooks'
import { BlueprintDemo } from './blueprint-demo'
import { type Metric, Numbers } from './numbers'

type Props = { limits: Record<string, number | undefined>; demo: boolean }

function SectionTitle({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <h2 id={id} className="type-h1 scroll-mt-24">
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
    <div className="flex min-w-0 flex-col gap-10">
      <PageHeader title={HOW.title} description={HOW.description} />
      <nav aria-label="Разделы страницы">
        <ul className="flex min-w-0 flex-wrap gap-2">
          {HOW.toc.map((x) => (
            <li key={x.id}>
              <Button asChild variant="secondary" size="sm">
                <a href={`#${x.id}`}>{x.label}</a>
              </Button>
            </li>
          ))}
        </ul>
      </nav>

      <section aria-labelledby="testing" className="flex min-w-0 flex-col gap-5">
        <SectionTitle id="testing">{HOW.testing.title}</SectionTitle>
        <p className="type-body max-w-[72ch]">{HOW.testing.lead}</p>
        <ol className="flex min-w-0 flex-col gap-2 md:flex-row md:flex-wrap md:items-center">
          {HOW.testing.flow.map((step, i) => (
            <li key={step} className="flex min-w-0 items-center gap-2">
              <span className="surface-row type-sm min-w-0 px-3 py-2">{step}</span>
              {i < HOW.testing.flow.length - 1 ? (
                <PipelineLine shape="horizontal" dot={false} className="hidden w-6 md:block" />
              ) : null}
            </li>
          ))}
        </ol>
        <ul className="flex max-w-[72ch] min-w-0 list-disc flex-col gap-1.5 pl-5">
          {HOW.testing.rules.map((r) => (
            <li key={r} className="type-body min-w-0 break-words">
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
            Предпросмотр плана доступен на демо-стенде. Пример: «{HOW.examples[1].title}» проверяет Python, SQL, HTTP,
            Git и базы данных; Docker тестом не проверяется.
          </p>
        )}
        <Numbers title={HOW.testing.numbers} metrics={testMetrics} n={t?.n} expert={t?.expert} />
        <section className="flex min-w-0 flex-col gap-2" aria-label={HOW.testing.notClaimed}>
          <h3 className="type-h3">{HOW.testing.notClaimed}</h3>
          <ul className="flex max-w-[72ch] min-w-0 list-disc flex-col gap-1.5 pl-5">
            {HOW.testing.notClaimedItems.map((x) => (
              <li key={x} className="type-body min-w-0 break-words">
                {x}
              </li>
            ))}
          </ul>
        </section>
        {summary.isError ? <p className="type-sm text-ink-muted">{HOW.noNumbers}</p> : null}
      </section>

      <section aria-labelledby="matching" className="flex min-w-0 flex-col gap-5">
        <SectionTitle id="matching">{HOW.matching.title}</SectionTitle>
        <p className="type-body max-w-[72ch]">{HOW.matching.lead}</p>
        <ol className="flex max-w-[72ch] min-w-0 flex-col gap-3">
          {HOW.matching.order.map(([k, v], i) => (
            <li key={k} className="surface-row flex min-w-0 gap-3 p-4">
              <span className="num type-h3 shrink-0 text-brand-700">{i + 1}</span>
              <span className="type-body min-w-0 break-words">
                <span className="font-medium">{k}.</span> {v}
              </span>
            </li>
          ))}
        </ol>
        <EvidenceLegend />
        <p className="type-body max-w-[72ch]">{HOW.matching.versions}</p>
        <Numbers title={HOW.matching.numbers} metrics={matchMetrics} n={m?.n} />
      </section>

      <section aria-labelledby="contact" className="flex min-w-0 flex-col gap-5">
        <SectionTitle id="contact">{HOW.contact.title}</SectionTitle>
        <p className="type-body max-w-[72ch]">{HOW.contact.lead}</p>
        <ol className="grid min-w-0 gap-3 md:grid-cols-3">
          {HOW.contact.scheme.map(([k, v]) => (
            <li key={k} className="surface-card min-w-0 p-4">
              <p className="type-h3">{k}</p>
              <p className="type-sm mt-1 min-w-0 break-words text-ink-muted">{v}</p>
            </li>
          ))}
        </ol>
        <p className="type-body max-w-[72ch]">{HOW.contact.hidden}</p>
        <Numbers title={HOW.contact.numbers} metrics={contactMetrics} n={c?.n} note={HOW.contact.caveat} />
      </section>

      <div className="flex min-w-0 flex-wrap gap-3">
        <Button asChild variant="secondary">
          <Link to="/signup" search={{ role: 'candidate' }}>
            {HOW.ctaCandidate}
          </Link>
        </Button>
        <Button asChild variant="secondary">
          <Link to="/signup" search={{ role: 'employer' }}>
            {HOW.ctaEmployer}
          </Link>
        </Button>
      </div>
    </div>
  )
}
