import { Inbox, Plus, Search } from 'lucide-react'
import type * as React from 'react'
import { useState } from 'react'
import type { Contribution, LevelView } from '@/client'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogBody,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Progress } from '@/components/ui/progress'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { INVITATION_STATUS_LABELS, TEST_OUTCOME_LABELS, VISIBILITY_LABELS } from '@/content/common'
import { ApiError } from '@/lib/api'
import { formatDate, formatDateTime, formatDeadline, formatList, PLURALS, pluralize } from '@/lib/format'
import { STRESS } from '@/lib/stress'
import { CategoryChip } from '../category-chip'
import { ClampText } from '../clamp-text'
import { ConsentCheckbox } from '../consent-checkbox'
import { ContributionBars } from '../contribution-bars'
import { CopyButton } from '../copy-button'
import { DemoChip } from '../demo-chip'
import { EmptyState } from '../empty-state'
import { ErrorState } from '../error-state'
import { EvidenceChip, EvidenceLegend } from '../evidence-chip'
import { ExternalLink } from '../external-link'
import { FitBadge } from '../fit-badge'
import { LevelScale } from '../level-scale'
import { PageHeader } from '../page-header'
import { PageSkeleton } from '../page-skeleton'
import { PasswordInput } from '../password-input'
import { PipelineLine } from '../pipeline-line'
import { QuotaIndicator } from '../quota-indicator'
import { SalaryRange } from '../salary-range'
import { SalaryRangeInput, type SalaryRangeValue } from '../salary-range-input'
import { StatusBadge } from '../status-badge'
import { Stepper } from '../stepper'
import { StickyActionBar } from '../sticky-action-bar'
import { TagInput, type TagValue } from '../tag-input'

/* ───────────── Данные витрины: статические, запросов страница не делает ───────────── */

const GRADES = [
  { grade: { code: 'junior', title: 'Junior' }, pos: 25 },
  { grade: { code: 'middle', title: 'Middle' }, pos: 50 },
  { grade: { code: 'senior', title: 'Senior' }, pos: 75 },
]

const level = (point: number, lower: number, upper: number, verdict_label: string): LevelView => ({
  point,
  lower,
  upper,
  thresholds: GRADES,
  verdict: 'confirmed',
  verdict_label,
  stale: false,
  tested_at: '2026-10-01T10:00:00Z',
  last_evidence_at: '2026-10-01T10:00:00Z',
})

const LEVELS = {
  confirmed: level(58, 51, 66, 'Middle подтверждён'),
  margin: level(71, 63, 79, 'Middle подтверждён с запасом'),
  borderline: level(49, 41, 57, 'Результат на границе Middle'),
  narrow: level(2, 1, 2, 'Junior не подтверждён'),
  top: level(99, 94, 100, 'Senior подтверждён с запасом'),
}

const CONTRIBUTIONS: Contribution[] = [
  { group: 'coverage', code: 'must', label: 'Обязательные навыки, подтверждённые тестом', points: 42, max_points: 60 },
  { group: 'coverage', code: 'nice', label: 'Желательные навыки', points: 6, max_points: 20 },
  {
    group: 'strength',
    code: 'level',
    label: 'Уровень по результату теста: нижняя граница интервала',
    points: 31,
    max_points: 50,
  },
  { group: 'strength', code: 'fsp', label: 'Достижения ФСП', points: 18, max_points: 30 },
  { group: 'strength', code: 'freshness', label: 'Давность подтверждения', points: -0.8, max_points: 0 },
]

const SKILL_OPTIONS = [
  { code: 'python', title: 'Python', aliases: ['py', 'питон'] },
  { code: 'postgresql', title: 'PostgreSQL', aliases: ['postgres', 'pg', 'постгрес'] },
  { code: 'kafka', title: 'Apache Kafka', aliases: ['kafka', 'кафка'] },
  { code: 'clickhouse', title: 'ClickHouse', aliases: ['ch'] },
  { code: 'docker', title: 'Docker', aliases: ['докер'] },
  { code: 'fastapi', title: 'FastAPI', aliases: [] },
  { code: 'redis', title: 'Redis', aliases: [] },
  { code: 'sql', title: 'SQL', aliases: ['скл'] },
  { code: 'git', title: 'Git', aliases: ['гит'] },
]

const SALARY_LIMITS = { salary_min: 30_000, salary_max: 3_000_000, salary_max_ratio: 1.5 }

const WIZARD = [
  { id: 'profile', label: 'Профиль', href: '/demo/components' },
  { id: 'survey', label: 'Опрос', href: '/demo/components' },
  { id: 'grade', label: 'Грейд' },
  { id: 'test', label: 'Тест' },
  { id: 'done', label: 'Категория' },
]

const INVITATION_ROWS = [
  { name: STRESS.fullName, mono: false, status: 'accepted', label: 'Принято', due: '12 окт.' },
  { name: 'К-20077', mono: true, status: 'bounced', label: 'Не доставлено', due: '9 окт.' },
] as const

const NOW = new Date('2026-10-05T12:00:00Z')

/* ───────────── Разметка витрины ───────────── */

function Section({
  id,
  title,
  description,
  children,
}: {
  id: string
  title: string
  description?: string
  children: React.ReactNode
}) {
  return (
    <section aria-labelledby={`${id}-title`} className="flex min-w-0 scroll-mt-20 flex-col gap-4" id={id}>
      <div className="flex min-w-0 flex-col gap-1">
        <h2 id={`${id}-title`} className="type-h2 text-ink">
          {title}
        </h2>
        {description ? <p className="type-sm max-w-[72ch] text-ink-muted">{description}</p> : null}
      </div>
      <div className="grid min-w-0 gap-4 md:gap-6">{children}</div>
    </section>
  )
}

function Specimen({ title, children, className }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <Card className="gap-4">
      <h3 className="type-eyebrow text-ink-muted">{title}</h3>
      <div className={className ?? 'flex min-w-0 flex-wrap items-center gap-3'}>{children}</div>
    </Card>
  )
}

/** Узкий контейнер 280 px: компоненты перестраиваются по ширине контейнера, а не окна. */
function Narrow({ children }: { children: React.ReactNode }) {
  return (
    <div className="w-[280px] max-w-full min-w-0 shrink-0 rounded-lg border border-dashed border-line-strong p-3">
      {children}
    </div>
  )
}

const SECTIONS = [
  ['buttons', 'Кнопки'],
  ['badges', 'Бейджи и статусы'],
  ['evidence', 'Доказательства'],
  ['salary', 'Вилка'],
  ['level', 'Уровень'],
  ['fit', 'Совпадение и вклады'],
  ['stepper', 'Шаги и линии'],
  ['forms', 'Поля форм'],
  ['tags', 'Теги и копирование'],
  ['text', 'Длинный текст'],
  ['states', 'Состояния'],
  ['layers', 'Слои'],
  ['header', 'Шапка страницы'],
] as const

/**
 * Витрина компонентов `/demo/components`: каждый общий компонент в обычном виде и с проверочными строками
 * (E §4.6), все варианты и состояния. Страница статическая; по ней проходит автопроверка вёрстки (E §4.7).
 */
export function Showcase() {
  const [salary, setSalary] = useState<SalaryRangeValue>({ from: 180_000, to: 240_000 })
  const [wideSalary, setWideSalary] = useState<SalaryRangeValue>({ from: 100_000, to: 400_000 })
  const [tags, setTags] = useState<TagValue[]>([
    { code: 'python', title: 'Python' },
    { code: 'postgresql', title: 'PostgreSQL' },
    { code: null, title: STRESS.customTag },
  ])
  const [consent, setConsent] = useState(false)
  const [retrying, setRetrying] = useState(false)

  return (
    <div className="page-container flex min-w-0 flex-col gap-10 py-8 md:gap-12 md:py-12">
      <PageHeader
        title="Витрина компонентов"
        eyebrow="дизайн-система"
        description="Общие компоненты в обычном виде и с проверочными строками: длинные названия, слово без пробелов, предельная вилка. Страница статическая и запросов не делает."
        meta={
          <>
            <Badge variant="info">светлая тема</Badge>
            <Badge variant="neutral">Inter · JetBrains Mono</Badge>
            <DemoChip />
          </>
        }
      />

      <nav aria-label="Разделы витрины">
        <ul className="flex min-w-0 flex-wrap gap-2">
          {SECTIONS.map(([id, label]) => (
            <li key={id}>
              <a
                href={`#${id}`}
                className="inline-flex h-11 items-center rounded-full border border-line-strong bg-surface px-4 text-sm font-medium whitespace-nowrap text-ink transition-colors duration-(--dur-fast) hover:border-brand-600 hover:bg-brand-50 hover:text-brand-700"
              >
                {label}
              </a>
            </li>
          ))}
        </ul>
      </nav>

      <Section
        id="buttons"
        title="Кнопки"
        description="Пилюли. Основная — одна на экран; подпись не длиннее 32 знаков и не переносится."
      >
        <Specimen title="варианты">
          <Button variant="primary">Отправить приглашение</Button>
          <Button variant="secondary">Уточнить запрос</Button>
          <Button variant="ghost">Назад</Button>
          <Button variant="destructive">Отозвать приглашение</Button>
          <Button variant="link">Как это считается?</Button>
        </Specimen>
        <Specimen title="размеры и иконки">
          <Button size="lg" variant="secondary">
            Пройти тест на Middle
          </Button>
          <Button size="md" variant="secondary">
            <Plus aria-hidden="true" />
            Описать потребность
          </Button>
          <Button size="sm" variant="secondary">
            Пригласить
          </Button>
          <Button size="icon" variant="ghost" aria-label="Найти">
            <Search aria-hidden="true" />
          </Button>
          <Button size="icon-sm" variant="ghost" aria-label="Добавить">
            <Plus aria-hidden="true" />
          </Button>
        </Specimen>
        <Specimen title="состояния: загрузка и недоступно">
          <Button variant="secondary" loading>
            Сформировать подборку
          </Button>
          <Button variant="secondary" disabled>
            Пригласить
          </Button>
          <span className="type-sm text-ink-muted">Недоступно: все слоты заняты</span>
        </Specimen>
        <Specimen title="ряд кнопок в узком контейнере" className="flex min-w-0">
          <Narrow>
            <div className="flex min-w-0 flex-col gap-3">
              <Button variant="secondary" className="w-full">
                Пересмотреть условия
              </Button>
              <Button variant="ghost" className="w-full">
                Другие кандидаты
              </Button>
            </div>
          </Narrow>
        </Specimen>
      </Section>

      <Section
        id="badges"
        title="Бейджи и статусы"
        description="Статус различим без цвета: у каждого бейджа иконка и подпись."
      >
        <Specimen title="приглашение — работодателю">
          {(['sent', 'viewed', 'accepted', 'declined', 'expired', 'withdrawn', 'bounced'] as const).map((status) => (
            <StatusBadge key={status} status={status} label={INVITATION_STATUS_LABELS.employer[status] ?? status} />
          ))}
        </Specimen>
        <Specimen title="приглашение — кандидату (sm)">
          {(['sent', 'viewed', 'accepted', 'declined', 'expired', 'withdrawn'] as const).map((status) => (
            <StatusBadge
              key={status}
              status={status}
              size="sm"
              label={INVITATION_STATUS_LABELS.candidate[status] ?? status}
            />
          ))}
        </Specimen>
        <Specimen title="исход теста">
          {(['confirmed', 'confirmed_with_margin', 'borderline', 'not_confirmed'] as const).map((status) => (
            <StatusBadge key={status} status={status} label={TEST_OUTCOME_LABELS[status]} />
          ))}
        </Specimen>
        <Specimen title="видимость профиля и квота">
          {(['visible', 'paused', 'unpublished', 'not_ready'] as const).map((status) => (
            <StatusBadge key={status} status={status} label={VISIBILITY_LABELS[status]} />
          ))}
          <QuotaIndicator quota={{ used: 3, limit: 10, frozen: false }} />
          <QuotaIndicator quota={{ used: 10, limit: 10, frozen: false }} />
          <QuotaIndicator quota={{ used: 4, limit: 10, frozen: true }} />
        </Specimen>
        <Specimen title="категория">
          <CategoryChip title="Backend · Middle" />
          {STRESS.categories.map((title) => (
            <CategoryChip key={title} title={title} />
          ))}
          <CategoryChip title="Fullstack · Senior" size="lg" />
          <DemoChip />
        </Specimen>
        <Specimen title="тона бейджа">
          <Badge variant="neutral">нейтральный</Badge>
          <Badge variant="info">новый</Badge>
          <Badge variant="success">из резюме</Badge>
          <Badge variant="warning">проверьте</Badge>
          <Badge variant="danger">ошибка</Badge>
          <Badge variant="outline">давно не подтверждалось</Badge>
          <Badge variant="neutral" size="sm">
            по опросу
          </Badge>
        </Specimen>
      </Section>

      <Section
        id="evidence"
        title="Доказательства"
        description="Вид доказательства различается иконкой, типом границы и подписью; над списком с короткими чипами стоит легенда."
      >
        <Specimen title="легенда" className="flex min-w-0 flex-col gap-3">
          <EvidenceLegend />
          <EvidenceLegend audience="self" kinds={['test', 'pulse', 'fsp', 'declared', 'none']} />
        </Specimen>
        <Specimen title="md: навык и подпись">
          <EvidenceChip kind="test" skill="Python" />
          <EvidenceChip kind="pulse" skill="SQL" />
          <EvidenceChip kind="fsp" skill="Алгоритмы" />
          <EvidenceChip kind="declared" skill="Kafka" />
          <EvidenceChip kind="none" skill="ClickHouse" />
          <EvidenceChip kind="declared" skill={STRESS.customTag} />
          <EvidenceChip kind="test" skill="PostgreSQL" detail="через смежный навык SQL · подтверждено 12 сент." />
        </Specimen>
        <Specimen title="sm: иконка и навык (подпись — в title и aria-label)">
          <EvidenceChip kind="test" skill="Python" size="sm" />
          <EvidenceChip kind="test" skill="PostgreSQL" size="sm" />
          <EvidenceChip kind="fsp" skill="Алгоритмы" size="sm" />
          <EvidenceChip kind="declared" skill="Kafka" size="sm" />
          <EvidenceChip kind="declared" skill={STRESS.customTag} size="sm" />
          <span className="type-sm num text-ink-muted">+2</span>
        </Specimen>
        <Specimen title="в узком контейнере" className="flex min-w-0 flex-wrap gap-4">
          <Narrow>
            <div className="flex min-w-0 flex-wrap gap-2">
              <EvidenceChip kind="declared" skill={STRESS.customTag} />
              <EvidenceChip kind="test" skill="Python" />
              <EvidenceChip kind="fsp" skill={STRESS.customTag} size="sm" />
            </div>
          </Narrow>
        </Specimen>
      </Section>

      <Section id="salary" title="Вилка" description="Моноширинные цифры, неразрывные пробелы, всегда в одну строку.">
        <Specimen title="размеры" className="flex min-w-0 flex-col items-start gap-4">
          <SalaryRange from={180_000} to={240_000} size="sm" />
          <SalaryRange from={180_000} to={240_000} size="md" />
          <SalaryRange from={180_000} to={240_000} size="lg" />
        </Specimen>
        <Specimen title="предельная вилка и компактный вид" className="flex min-w-0 flex-col items-start gap-4">
          <SalaryRange from={STRESS.salaryFrom} to={STRESS.salaryTo} size="lg" />
          <SalaryRange from={STRESS.salaryFrom} to={STRESS.salaryTo} size="md" />
          <SalaryRange from={180_000} to={240_000} size="sm" compact />
          <SalaryRange from={STRESS.salaryFrom} to={STRESS.salaryTo} size="sm" compact />
        </Specimen>
        <Specimen title="поля вилки" className="grid min-w-0 gap-6 lg:grid-cols-2">
          <SalaryRangeInput value={salary} onChange={setSalary} limits={SALARY_LIMITS} required />
          <SalaryRangeInput
            value={wideSalary}
            onChange={setWideSalary}
            limits={SALARY_LIMITS}
            showErrors
            legend="Слишком широкая вилка"
          />
        </Specimen>
        <Specimen title="поля вилки в узком контейнере" className="flex min-w-0">
          <Narrow>
            <SalaryRangeInput
              value={{ from: STRESS.salaryFrom, to: STRESS.salaryTo }}
              onChange={() => undefined}
              limits={SALARY_LIMITS}
              serverError="Условия должны быть не хуже названных кандидатом"
            />
          </Narrow>
        </Specimen>
      </Section>

      <Section
        id="level"
        title="Уровень"
        description="Интервал и точка на шкале с порогами грейдов; рядом — вердикт текстом. Баллов и процентов нет."
      >
        <Specimen title="md" className="grid min-w-0 gap-8 md:grid-cols-2">
          <LevelScale level={LEVELS.confirmed} ownGrade="middle" animate />
          <LevelScale level={LEVELS.margin} ownGrade="middle" />
          <LevelScale level={LEVELS.borderline} ownGrade="middle" />
          <LevelScale level={LEVELS.narrow} ownGrade="junior" />
          <LevelScale level={LEVELS.top} ownGrade="senior" />
        </Specimen>
        <Specimen title="sm: подпись только у порога своего грейда">
          <LevelScale level={LEVELS.confirmed} size="sm" ownGrade="middle" />
          <LevelScale level={LEVELS.top} size="sm" ownGrade="senior" />
          <LevelScale level={LEVELS.narrow} size="sm" ownGrade="junior" />
        </Specimen>
      </Section>

      <Section
        id="fit"
        title="Совпадение и вклады"
        description="Полоса совпадения названа словами; вклад каждой части виден числом и полосой."
      >
        <Specimen title="полоса совпадения и сила профиля">
          <FitBadge band="strong" />
          <FitBadge band="good" />
          <FitBadge band="partial" />
          <FitBadge band={null} strength="high" />
          <FitBadge band={null} strength="medium" />
          <FitBadge band={null} strength="base" size="sm" />
        </Specimen>
        <Specimen title="вклады в оценку" className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1fr)_auto]">
          <ContributionBars items={CONTRIBUTIONS} />
          <Narrow>
            {/* Кандидат без истории ФСП: строка «Достижения ФСП: 0» не рисуется. */}
            <ContributionBars
              items={CONTRIBUTIONS.map((item) => (item.code === 'fsp' ? { ...item, points: 0 } : item))}
            />
          </Narrow>
        </Specimen>
      </Section>

      <Section
        id="stepper"
        title="Шаги и линии"
        description="Линия-пайплайн брендбука ФСП соединяет шаги; в узком контейнере степпер становится строкой «Шаг i из n»."
      >
        <Specimen title="мастер кандидата" className="flex min-w-0 flex-col gap-6">
          <Stepper steps={WIZARD} current="grade" />
          <Stepper steps={WIZARD} current="profile" />
          <Stepper steps={WIZARD} current="done" linkCompleted={false} />
        </Specimen>
        <Specimen
          title="первый запуск работодателя и узкий контейнер"
          className="flex min-w-0 flex-wrap items-start gap-6"
        >
          <div className="min-w-0 flex-1 basis-96">
            <Stepper
              steps={[
                { id: 'company', label: 'Компания' },
                { id: 'need', label: 'Потребность' },
                { id: 'shortlist', label: 'Подборка' },
              ]}
              current="need"
            />
          </div>
          <Narrow>
            <Stepper steps={WIZARD} current="test" />
          </Narrow>
        </Specimen>
        <Specimen title="линия-пайплайн" className="flex min-w-0 flex-wrap items-center gap-8">
          <PipelineLine shape="horizontal" className="w-32" />
          <PipelineLine shape="horizontal" className="w-32" muted />
          <PipelineLine shape="vertical" className="h-16" />
          <PipelineLine shape="turn-down" className="size-16" />
          <PipelineLine shape="turn-right" className="size-16" />
        </Specimen>
      </Section>

      <Section
        id="forms"
        title="Поля форм"
        description="Высота поля 44 px; у каждого поля подпись; ошибка — иконка и текст."
      >
        <Specimen title="поля" className="grid min-w-0 gap-5 md:grid-cols-2">
          <div className="flex min-w-0 flex-col gap-2">
            <Label htmlFor="sc-name">Фамилия</Label>
            <Input id="sc-name" defaultValue={STRESS.fullName} autoComplete="off" />
          </div>
          <div className="flex min-w-0 flex-col gap-2">
            <Label htmlFor="sc-empty">Город</Label>
            <Input id="sc-empty" placeholder="Например, Казань" autoComplete="off" />
          </div>
          <div className="flex min-w-0 flex-col gap-2">
            <Label htmlFor="sc-invalid">E-mail</Label>
            <Input
              id="sc-invalid"
              defaultValue="anna@example"
              aria-invalid="true"
              aria-describedby="sc-invalid-error"
              autoComplete="off"
            />
            <p id="sc-invalid-error" className="type-sm text-danger">
              Проверьте адрес: в нём должны быть «@» и домен
            </p>
          </div>
          <div className="flex min-w-0 flex-col gap-2">
            <Label htmlFor="sc-disabled">Недоступное поле</Label>
            <Input id="sc-disabled" defaultValue="только чтение" disabled />
          </div>
          <div className="flex min-w-0 flex-col gap-2">
            <Label htmlFor="sc-password">Пароль</Label>
            <PasswordInput id="sc-password" defaultValue="correct-horse" autoComplete="off" />
          </div>
          <div className="flex min-w-0 flex-col gap-2">
            <Label htmlFor="sc-select">Минимальная зарплата</Label>
            <Select defaultValue="160000">
              <SelectTrigger id="sc-select">
                <SelectValue placeholder="Не задан" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">Не задан</SelectItem>
                <SelectItem value="120000">120 000 ₽</SelectItem>
                <SelectItem value="160000">160 000 ₽</SelectItem>
                <SelectItem value="200000">200 000 ₽</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex min-w-0 flex-col gap-2 md:col-span-2">
            <Label htmlFor="sc-about">О себе</Label>
            <Textarea id="sc-about" defaultValue={`Шесть лет пишу бэкенд. ${STRESS.longWord}`} />
          </div>
        </Specimen>
        <Specimen title="выбор" className="grid min-w-0 gap-6 md:grid-cols-2">
          <div className="flex min-w-0 flex-col gap-3">
            <div className="flex items-center gap-3">
              <Checkbox id="sc-check-1" defaultChecked />
              <Label htmlFor="sc-check-1" className="text-base font-normal">
                удалённо
              </Label>
            </div>
            <div className="flex items-center gap-3">
              <Checkbox id="sc-check-2" />
              <Label htmlFor="sc-check-2" className="text-base font-normal">
                гибрид
              </Label>
            </div>
            <div className="flex items-center gap-3">
              <Checkbox id="sc-check-3" disabled />
              <Label htmlFor="sc-check-3" className="text-base font-normal">
                офис — кандидат не рассматривает
              </Label>
            </div>
          </div>
          <RadioGroup defaultValue="middle" aria-label="Грейд">
            {['junior', 'middle', 'senior'].map((grade) => (
              <div key={grade} className="flex items-center gap-3">
                <RadioGroupItem id={`sc-radio-${grade}`} value={grade} />
                <Label htmlFor={`sc-radio-${grade}`} className="text-base font-normal capitalize">
                  {grade}
                </Label>
              </div>
            ))}
          </RadioGroup>
          <div className="flex items-center gap-3">
            <Switch id="sc-switch" defaultChecked />
            <Label htmlFor="sc-switch" className="text-base font-normal">
              Готов(а) к переезду
            </Label>
          </div>
          <ToggleGroup type="multiple" defaultValue={['remote']} aria-label="Формат работы">
            <ToggleGroupItem value="office">офис</ToggleGroupItem>
            <ToggleGroupItem value="hybrid">гибрид</ToggleGroupItem>
            <ToggleGroupItem value="remote">удалённо</ToggleGroupItem>
          </ToggleGroup>
        </Specimen>
        <Specimen title="согласие" className="grid min-w-0 gap-5 md:grid-cols-2">
          <ConsentCheckbox
            checked={consent}
            onCheckedChange={setConsent}
            href="/legal/processing"
            version="2026-10-01"
            required
          >
            Согласен(на) на обработку персональных данных
          </ConsentCheckbox>
          <ConsentCheckbox
            checked={false}
            onCheckedChange={() => undefined}
            href="/legal/publication"
            version="2026-10-01"
            error="Без согласия профиль не будет показан работодателям"
          >
            Согласен(на) на публикацию профиля в банке кандидатов
          </ConsentCheckbox>
          <ConsentCheckbox checked onCheckedChange={() => undefined} disabled hint="Согласие дано 1 окт. 2026">
            Согласен(на) на получение сведений из реестра ФСП
          </ConsentCheckbox>
        </Specimen>
      </Section>

      <Section
        id="tags"
        title="Теги и копирование"
        description="Поиск по названию и алиасам справочника; свой тег — до 40 знаков; счётчик «n из max»."
      >
        <Specimen title="поле тегов" className="grid min-w-0 gap-6 lg:grid-cols-2">
          <TagInput
            label="Стек"
            value={tags}
            onChange={setTags}
            options={SKILL_OPTIONS}
            max={30}
            allowCustom
            customHint="Свой тег учтём как заявленный: в подборе он не участвует и до вашего согласия не показывается"
          />
          <TagInput
            label="Роли (заполнено до предела)"
            value={[
              { code: 'be', title: 'Backend-разработчик' },
              { code: 'tl', title: 'Техлид' },
            ]}
            onChange={() => undefined}
            options={[]}
            max={2}
          />
        </Specimen>
        <Specimen title="значения с копированием" className="grid min-w-0 gap-3">
          <div className="flex min-w-0 items-center gap-2">
            <ExternalLink href={STRESS.link}>{STRESS.link}</ExternalLink>
            <CopyButton value={STRESS.link} label="ссылку" />
          </div>
          <div className="flex min-w-0 items-center gap-2">
            <span className="type-body min-w-0 text-ink [overflow-wrap:anywhere]">{STRESS.email}</span>
            <CopyButton value={STRESS.email} label="e-mail" />
          </div>
          <div className="flex min-w-0 items-center gap-2">
            <span className="num type-body text-ink">К-10042</span>
            <CopyButton value="К-10042" label="код кандидата" />
          </div>
        </Specimen>
      </Section>

      <Section
        id="text"
        title="Длинный текст"
        description="Текст не накладывается и не обрезается без явного усечения: у усечённого есть title и место, где значение видно целиком."
      >
        <Specimen
          title="название в карточке списка: не больше двух строк"
          className="grid min-w-0 gap-4 md:grid-cols-2"
        >
          <div className="surface-row flex min-w-0 flex-col gap-2 p-4">
            <p className="type-h3 line-clamp-2 min-w-0 text-ink" title={STRESS.needTitle}>
              {STRESS.needTitle}
            </p>
            <p className="type-sm truncate text-ink-muted" title={STRESS.company}>
              {STRESS.company}
            </p>
            <SalaryRange from={STRESS.salaryFrom} to={STRESS.salaryTo} size="sm" />
          </div>
          <div className="surface-row flex min-w-0 flex-col gap-2 p-4">
            <div className="flex min-w-0 items-center gap-2">
              <p className="type-h3 min-w-0 truncate text-ink" title={STRESS.fullName}>
                {STRESS.fullName}
              </p>
              <FitBadge band="strong" size="sm" />
            </div>
            <p className="type-sm truncate text-ink-muted" title={STRESS.fspLine}>
              {STRESS.fspLine}
            </p>
            <p className="type-sm line-clamp-2 text-warning" title={STRESS.risk}>
              {STRESS.risk}
            </p>
          </div>
        </Specimen>
        <Specimen
          title="«О себе»: шесть строк и «Показать полностью»"
          className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1fr)_auto]"
        >
          <ClampText text={STRESS.about} />
          <Narrow>
            <ClampText text={STRESS.about} />
          </Narrow>
        </Specimen>
        <Specimen title="строка кода: прокрутка внутри блока" className="flex min-w-0">
          <section
            aria-label="Код задания"
            // biome-ignore lint/a11y/noNoninteractiveTabindex: прокручиваемая область кода должна быть доступна с клавиатуры (E §7)
            tabIndex={0}
            className="max-w-full min-w-0 flex-1 overflow-x-auto rounded-md border border-line bg-canvas"
          >
            <pre className="w-max p-4 text-sm leading-[22px] whitespace-pre text-ink">
              <code>{`1  def top(events, threshold):\n2      ${STRESS.codeLine}\n3      return result`}</code>
            </pre>
          </section>
        </Specimen>
        <Specimen title="числа, даты и склонения" className="grid min-w-0 gap-2">
          <p className="type-body text-ink">
            <span className="num">{formatDate('2026-10-12T09:00:00Z', NOW)}</span> ·{' '}
            <span className="num">{formatDateTime('2025-10-12T11:02:00Z', NOW)}</span> ·{' '}
            {formatDeadline('2026-10-08T12:00:00Z', 'ответить', NOW)}
          </p>
          <p className="type-body text-ink">
            {pluralize(1, PLURALS.candidate)}, {pluralize(3, PLURALS.candidate)}, {pluralize(14, PLURALS.task)},{' '}
            {pluralize(21, PLURALS.day)}, {pluralize(5, PLURALS.slot)}
          </p>
          <p className="type-body text-ink">{formatList(['PostgreSQL', 'Kafka', 'ClickHouse', 'Redis', 'Docker'])}</p>
        </Specimen>
        <Specimen title="таблица: в узком контейнере — список карточек" className="@container min-w-0">
          {/* Горизонтальной прокрутки у таблиц данных нет: вид меняется по ширине контейнера (E §4.5). */}
          <div className="hidden @xl:block">
            <Table>
              <TableCaption>Приглашения по потребности</TableCaption>
              <colgroup>
                <col />
                <col className="w-44" />
                <col className="w-28" />
              </colgroup>
              <TableHeader>
                <TableRow>
                  <TableHead>Кандидат</TableHead>
                  <TableHead>Статус</TableHead>
                  <TableHead className="text-right">Срок</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {INVITATION_ROWS.map((row) => (
                  <TableRow key={row.name}>
                    <TableCell>
                      <span className={row.mono ? 'num block truncate' : 'block truncate'} title={row.name}>
                        {row.name}
                      </span>
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={row.status} label={row.label} size="sm" />
                    </TableCell>
                    <TableCell className="num text-right">{row.due}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <ul className="flex min-w-0 flex-col gap-3 @xl:hidden">
            {INVITATION_ROWS.map((row) => (
              <li key={row.name} className="surface-row flex min-w-0 flex-col gap-2 p-4">
                <p
                  className={row.mono ? 'num type-body font-medium text-ink' : 'type-body min-w-0 font-medium text-ink'}
                >
                  {row.name}
                </p>
                <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
                  <StatusBadge status={row.status} label={row.label} size="sm" />
                  <span className="num type-sm text-ink-muted">{row.due}</span>
                </div>
              </li>
            ))}
          </ul>
        </Specimen>
      </Section>

      <Section
        id="states"
        title="Состояния"
        description="Загрузка, пусто и ошибка: каркас и навигация остаются на месте."
      >
        <Specimen title="плашки" className="grid min-w-0 gap-3 md:grid-cols-2">
          <Alert variant="info">
            <AlertTitle>Грейд не понижается автоматически</AlertTitle>
            <AlertDescription>Не подтвердите — сможете сразу пройти тест на грейд ниже.</AlertDescription>
          </Alert>
          <Alert variant="success">
            <AlertTitle>Приглашение отправлено</AlertTitle>
            <AlertDescription>Слот занят до ответа кандидата, но не дольше 7 дней.</AlertDescription>
          </Alert>
          <Alert variant="warning">
            <AlertTitle>Не доставлено: условия не совпали</AlertTitle>
            <AlertDescription>Повторить попытку можно с 4 нояб.</AlertDescription>
          </Alert>
          <Alert variant="destructive">
            <AlertTitle>Не удалось сохранить</AlertTitle>
            <AlertDescription>{STRESS.longWord} — введённое сохранено в форме, повторите попытку.</AlertDescription>
          </Alert>
        </Specimen>
        <Specimen title="пусто" className="grid min-w-0 gap-4 md:grid-cols-2">
          <EmptyState
            icon={Inbox}
            title="Приглашений пока нет"
            text="Откликаться не нужно: работодатели сами находят вашу категорию и присылают приглашение с зарплатой"
            headingLevel={4}
            compact
          />
          <EmptyState
            icon={Search}
            title="Ничего не найдено"
            text="Измените или сбросьте фильтры"
            action={<Button variant="secondary">Сбросить фильтры</Button>}
            headingLevel={4}
            compact
          />
        </Specimen>
        <Specimen title="ошибка загрузки, нет доступа, не найдено" className="grid min-w-0 gap-4 lg:grid-cols-3">
          <ErrorState
            error={new ApiError({ status: 503, code: 'internal_error' })}
            headingLevel={3}
            compact
            retrying={retrying}
            onRetry={() => {
              setRetrying(true)
              window.setTimeout(() => setRetrying(false), 1200)
            }}
          />
          <ErrorState
            error={new ApiError({ status: 403, code: 'forbidden' })}
            headingLevel={3}
            compact
            homeHref="/demo/components"
          />
          <ErrorState
            error={new ApiError({ status: 404, code: 'not_found' })}
            headingLevel={3}
            compact
            homeHref="/demo/components"
          />
        </Specimen>
        <Specimen title="скелетоны и прогресс" className="grid min-w-0 gap-6 lg:grid-cols-2">
          <PageSkeleton variant="form" />
          <div className="flex min-w-0 flex-col gap-4">
            <Skeleton className="h-[104px] w-full rounded-lg" />
            <Skeleton className="h-[104px] w-full rounded-lg" />
            <div className="flex min-w-0 flex-col gap-2">
              <span id="sc-progress-label" className="type-sm num text-ink-muted">
                7 из 14
              </span>
              <Progress value={50} aria-labelledby="sc-progress-label" />
            </div>
          </div>
        </Specimen>
      </Section>

      <Section
        id="layers"
        title="Слои"
        description="Диалог, боковая панель, вкладки и подсказка. Esc закрывает верхний слой и возвращает фокус."
      >
        <Specimen title="диалог и панель">
          <Dialog>
            <DialogTrigger asChild>
              <Button variant="secondary">Открыть диалог</Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Принять приглашение?</DialogTitle>
                <DialogDescription>
                  Работодатель увидит ваше имя и выбранные способы связи. Отозвать уже переданное нельзя.
                </DialogDescription>
              </DialogHeader>
              <DialogBody>
                <div className="flex items-center gap-3">
                  <Checkbox id="sc-dialog-email" defaultChecked />
                  <Label htmlFor="sc-dialog-email" className="min-w-0 text-base font-normal [overflow-wrap:anywhere]">
                    {STRESS.email}
                  </Label>
                </div>
                <p className="type-sm text-ink-muted">{STRESS.company}</p>
              </DialogBody>
              <DialogFooter>
                <DialogClose asChild>
                  <Button variant="ghost">Не сейчас</Button>
                </DialogClose>
                <DialogClose asChild>
                  <Button variant="primary">Принять и открыть контакты</Button>
                </DialogClose>
              </DialogFooter>
            </DialogContent>
          </Dialog>
          <Sheet>
            <SheetTrigger asChild>
              <Button variant="secondary">Открыть панель</Button>
            </SheetTrigger>
            <SheetContent>
              <SheetHeader>
                <SheetTitle>Кандидат К-10042</SheetTitle>
                <SheetDescription>Карточка кандидата: до согласия — код вместо имени</SheetDescription>
              </SheetHeader>
              <SheetBody>
                <CategoryChip title="Backend · Middle" />
                <LevelScale level={LEVELS.confirmed} ownGrade="middle" />
                <EvidenceLegend />
                <ContributionBars items={CONTRIBUTIONS} />
                <ClampText text={STRESS.about} />
              </SheetBody>
              <SheetFooter>
                <Button variant="ghost">Закрепить</Button>
                <Button variant="primary">Пригласить</Button>
              </SheetFooter>
            </SheetContent>
          </Sheet>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="sm">
                Подсказка
              </Button>
            </TooltipTrigger>
            <TooltipContent>Подсказка дублирует текст, а не заменяет его</TooltipContent>
          </Tooltip>
        </Specimen>
        <Specimen title="вкладки" className="min-w-0">
          <Tabs defaultValue="awaiting">
            <TabsList aria-label="Приглашения">
              <TabsTrigger value="awaiting">
                Ждут ответа <span className="num text-ink-muted">3</span>
              </TabsTrigger>
              <TabsTrigger value="accepted">
                Принятые <span className="num text-ink-muted">12</span>
              </TabsTrigger>
              <TabsTrigger value="archived">
                Архив <span className="num text-ink-muted">104</span>
              </TabsTrigger>
            </TabsList>
            <TabsContent value="awaiting">
              <p className="type-body text-ink-muted">Три приглашения ждут вашего ответа.</p>
            </TabsContent>
            <TabsContent value="accepted">
              <p className="type-body text-ink-muted">Принятые приглашения: контакты открыты работодателю.</p>
            </TabsContent>
            <TabsContent value="archived">
              <p className="type-body text-ink-muted">Отклонённые и истёкшие приглашения.</p>
            </TabsContent>
          </Tabs>
        </Specimen>
      </Section>

      <Section
        id="header"
        title="Шапка страницы"
        description="Заголовок переносится до трёх строк и не усекается; действия уходят под заголовок, когда не помещаются."
      >
        <Card>
          <CardHeader>
            <CardTitle as="h3">Карточка с заголовком</CardTitle>
            <CardDescription>{STRESS.fspLine}</CardDescription>
          </CardHeader>
          <div className="flex min-w-0 flex-col gap-3 rounded-lg border border-dashed border-line-strong p-4">
            {/* Образец шапки страницы: на витрине уже есть h1, поэтому заголовок образца — обычный текст. */}
            <p className="type-eyebrow text-ink-muted">потребность · версия 3</p>
            <p className="type-h1 min-w-0 text-ink [overflow-wrap:anywhere]">{STRESS.needTitle}</p>
            <p className="type-body min-w-0 text-ink-muted">{STRESS.company}</p>
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <CategoryChip title="Data/ML · Middle" />
              <SalaryRange from={STRESS.salaryFrom} to={STRESS.salaryTo} size="sm" />
              <Badge variant="neutral">гибрид</Badge>
            </div>
          </div>
        </Card>
      </Section>

      <StickyActionBar
        width="page"
        secondary={
          <Button variant="ghost" asChild>
            <a href="#buttons">К началу</a>
          </Button>
        }
        note={<span className="num">Сохранено в 14:02</span>}
      >
        <Button variant="secondary" asChild>
          <a href="#layers">К слоям</a>
        </Button>
        <Button variant="secondary" asChild>
          <a href="#forms">К полям форм</a>
        </Button>
      </StickyActionBar>
    </div>
  )
}
