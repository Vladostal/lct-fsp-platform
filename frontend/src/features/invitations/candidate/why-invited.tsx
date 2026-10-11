import { Database, Eye, Lock, Search } from 'lucide-react'
import type { EvidenceItem, EvidenceKind, InvitationWhy } from '@/client'
import { EvidenceChip, SoftPill } from '@/components/app'
import { EVIDENCE_LABELS } from '@/content/common'

export type WhyInvitedProps = { why: InvitationWhy }

/** «Почему вас пригласили»: что искал работодатель, какие навыки совпали и что он видел до ответа. */
export function WhyInvited({ why }: WhyInvitedProps) {
  const saw = why.employer_saw ?? []
  // Навыки группируются по источнику в порядке первого появления.
  const groups: [EvidenceKind, EvidenceItem[]][] = []
  for (const item of why.matched ?? []) {
    const group = groups.find(([kind]) => kind === item.kind)
    if (group) group[1].push(item)
    else groups.push([item.kind, [item]])
  }
  return (
    <div className="flex min-w-0 flex-col gap-4">
      {why.source === 'need' ? (
        <p className="type-body flex min-w-0 flex-wrap items-center gap-2 text-ink">
          <Search aria-hidden="true" className="size-4 shrink-0 text-brand-700" />
          <span className="text-ink-muted">Работодатель искал:</span>
          <span className="num min-w-0 font-medium [overflow-wrap:anywhere]">{why.target.title}</span>
        </p>
      ) : (
        <p className="type-body flex min-w-0 items-center gap-2 text-ink">
          <Database aria-hidden="true" className="size-4 shrink-0 text-brand-700" />
          <span className="min-w-0">Работодатель нашёл вас в банке кандидатов</span>
        </p>
      )}
      {groups.length > 0 ? (
        <ul className="flex min-w-0 flex-col gap-2" aria-label="Совпавшие навыки">
          {groups.map(([kind, items]) => (
            <li key={kind} className="flex min-w-0 flex-wrap items-center gap-2">
              {/* Источник назван один раз на группу; в самих чипах он остаётся для скринридера и в title. */}
              <span className="type-sm text-ink-muted" aria-hidden="true">
                {EVIDENCE_LABELS[kind].self}
              </span>
              {items.map((item) => (
                <EvidenceChip
                  key={item.skill.code}
                  kind={kind}
                  skill={item.skill.title}
                  audience="self"
                  showLabel={false}
                />
              ))}
            </li>
          ))}
        </ul>
      ) : null}
      <div className="flex min-w-0 flex-col gap-3 rounded-md bg-fill p-4">
        {saw.length > 0 ? (
          <div className="flex min-w-0 flex-col gap-2">
            <p className="type-sm flex min-w-0 items-center gap-1.5 text-ink-muted">
              <Eye aria-hidden="true" className="size-4 shrink-0" />
              До вашего ответа работодатель видел:
            </p>
            <ul className="flex min-w-0 flex-wrap gap-1.5">
              {saw.map((item) => (
                <li key={item} className="min-w-0 max-w-full">
                  <SoftPill size="sm" className="h-auto min-h-6 bg-surface py-0.5 text-ink">
                    <span className="min-w-0 [overflow-wrap:anywhere]">{item}</span>
                  </SoftPill>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        <p className="type-sm flex min-w-0 items-start gap-1.5 font-medium text-ink">
          <Lock aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          Имя и контакты работодатель не видел.
        </p>
      </div>
    </div>
  )
}
