import { useInfiniteQuery } from '@tanstack/react-query'
import { SlidersHorizontal } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import type { Catalog } from '@/client'
import { EmptyState, ErrorState, PageHeader, TagInput, type TagValue } from '@/components/app'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Sheet, SheetBody, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { hasCode } from '@/lib/api'
import { useMediaQuery } from '@/lib/hooks/use-media-query'
import { bankQuery } from '../api'
import { MATCHING } from '../content'
import { usePairStates } from '../hooks'
import type { BankSearch } from '../schemas'
import { CandidateSheet } from './candidate-sheet'
import { MatchCardCompact } from './match-card-compact'

const B = MATCHING.bank
const ANY = '__any'

type Props = {
  search: BankSearch
  catalog: Catalog | null | undefined
  setSearch: (patch: Partial<BankSearch>, replace?: boolean) => void
  renderInvite?: React.ComponentProps<typeof CandidateSheet>['renderInvite']
}

function Filters({ search, catalog, setSearch }: Omit<Props, 'renderInvite'>) {
  const categories = catalog?.available_categories ?? []
  const [skills, setSkills] = useState<TagValue[]>(() =>
    (search.skills?.split(',').filter(Boolean) ?? []).map((c) => ({
      code: c,
      title: catalog?.skills.find((s) => s.code === c)?.title ?? c,
    })),
  )
  const [code, setCode] = useState(search.code ?? '')
  const options = (catalog?.skills ?? []).map((s) => ({ code: s.code, title: s.title, aliases: s.aliases }))
  const catTitle = (c: string) => {
    const [spec, grade] = c.split(':')
    return `${catalog?.specializations.find((s) => s.code === spec)?.title_short ?? spec}, ${catalog?.grades.find((g) => g.code === grade)?.title ?? grade}`
  }
  const grades = search.grade?.split(',').filter(Boolean) ?? []
  const skillCodes = skills.map((s) => s.code).filter((c): c is string => Boolean(c))
  const skillsKey = skillCodes.join(',')

  // Навыки применяются с задержкой 300 мс.
  useEffect(() => {
    const value = skillsKey || undefined
    if (value === search.skills) return
    const t = setTimeout(() => setSearch({ skills: value, confirmed: value ? search.confirmed : undefined }, true), 300)
    return () => clearTimeout(t)
  }, [skillsKey, search.skills, search.confirmed, setSearch])

  return (
    <form
      className="flex min-w-0 flex-col gap-5"
      onSubmit={(e) => {
        e.preventDefault()
        setSearch({ code: code.trim() || undefined })
      }}
    >
      <div className="flex min-w-0 flex-col gap-1.5">
        <Label htmlFor="b-cat">{B.category}</Label>
        <Select
          value={search.category ?? ANY}
          onValueChange={(v) =>
            setSearch({ category: v === ANY ? undefined : v, specialization: undefined, grade: undefined })
          }
        >
          <SelectTrigger id="b-cat">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>{B.anyCategory}</SelectItem>
            {categories.map((c) => (
              <SelectItem key={c} value={c}>
                {catTitle(c)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="flex min-w-0 flex-col gap-1.5">
        <Label htmlFor="b-spec">{B.specialization}</Label>
        <Select
          value={search.specialization ?? ANY}
          disabled={Boolean(search.category)}
          onValueChange={(v) => setSearch({ specialization: v === ANY ? undefined : v })}
        >
          <SelectTrigger id="b-spec">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>{B.anySpec}</SelectItem>
            {(catalog?.specializations ?? [])
              .filter((s) => s.available)
              .map((s) => (
                <SelectItem key={s.code} value={s.code}>
                  {s.title}
                </SelectItem>
              ))}
          </SelectContent>
        </Select>
      </div>
      <fieldset className="flex min-w-0 flex-col gap-1" disabled={Boolean(search.category)}>
        <legend className="type-sm mb-1 font-medium">{B.grade}</legend>
        {(catalog?.grades ?? [])
          .filter((g) => g.available)
          .map((g) => (
            <Label key={g.code} className="tap-target flex items-center gap-2 font-normal">
              <Checkbox
                checked={grades.includes(g.code)}
                onCheckedChange={(on) => {
                  const next = on ? [...grades, g.code] : grades.filter((x) => x !== g.code)
                  setSearch({ grade: next.join(',') || undefined })
                }}
              />
              {g.title}
            </Label>
          ))}
      </fieldset>
      <div className="flex min-w-0 flex-col gap-1">
        <TagInput label={B.skills} value={skills} onChange={setSkills} options={options} max={8} />
        <p className="type-sm text-ink-muted">{B.skillsHint}</p>
      </div>
      <div className="flex min-w-0 flex-col gap-1">
        <Label className="tap-target flex min-w-0 items-center justify-between gap-3 font-normal">
          <span className="min-w-0">{B.confirmed}</span>
          <Switch
            checked={Boolean(search.confirmed)}
            disabled={skillCodes.length === 0}
            onCheckedChange={(on) => setSearch({ confirmed: on || undefined })}
          />
        </Label>
        <p className="type-sm text-ink-muted">{B.confirmedHint}</p>
      </div>
      <div className="flex min-w-0 flex-col gap-1">
        <Label className="tap-target flex min-w-0 items-center justify-between gap-3 font-normal">
          <span className="min-w-0">{B.fsp}</span>
          <Switch checked={Boolean(search.fsp)} onCheckedChange={(on) => setSearch({ fsp: on || undefined })} />
        </Label>
        <p className="type-sm text-ink-muted">{B.fspHint}</p>
      </div>
      <div className="flex min-w-0 flex-col gap-1.5">
        <Label htmlFor="b-code">{B.code}</Label>
        <div className="flex min-w-0 gap-2">
          <Input
            id="b-code"
            value={code}
            placeholder={B.codePlaceholder}
            className="num"
            onChange={(e) => setCode(e.target.value)}
          />
          <Button type="submit" variant="secondary">
            Найти
          </Button>
        </div>
      </div>
      <Button
        type="button"
        variant="ghost"
        onClick={() => {
          setSkills([])
          setCode('')
          setSearch({
            category: undefined,
            specialization: undefined,
            grade: undefined,
            skills: undefined,
            confirmed: undefined,
            fsp: undefined,
            code: undefined,
          })
        }}
      >
        {B.reset}
      </Button>
    </form>
  )
}

export function BankScreen({ search, catalog, setSearch, renderInvite }: Props) {
  const wide = useMediaQuery('(min-width: 1280px)')
  const [filtersOpen, setFiltersOpen] = useState(false)
  const filters = useMemo(
    () => ({
      category: search.category,
      specialization: search.specialization,
      grade: search.grade,
      skills: search.skills,
      confirmed: search.confirmed,
      fsp: search.fsp,
      code: search.code,
    }),
    [search.category, search.specialization, search.grade, search.skills, search.confirmed, search.fsp, search.code],
  )
  const query = useInfiniteQuery({ ...bankQuery(filters), placeholderData: (prev) => prev })
  const pages = query.data?.pages ?? []
  const items = pages.flatMap((p) => p.items)
  const pairs = usePairStates(items.map((i) => i.candidate_id))
  const first = pages[0]
  const count = Object.values(filters).filter(Boolean).length

  // Неверный фильтр: сброс и сообщение; неверный курсор: загрузка с начала.
  useEffect(() => {
    if (!query.isError) return
    if (hasCode(query.error, 'filter_invalid')) {
      toast.error(B.badFilter)
      setSearch(
        {
          category: undefined,
          specialization: undefined,
          grade: undefined,
          skills: undefined,
          confirmed: undefined,
          fsp: undefined,
          code: undefined,
        },
        true,
      )
    } else if (hasCode(query.error, 'cursor_invalid')) void query.refetch()
  }, [query.isError, query.error, query.refetch, setSearch])

  const sectionsOrder = first?.sections ?? []
  const grouped = sectionsOrder.length
    ? sectionsOrder
        .map((s) => ({ s, rows: items.filter((i) => i.category.code === s.category.code) }))
        .filter((g) => g.rows.length > 0)
    : [{ s: null, rows: items }]

  const body = (() => {
    if (query.isPending) {
      return (
        <div className="flex min-w-0 flex-col gap-3" aria-busy="true">
          <span role="status" className="sr-only">
            Загружаем кандидатов…
          </span>
          {[0, 1, 2, 3, 4, 5].map((n) => (
            <Skeleton key={n} className="h-[104px] w-full" />
          ))}
        </div>
      )
    }
    if (query.isError && !hasCode(query.error, 'filter_invalid', 'cursor_invalid'))
      return (
        <ErrorState
          error={query.error}
          onRetry={() => query.refetch()}
          text={hasCode(query.error, 'bank_page_limit') ? B.bankLimit : undefined}
          compact
        />
      )
    if (items.length === 0)
      return (
        <EmptyState
          title={B.empty}
          action={
            <Button
              type="button"
              variant="secondary"
              onClick={() =>
                setSearch({
                  category: undefined,
                  specialization: undefined,
                  grade: undefined,
                  skills: undefined,
                  confirmed: undefined,
                  fsp: undefined,
                  code: undefined,
                })
              }
            >
              {B.emptyAction}
            </Button>
          }
        />
      )
    return (
      <div className="flex min-w-0 flex-col gap-5">
        <p className="type-sm text-ink-muted">
          {B.found} <span className="num font-medium text-ink">{first?.total ?? items.length}</span>. {B.order}
          {first?.hidden_by_fsp ? ` ${B.hiddenByFsp(first.hidden_by_fsp)}` : ''}
        </p>
        {grouped.map(({ s, rows }) => (
          <section key={s?.category.code ?? 'all'} className="flex min-w-0 flex-col gap-3">
            {s ? (
              <h2 className="type-h3 sticky top-16 z-10 border-b border-line bg-canvas py-2">
                {s.category.title} · <span className="num">{s.count}</span>
              </h2>
            ) : null}
            <ul className="flex min-w-0 flex-col gap-3">
              {rows.map((item) => (
                <MatchCardCompact
                  key={item.candidate_id}
                  variant="bank"
                  item={item}
                  pair={pairs.get(item.candidate_id)}
                  onOpen={(id) => setSearch({ candidate: id, invite: undefined })}
                />
              ))}
            </ul>
          </section>
        ))}
        {query.hasNextPage ? (
          <Button
            type="button"
            variant="secondary"
            className="self-center"
            loading={query.isFetchingNextPage}
            onClick={() => query.fetchNextPage()}
          >
            {B.more}
          </Button>
        ) : null}
      </div>
    )
  })()

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <PageHeader
        title={B.title}
        description={B.description}
        actions={
          !wide ? (
            <Button type="button" variant="secondary" onClick={() => setFiltersOpen(true)}>
              <SlidersHorizontal aria-hidden="true" />
              {B.filters} ({count})
            </Button>
          ) : undefined
        }
      />
      <div className={wide ? 'grid min-w-0 grid-cols-[280px_minmax(0,1fr)] gap-6' : 'min-w-0'}>
        {wide ? (
          <aside aria-label={B.filters} className="surface-card h-fit min-w-0 p-4">
            <Filters search={search} catalog={catalog} setSearch={setSearch} />
          </aside>
        ) : (
          <Sheet open={filtersOpen} onOpenChange={setFiltersOpen}>
            <SheetContent side="left">
              <SheetHeader>
                <SheetTitle>{B.filters}</SheetTitle>
                <SheetDescription className="sr-only">Фильтры банка кандидатов применяются сразу</SheetDescription>
              </SheetHeader>
              <SheetBody>
                <Filters search={search} catalog={catalog} setSearch={setSearch} />
              </SheetBody>
            </SheetContent>
          </Sheet>
        )}
        <div className="min-w-0">{body}</div>
      </div>
      {search.candidate ? (
        <CandidateSheet
          candidateId={search.candidate}
          invite={Boolean(search.invite)}
          onInvite={() => setSearch({ invite: true })}
          onBackFromInvite={() => setSearch({ invite: undefined })}
          onClose={() => setSearch({ candidate: undefined, invite: undefined })}
          renderInvite={renderInvite}
        />
      ) : null}
    </div>
  )
}
