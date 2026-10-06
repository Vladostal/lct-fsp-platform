import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Ellipsis } from 'lucide-react'
import { useState } from 'react'
import type { Catalog, NeedView } from '@/client'
import { CategoryChip, EmptyState, ErrorState, NotFound, PageHeader, PageSkeleton, SalaryRange } from '@/components/app'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { hasStatus } from '@/lib/api'
import { polling } from '@/lib/query'
import { insightsQuery, needQuery } from '../api'
import { MATCHING } from '../content'
import type { NeedSearch } from '../schemas'
import { ArchiveDialog } from './archive-dialog'
import { CandidateSheet } from './candidate-sheet'
import { NeedBlueprint } from './need-blueprint'
import { ShortlistTab } from './shortlist-tab'

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

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <PageHeader
        title={need.title}
        breadcrumbs={[{ label: S.crumbs, href: '/employer/needs' }, { label: need.title }]}
        meta={
          <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
            <CategoryChip title={need.target.title} />
            <SalaryRange from={need.salary_from} to={need.salary_to} size="sm" />
            {need.work_formats.map((f) => (
              <span key={f} className="type-sm rounded-full bg-fill px-3 py-1">
                {FORMATS[f]}
              </span>
            ))}
          </div>
        }
        actions={
          !archived ? (
            <div className="flex items-center gap-2">
              <Button asChild variant="ghost">
                <Link to="/employer/needs/$needId/edit" params={{ needId }}>
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
  const cells: [string, number | undefined][] = [
    ['Доставлено', f.delivered],
    ['Не доставлено', f.not_delivered],
    ['Просмотрено', f.viewed],
    ['Принято', f.accepted],
    ['Отклонено', f.declined],
    ['Истекло', f.expired],
  ]
  return (
    <div className="flex min-w-0 flex-col gap-6">
      <dl className="grid min-w-0 grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {cells.map(([label, n]) => (
          <div key={label} className="surface-card min-w-0 p-4">
            <dt className="type-sm text-ink-muted">{label}</dt>
            <dd className="type-h2 num">{n ?? 0}</dd>
          </div>
        ))}
      </dl>
      <section className="flex min-w-0 flex-col gap-2">
        <h2 className="type-h3">Причины отказов</h2>
        {q.data.reasons.length > 0 ? (
          <ul className="flex min-w-0 flex-col gap-1">
            {q.data.reasons.map((r) => (
              <li key={r.reason_code} className="type-body min-w-0 break-words">
                {r.reason_label} — <span className="num">{r.count}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="type-sm text-ink-muted">Отказов пока нет</p>
        )}
      </section>
      {q.data.stated_salary.length > 0 || q.data.stated_formats.length > 0 ? (
        <section className="flex min-w-0 flex-col gap-2">
          <h2 className="type-h3">Условия, которые назвали кандидаты</h2>
          <ul className="flex min-w-0 flex-col gap-1">
            {q.data.stated_salary.map((s) => (
              <li key={`s${s.value}`} className="type-body num">
                от {s.value.toLocaleString('ru-RU')} ₽ — {s.count}
              </li>
            ))}
            {q.data.stated_formats.map((s) => (
              <li key={`f${s.value}`} className="type-body">
                {FORMATS[s.value]} — <span className="num">{s.count}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {q.data.hints.length > 0 ? (
        <section className="flex min-w-0 flex-col gap-2">
          <h2 className="type-h3">Подсказки</h2>
          <ul className="flex min-w-0 flex-col gap-2">
            {q.data.hints.slice(0, 3).map((h) => (
              <li key={`${h.code}${h.value}`} className="surface-card type-sm min-w-0 break-words p-4">
                {h.text}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {q.data.salary_note ? <p className="type-sm text-ink-muted">{q.data.salary_note}</p> : null}
      <EmptyLink />
    </div>
  )
}

function EmptyLink() {
  return (
    <p className="type-sm">
      <Link to="/employer/invitations" className="text-link">
        Все приглашения
      </Link>
    </p>
  )
}

function DescriptionTab({ need }: { need: NeedView }) {
  const rows: [string, React.ReactNode][] = [
    ['Категория', need.target.title],
    ['Обязательные навыки', need.must_skills.map((s) => s.title).join(', ') || '—'],
    ['Желательные навыки', need.nice_skills.map((s) => s.title).join(', ') || '—'],
    ['Формат работы', need.work_formats.map((f) => FORMATS[f]).join(', ')],
    ['Город', need.city ?? '—'],
    ['Вилка', <SalaryRange key="s" from={need.salary_from} to={need.salary_to} size="sm" />],
    ['О команде', need.team_description],
  ]
  return (
    <div className="flex min-w-0 flex-col gap-6">
      <dl className="surface-card grid min-w-0 grid-cols-1 gap-x-6 gap-y-3 p-5 sm:grid-cols-[200px_minmax(0,1fr)]">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="type-sm text-ink-muted">{k}</dt>
            <dd className="type-body min-w-0 whitespace-pre-line break-words">{v}</dd>
          </div>
        ))}
      </dl>
      <section className="flex min-w-0 flex-col gap-3">
        <h2 className="type-h3">{MATCHING.form.blueprint}</h2>
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
