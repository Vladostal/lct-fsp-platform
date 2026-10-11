import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import {
  ArrowRight,
  CircleCheckBig,
  CircleX,
  Clock,
  Ellipsis,
  Eye,
  FileText,
  Lightbulb,
  ListChecks,
  MailX,
  MapPin,
  MessageSquareQuote,
  Pencil,
  Send,
  Sparkles,
  Star,
  UsersRound,
} from 'lucide-react'
import { useState } from 'react'
import type { Catalog, NeedView } from '@/client'
import {
  CategoryChip,
  DashedNote,
  EmptyState,
  ErrorState,
  FunnelBars,
  IconTile,
  LegendList,
  MiniBar,
  NotFound,
  PageHeader,
  PageSkeleton,
  SalaryRange,
  SoftPill,
} from '@/components/app'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { hasStatus } from '@/lib/api'
import { formatMoney } from '@/lib/format'
import { polling } from '@/lib/query'
import { insightsQuery, needQuery } from '../api'
import { MATCHING } from '../content'
import type { NeedSearch } from '../schemas'
import { ArchiveDialog } from './archive-dialog'
import { CandidateSheet } from './candidate-sheet'
import { NeedBlueprint } from './need-blueprint'
import { ShortlistTab } from './shortlist-tab'
import { FormatPills, PANEL, PanelHead, specLook } from './visuals'

const S = MATCHING.shortlist
const FORMATS = MATCHING.form.formats_

type Props = {
  needId: string
  search: NeedSearch
  catalog: Catalog | null | undefined
  setSearch: (patch: Partial<NeedSearch>, replace?: boolean) => void
  renderInvite?: React.ComponentProps<typeof CandidateSheet>['renderInvite']
}

export function noticeKey(needId: string) {
  return `need-notice:${needId}`
}

function readNotice(needId: string): string | null {
  try {
    const v = sessionStorage.getItem(noticeKey(needId))
    if (v) sessionStorage.removeItem(noticeKey(needId))
    return v
  } catch {
    return null
  }
}

export function NeedScreen({ needId, search, catalog, setSearch, renderInvite }: Props) {
  const query = useQuery({ ...needQuery(needId), ...polling })
  const [refineOpen, setRefineOpen] = useState(false)
  const [archiveId, setArchiveId] = useState<string | null>(null)
  const [notice] = useState(() => readNotice(needId))

  if (query.isPending) return <PageSkeleton variant="list" />
  if (query.isError) {
    if (hasStatus(query.error, 404)) return <NotFound />
    return <ErrorState error={query.error} onRetry={() => query.refetch()} />
  }
  const need = query.data
  const archived = need.status === 'archived'
  const look = specLook(need.target.specialization.code)

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <PageHeader
        documentTitle={need.title}
        title={
          <span className="flex min-w-0 items-start gap-3">
            <IconTile icon={look.Icon} tone={archived ? 'neutral' : look.tone} size="lg" className="mt-0.5" />
            <span className="min-w-0 [overflow-wrap:anywhere]">{need.title}</span>
          </span>
        }
        breadcrumbs={[{ label: S.crumbs, href: '/employer/needs' }, { label: need.title }]}
        meta={
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <CategoryChip title={need.target.title} className="mr-1" />
            <SoftPill tone="success">
              <SalaryRange from={need.salary_from} to={need.salary_to} size="sm" className="text-success" />
            </SoftPill>
            <FormatPills formats={need.work_formats} />
            {need.city ? <SoftPill icon={MapPin}>{need.city}</SoftPill> : null}
          </div>
        }
        actions={
          !archived ? (
            <div className="flex items-center gap-2">
              <Button asChild variant="ghost">
                <Link to="/employer/needs/$needId/edit" params={{ needId }}>
                  <Pencil aria-hidden="true" />
                  {MATCHING.needs.edit}
                </Link>
              </Button>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button type="button" variant="ghost" size="icon" aria-label={MATCHING.needs.menu}>
                    <Ellipsis aria-hidden="true" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onSelect={() => setArchiveId(needId)}>{MATCHING.needs.toArchive}</DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          ) : undefined
        }
      />
      <Tabs value={search.tab ?? 'shortlist'} onValueChange={(tab) => setSearch({ tab: tab as NeedSearch['tab'] })}>
        <TabsList aria-label="Разделы потребности">
          <TabsTrigger value="shortlist">
            {S.tabs.shortlist}
            {need.latest_snapshot ? ` (${need.latest_snapshot.items_count})` : ''}
          </TabsTrigger>
          <TabsTrigger value="invitations">{S.tabs.invitations}</TabsTrigger>
          <TabsTrigger value="description">{S.tabs.description}</TabsTrigger>
        </TabsList>
        <TabsContent value="shortlist">
          <ShortlistTab
            need={need}
            search={search}
            catalog={catalog}
            setSearch={setSearch}
            refineOpen={refineOpen}
            setRefineOpen={setRefineOpen}
            initialError={notice}
          />
        </TabsContent>
        <TabsContent value="invitations">
          <InvitationsTab need={need} />
        </TabsContent>
        <TabsContent value="description">
          <DescriptionTab need={need} />
        </TabsContent>
      </Tabs>

      {search.candidate ? (
        <CandidateSheet
          candidateId={search.candidate}
          needId={needId}
          snapshotId={search.snapshot ?? need.latest_snapshot?.id}
          invite={Boolean(search.invite)}
          onInvite={() => setSearch({ invite: true })}
          onBackFromInvite={() => setSearch({ invite: undefined, revises: undefined })}
          onClose={() => setSearch({ candidate: undefined, invite: undefined, revises: undefined })}
          renderInvite={renderInvite}
        />
      ) : null}
      <ArchiveDialog needId={archiveId} onClose={() => setArchiveId(null)} />
    </div>
  )
}

function InvitationsTab({ need }: { need: NeedView }) {
  const q = useQuery({ ...insightsQuery(need.id), ...polling })
  if (q.isPending)
    return (
      <p role="status" className="type-sm text-ink-muted">
        Загружаем сведения…
      </p>
    )
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} compact />
  const f = q.data.funnel
  const delivered = f.delivered ?? 0
  const viewed = f.viewed ?? 0
  const accepted = f.accepted ?? 0
  const declined = f.declined ?? 0
  const expired = f.expired ?? 0
  const notDelivered = f.not_delivered ?? 0
  // По убыванию, как в общей сводке приглашений.
  const reasons = [...q.data.reasons].sort((x, y) => y.count - x.count)
  const reasonsMax = Math.max(1, ...reasons.map((r) => r.count))
  const statedMax = Math.max(
    1,
    ...q.data.stated_salary.map((s) => s.count),
    ...q.data.stated_formats.map((s) => s.count),
  )
  const stated = q.data.stated_salary.length > 0 || q.data.stated_formats.length > 0
  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div className="grid min-w-0 gap-3 lg:grid-cols-2 lg:gap-4">
        <section className={PANEL} aria-labelledby="ni-funnel">
          <PanelHead id="ni-funnel" icon={Send} title="Воронка" />
          {delivered + notDelivered > 0 ? (
            <FunnelBars
              label="Воронка приглашений"
              conversionLabel="конверсия"
              steps={[
                {
                  key: 'delivered',
                  label: 'Доставлено',
                  value: delivered,
                  icon: Send,
                  tone: 'soft',
                  color: 'brandSoft',
                },
                { key: 'viewed', label: 'Просмотрено', value: viewed, icon: Eye, tone: 'brand', color: 'brand' },
                {
                  key: 'accepted',
                  label: 'Принято',
                  value: accepted,
                  icon: CircleCheckBig,
                  tone: 'success',
                  color: 'success',
                },
              ]}
            />
          ) : (
            <DashedNote icon={Send}>Приглашений пока нет</DashedNote>
          )}
        </section>
        <section className={PANEL} aria-labelledby="ni-out">
          <PanelHead id="ni-out" icon={UsersRound} title="Исходы" />
          <LegendList
            items={[
              { key: 'accepted', label: 'Принято', value: accepted, icon: CircleCheckBig, tone: 'success' },
              { key: 'declined', label: 'Отклонено', value: declined, icon: CircleX, tone: 'danger' },
              { key: 'expired', label: 'Истекло', value: expired, icon: Clock, tone: 'warning' },
              { key: 'not_delivered', label: 'Не доставлено', value: notDelivered, icon: MailX, tone: 'dashed' },
            ]}
          />
        </section>
        <section className={PANEL} aria-labelledby="ni-reasons">
          <PanelHead id="ni-reasons" icon={CircleX} tone="danger" title="Причины отказов" />
          {reasons.length > 0 ? (
            <ul className="flex min-w-0 flex-col gap-3">
              {reasons.map((r, i) => (
                <li key={r.reason_code} className="min-w-0">
                  <MiniBar label={r.reason_label} value={r.count} max={reasonsMax} color="danger" index={i} />
                </li>
              ))}
            </ul>
          ) : (
            <DashedNote icon={CircleCheckBig}>Отказов пока нет</DashedNote>
          )}
        </section>
        {stated ? (
          <section className={PANEL} aria-labelledby="ni-stated">
            <PanelHead id="ni-stated" icon={MessageSquareQuote} title="Условия, которые назвали кандидаты" />
            <ul className="flex min-w-0 flex-col gap-3">
              {q.data.stated_salary.map((s, i) => (
                <li key={`s${s.value}`} className="min-w-0">
                  <MiniBar
                    label={`от ${formatMoney(s.value)}`}
                    value={s.count}
                    max={statedMax}
                    color="success"
                    index={i}
                  />
                </li>
              ))}
              {q.data.stated_formats.map((s, i) => (
                <li key={`f${s.value}`} className="min-w-0">
                  <MiniBar
                    label={FORMATS[s.value]}
                    value={s.count}
                    max={statedMax}
                    index={q.data.stated_salary.length + i}
                  />
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>
      {q.data.hints.length > 0 ? (
        <section className="flex min-w-0 flex-col gap-2" aria-label="Подсказки">
          <ul className="flex min-w-0 flex-col gap-2">
            {q.data.hints.slice(0, 3).map((h) => (
              <li
                key={`${h.code}${h.value}`}
                className="surface-row type-sm flex min-w-0 items-center gap-3 p-3 break-words md:px-4"
              >
                <IconTile icon={Lightbulb} tone="warning" size="sm" />
                <span className="min-w-0">{h.text}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {q.data.salary_note ? <p className="type-sm text-ink-muted">{q.data.salary_note}</p> : null}
      <Button asChild variant="secondary" className="self-start max-[479px]:w-full">
        <Link to="/employer/invitations">
          Все приглашения
          <ArrowRight aria-hidden="true" />
        </Link>
      </Button>
    </div>
  )
}

function SkillChips({ skills, tone }: { skills: { code: string; title: string }[]; tone: 'brand' | 'neutral' }) {
  if (skills.length === 0) return <span className="type-sm text-ink-muted">—</span>
  return (
    <ul className="flex min-w-0 flex-wrap gap-1.5">
      {skills.map((s) => (
        <li key={s.code} className="min-w-0 max-w-full">
          <SoftPill tone={tone} className="h-auto min-h-7 shrink py-0.5 font-medium">
            <span className="min-w-0 break-words">{s.title}</span>
          </SoftPill>
        </li>
      ))}
    </ul>
  )
}

function DescriptionTab({ need }: { need: NeedView }) {
  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div className="grid min-w-0 gap-3 lg:grid-cols-2 lg:gap-4">
        <section className={PANEL} aria-labelledby="nd-skills">
          <PanelHead id="nd-skills" icon={ListChecks} title="Навыки" />
          <dl className="flex min-w-0 flex-col gap-4">
            <div className="flex min-w-0 flex-col gap-2">
              <dt className="type-eyebrow flex items-center gap-1.5">
                <Star aria-hidden="true" className="size-3.5 text-brand-700" />
                Обязательные навыки
              </dt>
              <dd className="min-w-0">
                <SkillChips skills={need.must_skills} tone="brand" />
              </dd>
            </div>
            <div className="flex min-w-0 flex-col gap-2">
              <dt className="type-eyebrow flex items-center gap-1.5">
                <Sparkles aria-hidden="true" className="size-3.5" />
                Желательные навыки
              </dt>
              <dd className="min-w-0">
                <SkillChips skills={need.nice_skills} tone="neutral" />
              </dd>
            </div>
          </dl>
        </section>
        <section className={PANEL} aria-labelledby="nd-team">
          <PanelHead id="nd-team" icon={UsersRound} title="О команде" />
          <p className="type-body max-w-[80ch] min-w-0 whitespace-pre-line break-words">{need.team_description}</p>
        </section>
      </div>
      <section className={PANEL} aria-labelledby="nd-blueprint">
        <PanelHead id="nd-blueprint" icon={FileText} title={MATCHING.form.blueprint} />
        <NeedBlueprint
          specialization={need.target.specialization.code}
          grade={need.target.grade.code}
          must={need.must_skills.map((s) => s.code)}
          nice={need.nice_skills.map((s) => s.code)}
        />
      </section>
      {!need.latest_snapshot ? <EmptyState compact text="Подборка ещё не сформирована." /> : null}
    </div>
  )
}
