import { Link } from '@tanstack/react-router'
import {
  Activity,
  ArrowRight,
  Banknote,
  BarChart3,
  Boxes,
  Briefcase,
  CalendarClock,
  CircleCheck,
  CircleSlash,
  ClipboardCheck,
  Crosshair,
  Dices,
  EyeOff,
  FileSearch,
  FileText,
  Filter,
  Fingerprint,
  Flag,
  Gauge,
  GitBranch,
  Hourglass,
  Layers,
  LayoutGrid,
  ListChecks,
  Lock,
  type LucideIcon,
  PencilLine,
  Repeat,
  Search,
  Send,
  ShieldAlert,
  ShieldCheck,
  Split,
  Tags,
  Target,
  Timer,
  TrendingUp,
  Trophy,
  UserCheck,
  X,
} from 'lucide-react'
import type * as React from 'react'
import {
  CHART,
  DashedNote,
  EvidenceLegend,
  IconTile,
  PageHeader,
  SoftPill,
  type TileTone,
  type Tone,
} from '@/components/app'
import { Button } from '@/components/ui/button'
import { HOW } from '../content'
import { useValidationSummary } from '../hooks'
import { BlueprintDemo } from './blueprint-demo'
import { type Metric, Numbers } from './numbers'
import { FactCard, Flow, SectionHead } from './parts'

const TOC_ICON: Record<string, LucideIcon> = { testing: ClipboardCheck, matching: Search, contact: Send }
const FLOW_ICON = [FileText, Tags, Layers, LayoutGrid, Boxes, Fingerprint] as const
const ORDER_ICON = [Filter, Layers, ListChecks, ShieldCheck, Gauge] as const
const SCHEME_ICON = [Banknote, Hourglass, Flag] as const
const SCHEME_TONE: readonly TileTone[] = ['success', 'warning', 'brand']
/* Исходы теста: «не подтверждён» остаётся нейтральным, а не красным. */
const OUTCOME_TONE: readonly Tone[] = ['neutral', 'warning', 'success', 'success']
const CONTACT_TONE: readonly Tone[] = ['success', 'danger', 'warning', 'neutral']
/* Цвета частей силы профиля: тест — бренд, ФСП — красный маркер ФСП, заявленное — нейтральные. */
const STRENGTH_COLOR: Record<string, string> = {
  test: CHART.brand,
  fsp: 'var(--color-fsp-red)',
  experience: CHART.neutral,
  skills: 'color-mix(in srgb, var(--color-line-strong) 55%, var(--color-surface))',
}

type Props = { limits: Record<string, number | undefined>; demo: boolean }

export function HowItWorks({ limits, demo }: Props) {
  const summary = useValidationSummary()
  const s = summary.data
  const t = s?.testing
  const m = s?.matching
  const c = s?.contact
  const testMetrics: Metric[] = t
    ? [
        { label: 'Точность определения грейда', value: t.v1_accuracy, icon: Target, tone: 'solid' },
        { label: 'Согласие результатов при повторе', value: t.v2_agreement, icon: Repeat },
        { label: 'Точное попадание в грейд', value: t.v3_exact, icon: Crosshair, tone: 'success' },
        { label: 'Завышение грейда', value: t.v3_overgrade, icon: TrendingUp, tone: 'warning' },
        {
          label: 'Корреляция с эталонным уровнем',
          value: t.v6_correlation,
          kind: 'plain',
          icon: Activity,
          tone: 'deep',
        },
        {
          label: 'Ложное подтверждение при утечке заданий',
          value: t.leak_false_confirm_m5,
          icon: ShieldAlert,
          tone: 'danger',
        },
      ]
    : []
  const matchMetrics: Metric[] = m
    ? [
        { label: 'Точность первой десятки: наш порядок', value: m.p10_ours, icon: Trophy },
        { label: 'Случайный порядок', value: m.p10_random, icon: Dices },
        { label: 'Только сила профиля', value: m.p10_strength_only, icon: Gauge },
        { label: 'По заявленным навыкам', value: m.p10_declared, icon: PencilLine },
        {
          label: 'Согласие ручной разметки (каппа)',
          value: m.manual_kappa,
          kind: 'plain',
          icon: UserCheck,
          tone: 'soft',
        },
      ]
    : []
  const contactMetrics: Metric[] = c
    ? [
        { label: 'Приглашения доставлены', value: c.delivered_share, icon: Send },
        { label: 'Приглашения приняты', value: c.accept_share, icon: CircleCheck, tone: 'success' },
        { label: 'Ответ в срок', value: c.reply_in_time_share, icon: Timer, tone: 'warning' },
        { label: 'Потребности закрыты', value: c.needs_filled_share, icon: Briefcase, tone: 'solid' },
      ]
    : []

  const T = HOW.testing
  const M = HOW.matching
  const C = HOW.contact
  const strengthTotal = M.strength.reduce((sum, x) => sum + x.max, 0)

  return (
    <div className="page-container flex min-w-0 flex-col gap-8 py-8 md:gap-10 md:py-12">
      <PageHeader title={HOW.title} description={HOW.description} />
      <nav aria-label="Разделы страницы" className="min-w-0">
        <ul className="flex min-w-0 flex-wrap gap-2">
          {HOW.toc.map((x) => (
            <li key={x.id}>
              <a
                href={`#${x.id}`}
                className="lift-card surface-row type-sm inline-flex h-11 items-center gap-2 rounded-full pr-4 pl-1.5 font-medium text-ink hover:text-brand-700"
              >
                <IconTile icon={TOC_ICON[x.id] ?? ClipboardCheck} size="sm" className="rounded-full" />
                {x.label}
              </a>
            </li>
          ))}
        </ul>
      </nav>

      <section aria-labelledby="testing" className="flex min-w-0 flex-col gap-5">
        <SectionHead id="testing" icon={ClipboardCheck} title={T.title} lead={T.lead} />
        <Flow
          label={T.flowLabel}
          row="lg6"
          compact
          steps={T.flow.map((title, i) => ({
            title,
            icon: FLOW_ICON[i] ?? FileText,
            tone: i === 5 ? 'solid' : 'brand',
          }))}
        />
        <ul aria-label={T.rulesLabel} className="grid min-w-0 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <li className="flex min-w-0">
            <FactCard icon={ListChecks} value={T.rules.plan.value} label={T.rules.plan.label} className="flex-1">
              <p className="type-sm min-w-0 break-words text-ink-muted">{T.rules.plan.text}</p>
            </FactCard>
          </li>
          <li className="flex min-w-0">
            <FactCard
              icon={Split}
              tone="soft"
              value={T.rules.outcomes.value}
              label={T.rules.outcomes.label}
              className="flex-1"
            >
              <span className="flex min-w-0 flex-wrap gap-1.5">
                {T.rules.outcomes.items.map((x, i) => (
                  <SoftPill key={x} size="sm" tone={OUTCOME_TONE[i] ?? 'neutral'}>
                    {x}
                  </SoftPill>
                ))}
              </span>
            </FactCard>
          </li>
          <li className="flex min-w-0">
            <FactCard icon={EyeOff} tone="neutral" title={T.rules.hidden.title} className="flex-1">
              <p className="type-sm min-w-0 break-words text-ink-muted">{T.rules.hidden.text}</p>
            </FactCard>
          </li>
          <li className="flex min-w-0">
            <FactCard
              icon={CalendarClock}
              tone="warning"
              value={T.rules.change.value}
              label={T.rules.change.label}
              className="flex-1"
            >
              <p className="type-sm min-w-0 break-words text-ink-muted">{T.rules.change.text}</p>
            </FactCard>
          </li>
        </ul>
        {demo ? (
          <BlueprintDemo
            min={limits.blueprint_preview_text_min ?? 30}
            max={limits.blueprint_preview_text_max ?? 5000}
          />
        ) : (
          <FactCard icon={FileSearch} tone="soft" title={T.demoTitle}>
            <p className="type-sm min-w-0 break-words text-ink-muted">
              Предпросмотр плана доступен на демо-стенде гостю и работодателю. Пример: «{HOW.examples[1].title}»
              проверяет Python, SQL, HTTP, Git и базы данных; Docker тестом не проверяется.
            </p>
          </FactCard>
        )}
        <Numbers title={T.numbers} metrics={testMetrics} n={t?.n} expert={t?.expert} />
        <section className="surface-row flex min-w-0 flex-col gap-3 p-4 md:p-5" aria-label={T.notClaimed}>
          <h3 className="type-eyebrow flex min-w-0 items-center gap-2">
            <CircleSlash aria-hidden="true" className="size-4 shrink-0 text-ink-muted" />
            {T.notClaimed}
          </h3>
          <ul className="grid min-w-0 gap-3 md:grid-cols-3">
            {T.notClaimedItems.map((x) => (
              <li key={x} className="flex min-w-0 items-start gap-2.5 rounded-md bg-fill p-3">
                <IconTile icon={X} tone="plain" size="xs" />
                <span className="type-sm min-w-0 break-words text-ink">{x}</span>
              </li>
            ))}
          </ul>
        </section>
        {summary.isError ? <DashedNote icon={BarChart3}>{HOW.noNumbers}</DashedNote> : null}
      </section>

      <section aria-labelledby="matching" className="flex min-w-0 flex-col gap-5">
        <SectionHead id="matching" icon={Search} title={M.title} lead={M.lead} />
        <Flow
          label={M.orderLabel}
          row="lg5"
          steps={M.order.map(([title, text], i) => ({ title, text, icon: ORDER_ICON[i] ?? Filter }))}
        />
        <div className="grid min-w-0 gap-3 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] lg:gap-4">
          <FactCard icon={Gauge} tone="solid" title={M.strengthTitle} className="md:p-5">
            <div
              role="img"
              aria-label={`${M.strengthLabel}: ${M.strength.map((x) => `${x.label} — ${M.upTo(x.max)}`).join(', ')}`}
              className="flex h-4 min-w-0 gap-0.5 overflow-hidden rounded-full"
            >
              {M.strength.map((x, i) => (
                <span
                  key={x.key}
                  className="stagger block h-full origin-left animate-grow-x"
                  style={
                    {
                      width: `${(x.max / strengthTotal) * 100}%`,
                      backgroundColor: STRENGTH_COLOR[x.key],
                      '--i': i * 2,
                    } as React.CSSProperties
                  }
                />
              ))}
            </div>
            <ul className="grid min-w-0 gap-x-4 gap-y-2 sm:grid-cols-2">
              {M.strength.map((x) => (
                <li key={x.key} className="flex min-w-0 items-center gap-2">
                  <span
                    aria-hidden="true"
                    className="size-2.5 shrink-0 rounded-full"
                    style={{ backgroundColor: STRENGTH_COLOR[x.key] }}
                  />
                  <span className="type-sm min-w-0 flex-1 break-words text-ink">{x.label}</span>
                  <span className="num type-sm shrink-0 font-semibold text-ink">{M.upTo(x.max)}</span>
                </li>
              ))}
            </ul>
            <div className="flex min-w-0 flex-col gap-2 border-t border-line pt-3">
              <EvidenceLegend />
              <p className="type-caption text-ink-muted">{M.strengthNote}</p>
            </div>
          </FactCard>
          <FactCard icon={GitBranch} tone="soft" title={M.versionsTitle} className="md:p-5">
            <p aria-hidden="true" className="flex min-w-0 flex-wrap items-center gap-2">
              <SoftPill>v1</SoftPill>
              <ArrowRight className="size-4 shrink-0 text-brand-600" />
              <SoftPill>v2</SoftPill>
              <ArrowRight className="size-4 shrink-0 text-brand-600" />
              <SoftPill tone="solid">v3</SoftPill>
            </p>
            <p className="type-sm min-w-0 break-words text-ink-muted">{M.versions}</p>
          </FactCard>
        </div>
        <Numbers title={M.numbers} metrics={matchMetrics} n={m?.n} bars />
      </section>

      <section aria-labelledby="contact" className="flex min-w-0 flex-col gap-5">
        <SectionHead id="contact" icon={Send} title={C.title} lead={C.lead} />
        <Flow
          label={C.schemeLabel}
          row="md"
          steps={C.scheme.map(([title, text], i) => ({
            title,
            text: text || undefined,
            icon: SCHEME_ICON[i] ?? Send,
            tone: SCHEME_TONE[i],
            extra:
              i === 2 ? (
                <span className="flex min-w-0 flex-wrap gap-1.5">
                  {C.outcomes.map((x, k) => (
                    <SoftPill key={x} size="sm" tone={CONTACT_TONE[k] ?? 'neutral'}>
                      {x}
                    </SoftPill>
                  ))}
                </span>
              ) : null,
          }))}
        />
        <FactCard icon={Lock} tone="ink" title={C.hiddenTitle}>
          <p className="type-sm max-w-[76ch] min-w-0 break-words text-ink-muted">{C.hidden}</p>
        </FactCard>
        <Numbers title={C.numbers} metrics={contactMetrics} n={c?.n} note={C.caveat} />
      </section>

      <div className="accent-card surface-row flex min-w-0 flex-col gap-3 p-4 min-[480px]:flex-row min-[480px]:flex-wrap min-[480px]:items-center md:p-5">
        <Button asChild variant="primary" size="lg">
          <Link to="/signup" search={{ role: 'candidate' }}>
            {HOW.ctaCandidate}
            <ArrowRight aria-hidden="true" />
          </Link>
        </Button>
        <Button asChild variant="secondary" size="lg">
          <Link to="/signup" search={{ role: 'employer' }}>
            {HOW.ctaEmployer}
          </Link>
        </Button>
      </div>
    </div>
  )
}
