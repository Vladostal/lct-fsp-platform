import type { InvitationWhy } from '@/client'
import { EvidenceChip } from '@/components/app'

export type WhyInvitedProps = { why: InvitationWhy }

/** «Почему вас пригласили»: что искал работодатель, какие навыки совпали и что он видел до ответа. */
export function WhyInvited({ why }: WhyInvitedProps) {
  const saw = why.employer_saw ?? []
  const matched = why.matched ?? []
  return (
    <div className="flex min-w-0 flex-col gap-3">
      <p className="type-body text-ink [overflow-wrap:anywhere]">
        {why.source === 'need'
          ? `Работодатель искал: ${why.target.title}`
          : 'Работодатель нашёл вас в банке кандидатов'}
      </p>
      {matched.length > 0 ? (
        <ul className="flex min-w-0 flex-wrap gap-2" aria-label="Совпавшие навыки">
          {matched.map((item) => (
            <li key={`${item.skill.code}-${item.kind}`} className="min-w-0 max-w-full">
              <EvidenceChip
                kind={item.kind}
                skill={item.skill.title}
                audience="self"
                label={item.kind === 'declared' ? 'указано вами в профиле' : undefined}
              />
            </li>
          ))}
        </ul>
      ) : null}
      <p className="type-sm text-ink-muted">
        {saw.length > 0 ? `До вашего ответа работодатель видел: ${saw.join(', ')}. ` : ''}
        Имя и контакты работодатель не видел.
      </p>
    </div>
  )
}
