import { Link } from '@tanstack/react-router'
import {
  Archive,
  BellRing,
  BrainCircuit,
  Bug,
  Building2,
  ChevronRight,
  Code,
  Container,
  Database,
  Ellipsis,
  Hourglass,
  Laptop,
  type LucideIcon,
  MonitorSmartphone,
  Palette,
  Send,
  Server,
  ShieldCheck,
  Shuffle,
  Smartphone,
  Sparkles,
  UserRoundCheck,
  UserRoundX,
  Users,
} from 'lucide-react'
import type { NeedFunnel, NeedView, WorkFormat } from '@/client'
import { CategoryChip, SalaryRange } from '@/components/app'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'
import { MATCHING } from '../content'

const N = MATCHING.needs
const FORMATS = MATCHING.form.formats_

/*
 * Пульс точки «новые ответы» и подъём карточки при наведении. Кейфреймы — только при no-preference:
 * без движения точка просто стоит, карточка меняет лишь цвет границы.
 */
export const NEED_LIST_CSS = `
.nl-card{transition:border-color var(--dur-base),box-shadow var(--dur-base),transform var(--dur-base) var(--ease-enter)}
.nl-card:hover,.nl-card:focus-within{border-color:var(--color-brand-200);box-shadow:0 10px 28px -16px color-mix(in srgb,var(--color-brand-600) 45%,transparent)}
.nl-go{transition:transform var(--dur-base) var(--ease-enter),background-color var(--dur-base),color var(--dur-base)}
.nl-card:hover .nl-go{background-color:var(--color-brand-600);color:var(--color-white)}
.nl-dot{position:relative}
.nl-accent{background-image:linear-gradient(150deg,color-mix(in srgb,var(--color-brand-600) 7%,var(--color-surface)),var(--color-surface) 46%);overflow:hidden}
.nl-accent::before{content:"";position:absolute;inset:0 0 auto 0;height:3px;background:linear-gradient(90deg,var(--color-brand-600),color-mix(in srgb,var(--color-brand-600) 25%,var(--color-surface)))}
.nl-band{background-image:linear-gradient(120deg,color-mix(in srgb,var(--color-brand-600) 12%,var(--color-surface)),var(--color-surface) 62%)}
@media (prefers-reduced-motion: no-preference){
  .nl-card:hover{transform:translateY(-2px)}
  .nl-card:hover .nl-go{transform:translateX(2px)}
  .nl-dot::after{content:"";position:absolute;inset:0;border-radius:9999px;background:currentColor;animation:nl-ping 1.8s var(--ease-enter,ease-out) infinite}
}
@keyframes nl-ping{0%{opacity:.7;transform:scale(1)}70%,100%{opacity:0;transform:scale(2.8)}}
`

const TILE_RED: React.CSSProperties = {
  background: 'color-mix(in srgb, var(--color-fsp-red) 12%, var(--color-surface))',
  color: 'var(--color-fsp-red)',
}

type Look = { Icon: LucideIcon; tile?: string; style?: React.CSSProperties }

const TILE_DEFAULT = 'bg-brand-100 text-brand-700'

/*
 * Плитка специализации: явная карта, а не хеш. Только фирменные тона и зелёный: жёлтый и красный «ошибки»
 * на карточке читались бы как предупреждение. Красный маркер ФСП — через color-mix.
 */
const SPEC_LOOKS: readonly [string, Look][] = [
  ['back', { Icon: Server, tile: TILE_DEFAULT }],
  ['front', { Icon: MonitorSmartphone, tile: 'bg-brand-600 text-white' }],
  ['mobile', { Icon: Smartphone, style: TILE_RED }],
  ['android', { Icon: Smartphone, style: TILE_RED }],
  ['ios', { Icon: Smartphone, style: TILE_RED }],
  ['devops', { Icon: Container, tile: 'bg-brand-200 text-brand-900' }],
  ['sre', { Icon: Container, tile: 'bg-brand-200 text-brand-900' }],
  ['qa', { Icon: Bug, tile: 'bg-success-bg text-success' }],
  ['test', { Icon: Bug, tile: 'bg-success-bg text-success' }],
  ['ml', { Icon: BrainCircuit, tile: 'bg-brand-900 text-white' }],
  ['data', { Icon: Database, tile: 'bg-brand-900 text-white' }],
  ['analy', { Icon: Database, tile: 'bg-brand-900 text-white' }],
  ['sec', { Icon: ShieldCheck, tile: 'bg-brand-200 text-brand-900' }],
  ['design', { Icon: Palette, style: TILE_RED }],
]

function specLook(code: string): Look {
  const c = code.toLowerCase()
  return SPEC_LOOKS.find(([k]) => c.includes(k))?.[1] ?? { Icon: Code, tile: TILE_DEFAULT }
}

const FORMAT_ICON: Record<WorkFormat, LucideIcon> = { office: Building2, hybrid: Shuffle, remote: Laptop }

type StageTone = 'brand' | 'deep' | 'success'
const STAGE: Record<StageTone, { cell: string; icon: string; bar: string }> = {
  brand: { cell: 'bg-brand-100', icon: 'text-brand-600', bar: 'bg-brand-600' },
  deep: { cell: 'bg-brand-100', icon: 'text-brand-900', bar: 'bg-brand-900' },
  success: { cell: 'bg-success-bg', icon: 'text-success', bar: 'bg-success' },
}

/**
 * Ступень воронки: значок, число, подпись в одно слово. Полоса по нижнему краю — конверсия из предыдущей
 * ступени (у первой её нет: она и есть база). Доля ограничена единицей: приглашения прежних версий
 * могут превышать размер текущей подборки.
 */
function Stage({
  Icon,
  value,
  label,
  share,
  tone,
  i,
}: {
  Icon: LucideIcon
  value: number
  label: string
  share?: number
  tone: StageTone
  i: number
}) {
  const on = value > 0
  const t = STAGE[tone]
  const pct = share === undefined ? null : Math.round(Math.min(1, share) * 100)
  return (
    <li
      className={cn(
        'relative flex min-w-0 flex-1 flex-col gap-1 overflow-hidden rounded-md border px-2 pt-2.5 pb-3 sm:px-3',
        on ? `border-transparent ${t.cell}` : 'border-dashed border-line-strong',
      )}
    >
      <span className="flex min-w-0 items-center gap-1.5">
        <Icon aria-hidden="true" className={cn('size-4', on ? t.icon : 'text-ink-subtle')} />
        {on ? (
          <span className="num text-xl leading-6 font-semibold text-ink">{value}</span>
        ) : (
          <>
            <span aria-hidden="true" className="num text-xl leading-6 font-semibold text-ink-muted">
              –
            </span>
            <span className="sr-only">0</span>
          </>
        )}
      </span>
      <span className="text-[0.6875rem] leading-4 tracking-tight text-ink-muted sm:text-xs sm:tracking-normal">
        {label}
      </span>
      {on && pct !== null ? (
        <>
          <span className="sr-only">{N.share(pct)}</span>
          <span aria-hidden="true" className="absolute inset-x-0 bottom-0 block h-1.5 bg-surface/70">
            <span
              className={cn('stagger block h-full origin-left animate-grow-x rounded-r-full', t.bar)}
              style={{ width: `${pct}%`, minWidth: 6, '--i': i + 2 } as React.CSSProperties}
            />
          </span>
        </>
      ) : null}
    </li>
  )
}

const ARROW = (
  <ChevronRight aria-hidden="true" className="hidden size-4 shrink-0 self-center text-line-strong sm:block" />
)

/** Второстепенный счётчик: значок и число, смысл — в подсказке и для скринридера. */
function Count({
  Icon,
  value,
  label,
  className,
}: {
  Icon: LucideIcon
  value: number
  label: string
  className: string
}) {
  return (
    <span
      title={label}
      className={cn(
        'relative z-10 inline-flex h-7 shrink-0 items-center gap-1.5 rounded-full px-2.5 text-sm font-medium',
        className,
      )}
    >
      <Icon aria-hidden="true" className="size-4" />
      <span className="sr-only">{label}: </span>
      <span className="num">{value}</span>
    </span>
  )
}

export function NeedCard({
  need,
  stat,
  onArchive,
  index,
}: {
  need: NeedView
  stat?: NeedFunnel
  onArchive: (id: string) => void
  index: number
}) {
  const f = stat?.funnel
  const archived = need.status !== 'active'
  const snap = need.latest_snapshot
  const shortlist = snap?.items_count ?? 0
  const invited = (f?.delivered ?? 0) + (f?.not_delivered ?? 0)
  const accepted = f?.accepted ?? 0
  const awaiting = stat?.awaiting ?? 0
  const declined = f?.declined ?? 0
  const updates = stat?.updates ?? 0
  const extras = updates > 0 || awaiting > 0 || declined > 0
  const look = specLook(need.target.specialization.code)
  const TileIcon = archived ? Archive : look.Icon

  return (
    <li
      style={{ '--i': index } as React.CSSProperties}
      className={cn(
        'nl-card surface-row stagger relative flex min-w-0 animate-rise-in flex-col gap-4 p-4 md:p-5',
        archived ? 'bg-fill grayscale' : 'nl-accent',
      )}
    >
      <div className="flex min-w-0 items-start gap-3">
        <span
          aria-hidden="true"
          className={cn(
            'flex size-11 shrink-0 items-center justify-center rounded-lg',
            archived ? 'bg-surface text-ink-muted' : look.tile,
          )}
          style={archived ? undefined : look.style}
        >
          <TileIcon className="size-5" />
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <h2 title={need.title} className="type-h2 line-clamp-3 min-w-0 [overflow-wrap:anywhere] sm:line-clamp-2">
            <Link
              to="/employer/needs/$needId"
              params={{ needId: need.id }}
              className={cn(
                "after:absolute after:inset-0 after:rounded-md after:content-[''] hover:text-brand-700",
                archived ? 'text-ink-muted' : 'text-ink',
              )}
            >
              {need.title}
            </Link>
          </h2>
          <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
            <CategoryChip title={need.target.title} className="text-ink-muted" />
            {snap ? (
              <span className="num rounded-sm bg-fill px-1.5 py-0.5 text-xs font-medium text-ink-muted">
                <span aria-hidden="true">v{snap.version_no}</span>
                <span className="sr-only">
                  {N.version} {snap.version_no}
                </span>
              </span>
            ) : null}
          </span>
        </div>
        <span
          aria-hidden="true"
          className="nl-go mt-1 hidden size-7 shrink-0 sm:flex items-center justify-center rounded-full bg-brand-50 text-brand-700"
        >
          <ChevronRight className="size-4" />
        </span>
        {archived ? null : (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={`${N.menu}: ${need.title}`}
                className="relative z-10 -mt-1 -mr-1 shrink-0"
              >
                <Ellipsis aria-hidden="true" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem asChild>
                <Link to="/employer/needs/$needId/edit" params={{ needId: need.id }}>
                  {N.edit}
                </Link>
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => onArchive(need.id)}>{N.toArchive}</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>

      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <span className="inline-flex h-7 max-w-full items-center rounded-full bg-success-bg px-3">
          <SalaryRange from={need.salary_from} to={need.salary_to} size="sm" className="text-success" />
        </span>
        {need.work_formats.map((w) => {
          const Icon = FORMAT_ICON[w] ?? Laptop
          return (
            <span
              key={w}
              className="inline-flex h-7 shrink-0 items-center gap-1.5 rounded-full bg-fill px-2.5 text-sm text-ink-muted"
            >
              <Icon aria-hidden="true" className="size-4" />
              {FORMATS[w]}
            </span>
          )
        })}
      </div>

      {snap ? (
        <ol aria-label={N.pipeline} className="flex min-w-0 items-stretch gap-1.5">
          <Stage Icon={Users} value={shortlist} label={N.stageShortlist} tone="brand" i={index} />
          {ARROW}
          <Stage
            Icon={Send}
            value={invited}
            label={N.stageInvited}
            share={shortlist > 0 ? invited / shortlist : 1}
            tone="deep"
            i={index + 1}
          />
          {ARROW}
          <Stage
            Icon={UserRoundCheck}
            value={accepted}
            label={N.stageAccepted}
            share={invited > 0 ? accepted / invited : 1}
            tone="success"
            i={index + 2}
          />
        </ol>
      ) : (
        <p className="flex min-h-[4.25rem] min-w-0 items-center justify-center gap-2 rounded-md border border-dashed border-line-strong px-3 text-sm text-ink-muted">
          <Sparkles aria-hidden="true" className="size-4 shrink-0" />
          {N.noShortlist}
        </p>
      )}

      {extras ? (
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          {updates > 0 ? (
            <span
              title={N.newReplies}
              className="relative z-10 inline-flex h-7 shrink-0 animate-pop-in items-center gap-1.5 rounded-full bg-brand-600 pr-3 pl-2.5 text-sm font-medium text-white"
            >
              <span aria-hidden="true" className="nl-dot size-2 rounded-full bg-white text-white" />
              <BellRing aria-hidden="true" className="size-4" />
              <span className="sr-only">{N.newReplies}: </span>
              <span className="num">{updates}</span>
            </span>
          ) : null}
          {awaiting > 0 ? (
            <Count Icon={Hourglass} value={awaiting} label={N.awaiting} className="bg-warning-bg text-warning" />
          ) : null}
          {declined > 0 ? (
            <Count Icon={UserRoundX} value={declined} label={N.declined} className="bg-danger-bg text-danger" />
          ) : null}
        </div>
      ) : null}
    </li>
  )
}
