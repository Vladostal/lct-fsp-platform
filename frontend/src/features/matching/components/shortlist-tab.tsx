import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import type { Catalog, NeedView, ShortlistItemView, ShortlistRefinement, ShortlistSnapshotView } from '@/client'
import { EmptyState, ErrorState } from '@/components/app'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Sheet, SheetBody, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { hasCode, hasStatus } from '@/lib/api'
import { formatDateTime, formatDuration } from '@/lib/format'
import { useMediaQuery } from '@/lib/hooks/use-media-query'
import { polling } from '@/lib/query'
import { cn } from '@/lib/utils'
import { matchingKeys, pinCandidate, shortlistsQuery, snapshotQuery, unpinCandidate } from '../api'
import { MATCHING } from '../content'
import { useCreateShortlist, usePairStates } from '../hooks'
import type { NeedSearch } from '../schemas'
import { MatchCardCompact } from './match-card-compact'
import { RefinePanel } from './refine-panel'

const S = MATCHING.shortlist

export function retryText(error: unknown): string {
  const sec = Number((error as { params?: Record<string, unknown> })?.params?.retry_after)
  return Number.isFinite(sec) && sec > 0 ? `через ${formatDuration(sec)}` : 'позже'
}

type Props = {
  need: NeedView
  search: NeedSearch
  catalog: Catalog | null | undefined
  /** Патч адреса: `undefined` убирает параметр. */
  setSearch: (patch: Partial<NeedSearch>, replace?: boolean) => void
  refineOpen: boolean
  setRefineOpen: (open: boolean) => void
  initialError?: string | null
}

export function ShortlistTab({ need, search, catalog, setSearch, refineOpen, setRefineOpen, initialError }: Props) {
  const queryClient = useQueryClient()
  const versions = useQuery(shortlistsQuery(need.id))
  const latest = versions.data?.find((v) => v.is_latest) ?? versions.data?.[0]
  const snapshotId = search.snapshot ?? need.latest_snapshot?.id ?? latest?.id
  const snapshot = useQuery({ ...snapshotQuery(snapshotId ?? ''), ...polling, enabled: Boolean(snapshotId) })
  const create = useCreateShortlist(need.id)
  const wide = useMediaQuery('(min-width: 1280px)')
  const [rateLimited, setRateLimited] = useState<string | null>(null)
  const [live, setLive] = useState('')
  const diffRef = useRef<HTMLDivElement>(null)
  const archived = need.status === 'archived'

  // 404 версии: сброс к последней.
  useEffect(() => {
    if (snapshot.isError && hasStatus(snapshot.error, 404) && search.snapshot) setSearch({ snapshot: undefined }, true)
  }, [snapshot.isError, snapshot.error, search.snapshot, setSearch])

  const build = (refinement: ShortlistRefinement | null, parentId?: string) => {
    setRateLimited(null)
    const known = new Set((versions.data ?? []).map((v) => v.id))
    create.mutate(
      { parent_id: parentId ?? null, refinement },
      {
        onSuccess: (snap) => {
          if (known.has(snap.id)) {
            toast.message(S.unchanged(snap.version_no))
            setSearch({ snapshot: snap.is_latest ? undefined : snap.id, category: undefined })
          } else {
            setLive(S.versionCreated(snap.version_no, snap.diff?.added ?? 0, snap.diff?.dropped ?? 0))
            setSearch({ snapshot: snap.id, category: undefined })
            setRefineOpen(false)
            setTimeout(() => diffRef.current?.focus(), 50)
          }
        },
        onError: (error) => {
          if (hasCode(error, 'shortlist_rate_limited')) setRateLimited(retryText(error))
          else toast.error('Не удалось сформировать подборку. Попробуйте ещё раз.')
        },
      },
    )
  }

  const pin = useMutation({
    mutationFn: ({ id, pinned }: { id: string; pinned: boolean }) =>
      pinned ? unpinCandidate(need.id, id) : pinCandidate(need.id, id),
    onMutate: async ({ id, pinned }) => {
      if (!snapshotId) return undefined
      const key = matchingKeys.snapshot(snapshotId)
      await queryClient.cancelQueries({ queryKey: key })
      const prev = queryClient.getQueryData<ShortlistSnapshotView>(key)
      if (prev) {
        const flip = (i: ShortlistItemView) => (i.candidate_id === id ? { ...i, pinned: !pinned } : i)
        queryClient.setQueryData(key, {
          ...prev,
          items: prev.items.map(flip),
          pinned_outside: prev.pinned_outside.map(flip),
        })
      }
      return { prev, key }
    },
    onError: (error, _vars, ctx) => {
      if (ctx?.prev) queryClient.setQueryData(ctx.key, ctx.prev)
      toast.error(hasCode(error, 'pin_limit') ? S.pinLimit : 'Не удалось изменить закрепление')
    },
    onSettled: () => {
      if (snapshotId) void queryClient.invalidateQueries({ queryKey: matchingKeys.snapshot(snapshotId) })
    },
  })

  const snap = snapshot.data
  const items = snap?.items ?? []
  const pairs = usePairStates([...items, ...(snap?.pinned_outside ?? [])].map((i) => i.candidate_id))

  const visible = useMemo(() => {
    return items.filter((i) => {
      if (search.category && i.category.code !== search.category) return false
      if ((search.view ?? 'all') === 'pinned') return Boolean(i.pinned)
      if ((search.view ?? 'all') === 'fsp') return Boolean(i.fsp_summary)
      if ((search.view ?? 'all') === 'not_invited') return !pairs.get(i.candidate_id)?.invitation
      return true
    })
  }, [items, search.category, search.view, pairs])

  const onOpen = (id: string) => setSearch({ candidate: id, invite: undefined, revises: undefined })

  if (versions.isPending || (snapshotId && snapshot.isPending)) {
    return (
      <div className="flex min-w-0 flex-col gap-3" aria-busy="true">
        <span role="status" className="sr-only">
          Загружаем подборку…
        </span>
        <Skeleton className="h-11 w-full max-w-md" />
        {[0, 1, 2, 3].map((n) => (
          <Skeleton key={n} className="h-[104px] w-full" />
        ))}
      </div>
    )
  }
  if (versions.isError) return <ErrorState error={versions.error} onRetry={() => versions.refetch()} compact />
  if (snapshot.isError && !hasStatus(snapshot.error, 404))
    return <ErrorState error={snapshot.error} onRetry={() => snapshot.refetch()} compact />

  if (!snapshotId || !snap) {
    return (
      <div className="flex min-w-0 flex-col gap-4">
        {initialError ? (
          <Alert variant="warning">
            <AlertDescription>{initialError}</AlertDescription>
          </Alert>
        ) : null}
        <EmptyState
          title={S.emptyTitle}
          text={S.emptyText}
          action={
            archived ? undefined : (
              <Button type="button" variant="primary" loading={create.isPending} onClick={() => build({}, undefined)}>
                {S.build}
              </Button>
            )
          }
        />
      </div>
    )
  }

  const latestNo = latest?.version_no ?? snap.version_no
  const hiddenByFsp = snap.dropped.filter((d) => d.reason_code === 'require_fsp').length
  const sections = (['exact', 'lower_with_margin', 'higher'] as const)
    .map((rel) => ({ rel, rows: visible.filter((i) => i.relation === rel) }))
    .filter((s) => s.rows.length > 0)
  const noSkills = (snap.query.must_skills?.length ?? 0) + (snap.query.nice_skills?.length ?? 0) === 0
  const refine = (
    <RefinePanel
      key={snap.id}
      query={snap.query}
      catalog={catalog}
      pending={create.isPending}
      rateLimited={rateLimited}
      hiddenByFsp={hiddenByFsp}
      onApply={(r) => build(r, snap.id)}
      onReset={() => build({}, snap.id)}
    />
  )

  return (
    <div className={cn('grid min-w-0 gap-6', refineOpen && wide && !archived && 'grid-cols-[320px_minmax(0,1fr)]')}>
      {refineOpen && wide && !archived ? (
        <aside aria-label={MATCHING.refine.title} className="surface-card h-fit min-w-0 p-4">
          <div className="mb-4 flex items-center justify-between gap-2">
            <h2 className="type-h3">{MATCHING.refine.title}</h2>
            <Button type="button" variant="ghost" size="sm" onClick={() => setRefineOpen(false)}>
              {MATCHING.refine.close}
            </Button>
          </div>
          {refine}
        </aside>
      ) : null}
      {refineOpen && !wide && !archived ? (
        <Sheet open onOpenChange={setRefineOpen}>
          <SheetContent>
            <SheetHeader>
              <SheetTitle>{MATCHING.refine.title}</SheetTitle>
              <SheetDescription className="sr-only">Изменённые поля создадут новую версию подборки</SheetDescription>
            </SheetHeader>
            <SheetBody>{refine}</SheetBody>
          </SheetContent>
        </Sheet>
      ) : null}

      <div className="flex min-w-0 flex-col gap-5">
        {archived ? (
          <Alert variant="info">
            <AlertDescription>{S.archivedBanner}</AlertDescription>
          </Alert>
        ) : null}
        {initialError ? (
          <Alert variant="warning">
            <AlertDescription>{initialError}</AlertDescription>
          </Alert>
        ) : null}

        <div className="flex min-w-0 flex-wrap items-end justify-between gap-3">
          <div className="flex min-w-0 flex-col gap-1.5">
            <span id="ver-label" className="type-sm font-medium">
              {S.versionLabel}
            </span>
            <Select
              value={snap.id}
              onValueChange={(id) => setSearch({ snapshot: id === latest?.id ? undefined : id, category: undefined })}
            >
              <SelectTrigger aria-labelledby="ver-label" className="w-full max-w-[min(28rem,calc(100vw-2rem))]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(versions.data ?? []).map((v) => (
                  <SelectItem key={v.id} value={v.id}>
                    Версия {v.version_no} · {formatDateTime(v.created_at)} · {v.query_changes ?? S.byDescription}
                    {v.is_latest ? ` · ${S.latest}` : ''}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {!archived ? (
            <Button
              type="button"
              variant="secondary"
              onClick={() => setRefineOpen(!refineOpen)}
              aria-expanded={refineOpen}
            >
              {S.refine}
            </Button>
          ) : null}
        </div>

        {!snap.is_latest ? (
          <Alert variant="info">
            <AlertDescription className="flex min-w-0 flex-wrap items-center gap-3">
              <span>{S.viewing(snap.version_no, latestNo)}</span>
              <Button type="button" variant="link" size="sm" onClick={() => setSearch({ snapshot: undefined })}>
                {S.toLatest}
              </Button>
            </AlertDescription>
          </Alert>
        ) : null}

        <div ref={diffRef} tabIndex={-1} className="min-w-0 outline-none" aria-live="polite">
          <span className="sr-only">{live}</span>
          {snap.diff && snap.parent_id ? (
            <p className="type-sm min-w-0 break-words">
              {S.diff(Math.max(1, snap.version_no - 1))}: новых <span className="num">{snap.diff.added ?? 0}</span> ·
              выпало <span className="num">{snap.diff.dropped ?? 0}</span> · выше{' '}
              <span className="num">{snap.diff.moved_up ?? 0}</span> · ниже{' '}
              <span className="num">{snap.diff.moved_down ?? 0}</span>
            </p>
          ) : null}
          {snap.dropped.length > 0 && snap.parent_id ? (
            <details className="mt-2 min-w-0">
              <summary className="tap-target type-sm cursor-pointer">
                {S.droppedTitle} ({snap.dropped.length})
              </summary>
              <ul className="mt-2 flex min-w-0 flex-col gap-1">
                {snap.dropped.map((d) => (
                  <li key={d.candidate_id} className="type-sm min-w-0 break-words">
                    <span className="num">{d.public_code}</span> · {d.category.title} · {d.reason_text}
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </div>

        <section aria-label={S.funnelTitle} className="min-w-0">
          <p className="type-sm min-w-0 break-words text-ink-muted">
            <span className="font-medium text-ink">{S.funnelTitle}:</span> {S.funnel[0]}{' '}
            <span className="num">{snap.funnel.category_total ?? 0}</span> → {S.funnel[1]}{' '}
            <span className="num">{snap.funnel.available ?? 0}</span> → {S.funnel[2]}{' '}
            <span className="num">{snap.funnel.format_ok ?? 0}</span> → {S.funnel[3]}{' '}
            <span className="num">{snap.funnel.must_ok ?? 0}</span> → {S.funnel[4]}{' '}
            <span className="num">{snap.funnel.shown ?? 0}</span>.{' '}
            <Link to="/how-it-works" hash="matching" className="text-link">
              {S.calc}
            </Link>
          </p>
          {noSkills ? <p className="type-sm mt-1 text-ink-muted">{S.noSkills}</p> : null}
        </section>

        {snap.hints.length > 0 && !archived ? (
          <section aria-label={S.hints} className="grid min-w-0 gap-3 md:grid-cols-3">
            {snap.hints.slice(0, 3).map((h) => (
              <div key={`${h.code}-${h.value}`} className="surface-card flex min-w-0 flex-col gap-2 p-4">
                <p className="type-sm min-w-0 break-words font-medium">{h.text}</p>
                <p className="type-caption text-ink-muted">{MATCHING.hint.source}</p>
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  className="self-start"
                  disabled={create.isPending}
                  onClick={() => build(h.refinement, snap.id)}
                >
                  {MATCHING.hint.apply}
                </Button>
              </div>
            ))}
          </section>
        ) : null}

        {snap.categories.length > 0 ? (
          <section aria-label={S.categories} className="flex min-w-0 flex-col gap-2">
            <h2 className="type-sm font-medium">{S.categories}</h2>
            <ul className="flex min-w-0 flex-wrap gap-2">
              <li>
                <Button
                  type="button"
                  size="sm"
                  variant={search.category ? 'secondary' : 'primary'}
                  aria-pressed={!search.category}
                  onClick={() => setSearch({ category: undefined })}
                >
                  {S.allCategories}
                </Button>
              </li>
              {snap.categories.map((c) => (
                <li key={c.category.code} className="min-w-0 max-w-full">
                  <Button
                    type="button"
                    size="sm"
                    variant={search.category === c.category.code ? 'primary' : 'secondary'}
                    aria-pressed={search.category === c.category.code}
                    disabled={c.count === 0}
                    className="max-w-full"
                    onClick={() => setSearch({ category: c.category.code })}
                  >
                    <span className="min-w-0 truncate" title={`${c.category.title} — ${c.relation_label}`}>
                      {c.category.title} — {c.relation_label} · {c.count}
                    </span>
                  </Button>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 flex-col gap-1">
            <ToggleGroup
              type="single"
              value={search.view ?? 'all'}
              aria-label="Быстрый вид"
              onValueChange={(v) => v && setSearch({ view: v as NeedSearch['view'] })}
            >
              {(Object.keys(S.views) as (keyof typeof S.views)[]).map((v) => (
                <ToggleGroupItem key={v} value={v}>
                  {S.views[v]}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
            <span className="type-caption text-ink-muted">{S.viewNote}</span>
          </div>
          {snap.hidden_count > 0 ? <p className="type-sm text-ink-muted">{S.hidden(snap.hidden_count)}</p> : null}
        </div>

        {items.length === 0 ? (
          <EmptyState
            title={S.noRows}
            text={S.noRowsText}
            action={
              archived ? undefined : (
                <Button type="button" variant="secondary" onClick={() => setRefineOpen(true)}>
                  {S.refine}
                </Button>
              )
            }
          />
        ) : visible.length === 0 ? (
          <EmptyState
            title={S.viewEmpty}
            action={
              <Button type="button" variant="secondary" onClick={() => setSearch({ view: 'all', category: undefined })}>
                {S.showAll}
              </Button>
            }
          />
        ) : (
          sections.map(({ rel, rows }) => (
            <section key={rel} aria-label={S.sections[rel]} className="flex min-w-0 flex-col gap-3">
              <h2 className="type-h3 border-b border-line pb-2">{S.sections[rel]}</h2>
              <ul className="flex min-w-0 flex-col gap-3">
                {rows.map((item) => (
                  <MatchCardCompact
                    key={item.candidate_id}
                    variant="shortlist"
                    item={item}
                    pair={pairs.get(item.candidate_id)}
                    onOpen={onOpen}
                    onPinToggle={(id, pinned) => pin.mutate({ id, pinned })}
                  />
                ))}
              </ul>
            </section>
          ))
        )}

        {snap.pinned_outside.length > 0 ? (
          <section aria-label={S.pinnedOutside} className="flex min-w-0 flex-col gap-3">
            <h2 className="type-h3 border-b border-line pb-2">{S.pinnedOutside}</h2>
            <ul className="flex min-w-0 flex-col gap-3">
              {snap.pinned_outside.map((item) => (
                <MatchCardCompact
                  key={item.candidate_id}
                  variant="shortlist"
                  item={item}
                  pair={pairs.get(item.candidate_id)}
                  onOpen={onOpen}
                  onPinToggle={(id, pinned) => pin.mutate({ id, pinned })}
                />
              ))}
            </ul>
          </section>
        ) : null}

        <p className="type-sm">
          <Link to="/employer/search" search={{ category: need.target.code }} className="text-link">
            {S.bankLink}
          </Link>
        </p>
      </div>
    </div>
  )
}
