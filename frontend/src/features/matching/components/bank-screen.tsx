import { useInfiniteQuery } from '@tanstack/react-query'
import { EyeOff, Hash, Layers, RotateCcw, Search, SlidersHorizontal, Trophy, UsersRound } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import type { Catalog } from '@/client'
import {
  CountChip,
  EmptyState,
  ErrorState,
  IconTile,
  PageHeader,
  SoftPill,
  TagInput,
  type TagValue,
} from '@/components/app'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Sheet, SheetBody, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { errorMessage, hasCode } from '@/lib/api'
import { hasTest } from '@/lib/category'
import { useMediaQuery } from '@/lib/hooks/use-media-query'
import { bankQuery } from '../api'
import { MATCHING } from '../content'
import { usePairStates } from '../hooks'
import type { BankSearch } from '../schemas'
import { CandidateSheet } from './candidate-sheet'
import { MatchCardCompact } from './match-card-compact'
import { specLook } from './visuals'

const B = MATCHING.bank
const ANY = '__any'

type Props = {
  search: BankSearch
  catalog: Catalog | null | undefined
  setSearch: (patch: Partial<BankSearch>, replace?: boolean) => void
  renderInvite?: React.ComponentProps<typeof CandidateSheet>['renderInvite']
}

function Filters({ search, catalog, setSearch }: Omit<Props, 'renderInvite'>) {
  // В списке — все пары «специализация — грейд»: там, где теста нет, в банке кандидаты с заявленным грейдом
  // (пометка — как в списке специализаций). Код вне справочника (старая ссылка) добавляется, чтобы выбор был виден.
  const known = (catalog?.specializations ?? []).flatMap((sp) =>
    [...(catalog?.grades ?? [])].sort((a, b) => a.order - b.order).map((g) => `${sp.code}:${g.code}`),
  )
  const categories = search.category && !known.includes(search.category) ? [...known, search.category] : known
  const skillTags = (value: string): TagValue[] =>
    value
      .split(',')
      .filter(Boolean)
      .map((c) => ({ code: c, title: catalog?.skills.find((s) => s.code === c)?.title ?? c }))
  const urlSkills = search.skills ?? ''
  const [skills, setSkills] = useState<TagValue[]>(() => skillTags(urlSkills))
  const [code, setCode] = useState(search.code ?? '')
  // Значение навыков, с которым поле и адрес в последний раз совпадали.
  const syncedSkills = useRef(urlSkills)
  const options = (catalog?.skills ?? []).map((s) => ({ code: s.code, title: s.title, aliases: s.aliases }))
  const catTitle = (c: string) => {
    const [spec, grade] = c.split(':')
    return `${catalog?.specializations.find((s) => s.code === spec)?.title_short ?? spec}, ${catalog?.grades.find((g) => g.code === grade)?.title ?? grade}`
  }
  const grades = search.grade?.split(',').filter(Boolean) ?? []
  const skillCodes = skills.map((s) => s.code).filter((c): c is string => Boolean(c))
  const skillsKey = skillCodes.join(',')

  // Адрес изменился не из этого поля (сброс фильтров, «Назад»): поля повторяют адрес. Иначе сброшенные навыки
  // через 300 мс возвращались бы в запрос.
  // biome-ignore lint/correctness/useExhaustiveDependencies: skillTags зависит только от справочника
  useEffect(() => {
    if (urlSkills === syncedSkills.current) return
    syncedSkills.current = urlSkills
    setSkills(skillTags(urlSkills))
  }, [urlSkills])
  useEffect(() => setCode(search.code ?? ''), [search.code])

  // Навыки применяются с задержкой 300 мс.
  useEffect(() => {
    if (skillsKey === syncedSkills.current) return
    const value = skillsKey || undefined
    const t = setTimeout(() => {
      syncedSkills.current = skillsKey
      setSearch({ skills: value, confirmed: value ? search.confirmed : undefined }, true)
    }, 300)
    return () => clearTimeout(t)
  }, [skillsKey, search.confirmed, setSearch])

  return (
    <form
      className="flex min-w-0 flex-col gap-5"
      onSubmit={(e) => {
        e.preventDefault()
        setSearch({ code: code.trim() || undefined })
      }}
    >
      <div className="flex min-w-0 flex-col gap-1.5">
        <Label htmlFor="b-cat" className="flex items-center gap-1.5">
          <Layers aria-hidden="true" className="size-4 text-ink-muted" />
          {B.category}
        </Label>
        <Select
          value={search.category ?? ANY}
          onValueChange={(v) =>
            setSearch({ category: v === ANY ? undefined : v, specialization: undefined, grade: undefined })
          }
        >
          <SelectTrigger id="b-cat">
            {/* В поле — только название: пометка «заявленные грейды» остаётся в списке. */}
            <SelectValue>{search.category ? catTitle(search.category) : B.anyCategory}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>{B.anyCategory}</SelectItem>
            {categories.map((c) => (
              <SelectItem key={c} value={c}>
                {catTitle(c)}
                {hasTest(catalog, c.split(':')[0]) ? '' : ` · ${B.specDeclared}`}
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
            {/* В поле — только название: пометка «заявленные грейды» остаётся в списке. */}
            <SelectValue>
              {catalog?.specializations.find((sp) => sp.code === search.specialization)?.title ?? B.anySpec}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>{B.anySpec}</SelectItem>
            {(catalog?.specializations ?? []).map((s) => (
              <SelectItem key={s.code} value={s.code}>
                {s.title}
                {s.available ? '' : ` · ${B.specDeclared}`}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <fieldset className="flex min-w-0 flex-col gap-1.5" disabled={Boolean(search.category)}>
        <legend className="type-sm mb-1.5 font-medium">{B.grade}</legend>
        <ToggleGroup
          type="multiple"
          value={grades}
          onValueChange={(next) => setSearch({ grade: next.join(',') || undefined })}
        >
          {(catalog?.grades ?? []).map((g) => (
            <ToggleGroupItem key={g.code} value={g.code}>
              {g.title}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </fieldset>
      <div className="flex min-w-0 flex-col gap-1">
        <TagInput label={B.skills} value={skills} onChange={setSkills} options={options} max={8} />
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
          <span className="flex min-w-0 items-center gap-2">
            <Trophy aria-hidden="true" className="size-4 shrink-0 text-fsp-red" />
            <span className="min-w-0">{B.fsp}</span>
          </span>
          <Switch checked={Boolean(search.fsp)} onCheckedChange={(on) => setSearch({ fsp: on || undefined })} />
        </Label>
      </div>
      <div className="flex min-w-0 flex-col gap-1.5">
        <Label htmlFor="b-code" className="flex items-center gap-1.5">
          <Hash aria-hidden="true" className="size-4 text-ink-muted" />
          {B.code}
        </Label>
        <div className="flex min-w-0 gap-2">
          <Input
            id="b-code"
            value={code}
            placeholder={B.codePlaceholder}
            className="num"
            onChange={(e) => setCode(e.target.value)}
          />
          <Button type="submit" variant="secondary">
            <Search aria-hidden="true" />
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
        <RotateCcw aria-hidden="true" />
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
    const loadError = query.isError && !hasCode(query.error, 'filter_invalid', 'cursor_invalid')
    if (loadError && items.length === 0)
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
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <SoftPill tone="brand" icon={UsersRound} className="font-medium">
            {B.found} <span className="num font-semibold">{first?.total ?? items.length}</span>
          </SoftPill>
          {first?.hidden_by_fsp ? (
            <CountChip icon={EyeOff} value={first.hidden_by_fsp} label={B.hiddenByFspLabel} />
          ) : null}
          <p className="type-caption min-w-0 text-ink-muted">{B.order}</p>
        </div>
        {grouped.map(({ s, rows }) => (
          <section key={s?.category.code ?? 'all'} className="flex min-w-0 flex-col gap-3">
            {s ? (
              <h2 className="sticky top-16 z-10 flex min-w-0 items-center gap-2.5 bg-canvas py-2">
                <IconTile
                  icon={specLook(s.category.specialization.code).Icon}
                  tone={specLook(s.category.specialization.code).tone}
                  size="xs"
                />
                <span className="num type-h3 min-w-0 truncate">{s.category.title}</span>
                <span className="num rounded-full bg-brand-50 px-2 text-xs leading-6 font-semibold text-brand-700">
                  {s.count}
                </span>
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
        {loadError ? (
          <p role="alert" className="type-sm self-center text-danger">
            {hasCode(query.error, 'bank_page_limit') ? B.bankLimit : errorMessage(query.error)}
          </p>
        ) : null}
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
          <aside
            aria-label={B.filters}
            className="surface-row sticky top-20 flex h-fit min-w-0 flex-col gap-4 self-start p-4"
          >
            <p className="type-h3 flex min-w-0 items-center gap-2.5">
              <IconTile icon={SlidersHorizontal} tone="soft" size="sm" />
              {B.filters}
              {count > 0 ? (
                <span className="num rounded-full bg-brand-600 px-2 text-xs leading-5 font-semibold text-on-brand">
                  {count}
                </span>
              ) : null}
            </p>
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
