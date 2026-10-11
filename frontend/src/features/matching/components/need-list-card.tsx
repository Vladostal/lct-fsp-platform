import { Link } from '@tanstack/react-router'
import {
  Archive,
  BellRing,
  BrainCircuit,
  Bug,
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
  Smartphone,
  Sparkles,
  UserRoundCheck,
  UserRoundX,
  Users,
} from 'lucide-react'
import type { NeedFunnel, NeedView } from '@/client'
import {
  CategoryChip,
  CountChip,
  DashedNote,
  FORMAT_ICON,
  GoChevron,
  IconTile,
  Pipeline,
  SalaryRange,
  SoftPill,
  StageCell,
  type TileTone,
} from '@/components/app'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'
import { MATCHING } from '../content'

const N = MATCHING.needs
const FORMATS = MATCHING.form.formats_

type Look = { Icon: LucideIcon; tone: TileTone }

/*
 * Плитка специализации: явная карта, а не хеш. Только фирменные тона и зелёный: жёлтый и красный «ошибки»
 * на карточке читались бы как предупреждение. Красный маркер ФСП — тон accent.
 */
const SPEC_LOOKS: readonly [string, Look][] = [
  ['back', { Icon: Server, tone: 'brand' }],
  ['front', { Icon: MonitorSmartphone, tone: 'solid' }],
  ['mobile', { Icon: Smartphone, tone: 'accent' }],
  ['android', { Icon: Smartphone, tone: 'accent' }],
  ['ios', { Icon: Smartphone, tone: 'accent' }],
  ['devops', { Icon: Container, tone: 'deep' }],
  ['sre', { Icon: Container, tone: 'deep' }],
  ['qa', { Icon: Bug, tone: 'success' }],
  ['test', { Icon: Bug, tone: 'success' }],
  ['ml', { Icon: BrainCircuit, tone: 'ink' }],
  ['data', { Icon: Database, tone: 'ink' }],
  ['analy', { Icon: Database, tone: 'ink' }],
  ['sec', { Icon: ShieldCheck, tone: 'deep' }],
  ['design', { Icon: Palette, tone: 'accent' }],
]

function specLook(code: string): Look {
  const c = code.toLowerCase()
  return SPEC_LOOKS.find(([k]) => c.includes(k))?.[1] ?? { Icon: Code, tone: 'brand' }
}

/*
 * Ступени воронки карточки: полоса по нижнему краю — конверсия из предыдущей ступени (у первой её нет:
 * она и есть база). Приглашения прежних версий могут превышать размер текущей подборки — долю ограничивает StageCell.
 */
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
        'lift-card surface-row stagger relative flex min-w-0 animate-rise-in flex-col gap-4 p-4 md:p-5',
        archived ? 'bg-fill grayscale' : 'accent-card',
      )}
    >
      <div className="flex min-w-0 items-start gap-3">
        <IconTile icon={TileIcon} tone={archived ? 'plain' : look.tone} size="lg" />
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <h2 title={need.title} className="type-h2 line-clamp-3 min-w-0 [overflow-wrap:anywhere] sm:line-clamp-2">
            <Link
              to="/employer/needs/$needId"
              params={{ needId: need.id }}
              className={cn(
                "after:absolute after:inset-0 after:z-[1] after:rounded-md after:content-[''] hover:text-brand-700",
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
        <GoChevron className="mt-1" />
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
        <SoftPill tone="success">
          <SalaryRange from={need.salary_from} to={need.salary_to} size="sm" className="text-success" />
        </SoftPill>
        {need.work_formats.map((w) => (
          <SoftPill key={w} icon={FORMAT_ICON[w] ?? Laptop}>
            {FORMATS[w]}
          </SoftPill>
        ))}
      </div>

      {snap ? (
        <Pipeline label={N.pipeline}>
          <StageCell icon={Users} value={shortlist} label={N.stageShortlist} tone="brand" index={index} />
          <StageCell
            icon={Send}
            value={invited}
            label={N.stageInvited}
            share={shortlist > 0 ? invited / shortlist : 1}
            shareText={N.share}
            tone="deep"
            index={index + 1}
          />
          <StageCell
            icon={UserRoundCheck}
            value={accepted}
            label={N.stageAccepted}
            share={invited > 0 ? accepted / invited : 1}
            shareText={N.share}
            tone="success"
            index={index + 2}
          />
        </Pipeline>
      ) : (
        <DashedNote icon={Sparkles}>{N.noShortlist}</DashedNote>
      )}

      {extras ? (
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          {updates > 0 ? (
            <CountChip icon={BellRing} value={updates} label={N.newReplies} tone="solid" live className="z-10" />
          ) : null}
          {awaiting > 0 ? (
            <CountChip icon={Hourglass} value={awaiting} label={N.awaiting} tone="warning" className="z-10" />
          ) : null}
          {declined > 0 ? (
            <CountChip icon={UserRoundX} value={declined} label={N.declined} tone="danger" className="z-10" />
          ) : null}
        </div>
      ) : null}
    </li>
  )
}
