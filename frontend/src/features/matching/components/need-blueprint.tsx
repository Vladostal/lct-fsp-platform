import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { CircleCheckBig, CircleDashed, GitBranch, type LucideIcon, TrendingUp } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { BlueprintPreview } from '@/client'
import { SoftPill, type Tone } from '@/components/app'
import { previewBlueprint } from '../api'
import { MATCHING } from '../content'

const B = MATCHING.blueprint

/** Связь требования с тестом: значок и тон вместо текста в ячейке. */
const UNTESTED: { icon: LucideIcon; tone: Tone } = { icon: CircleDashed, tone: 'neutral' }
const RELATION_LOOK: Record<string, { icon: LucideIcon; tone: Tone }> = {
  direct: { icon: CircleCheckBig, tone: 'success' },
  related: { icon: GitBranch, tone: 'brand' },
  untested: UNTESTED,
  above_grade: { icon: TrendingUp, tone: 'warning' },
}

type Props = {
  specialization?: string
  grade?: string
  must: readonly string[]
  nice: readonly string[]
}

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

/** Таблица покрытия требований тестом (задержка 500 мс, пока поля меняются). */
export function NeedBlueprint({ specialization, grade, must, nice }: Props) {
  const key = JSON.stringify([specialization, grade, must, nice])
  const debounced = useDebounced(key, 500)
  const ready = Boolean(specialization && grade && must.length + nice.length > 0)
  const q = useQuery({
    queryKey: ['assessment', 'blueprint-preview', debounced],
    queryFn: ({ signal }) => {
      const [spec, g, m, n] = JSON.parse(debounced) as [string, string, string[], string[]]
      return previewBlueprint({ specialization_code: spec, grade_code: g, must_skills: m, nice_skills: n }, signal)
    },
    enabled: ready && debounced === key,
    staleTime: 60_000,
  })
  if (!ready) return <p className="type-sm text-ink-muted">{B.empty}</p>
  if (q.isPending)
    return (
      <p role="status" className="type-sm text-ink-muted">
        {B.loading}
      </p>
    )
  if (q.isError) return <p className="type-sm text-ink-muted">Покрытие сейчас недоступно.</p>
  return <CoverageTable data={q.data} />
}

export function CoverageTable({ data }: { data: BlueprintPreview }) {
  const rows = data.coverage ?? []
  return (
    <div className="flex min-w-0 flex-col gap-3">
      <div className="min-w-0 overflow-x-auto">
        <table className="type-sm w-full min-w-[420px] border-collapse text-left">
          <thead>
            <tr className="type-eyebrow border-b border-line">
              <th scope="col" className="py-2 pr-3 font-medium">
                {B.skill}
              </th>
              <th scope="col" className="py-2 pr-3 font-medium">
                {B.priority}
              </th>
              <th scope="col" className="py-2 font-medium">
                {B.relation}
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const look = RELATION_LOOK[r.relation] ?? UNTESTED
              return (
                <tr key={r.skill.code} className="border-b border-line align-middle last:border-b-0">
                  <td className="min-w-0 break-words py-2 pr-3 font-medium">{r.skill.title}</td>
                  <td className="py-2 pr-3">
                    <SoftPill tone={r.priority === 'must' ? 'brand' : 'neutral'} size="sm" className="text-xs">
                      {r.priority === 'must' ? B.must : B.nice}
                    </SoftPill>
                  </td>
                  <td className="min-w-0 py-2">
                    <SoftPill tone={look.tone} icon={look.icon} size="sm" className="text-xs">
                      {MATCHING.coverage[r.relation] ?? r.relation}
                    </SoftPill>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <Link to="/how-it-works" hash="testing" className="text-link type-sm">
        {B.link}
      </Link>
    </div>
  )
}
