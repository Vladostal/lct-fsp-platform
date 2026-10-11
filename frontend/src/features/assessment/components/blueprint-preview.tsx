import { useQuery } from '@tanstack/react-query'
import type { BlueprintPreview as BlueprintPreviewData } from '@/client'
import { CategoryChip } from '@/components/app'
import { isFeatureEnabled } from '@/lib/features'
import { catalogQuery } from '@/lib/query'
import { cn } from '@/lib/utils'

const RELATION: Record<string, string> = {
  direct: 'проверяется напрямую',
  related: 'через смежную тему',
  untested: 'тестом не проверяется',
  above_grade: 'выше этого грейда',
}

export type BlueprintPreviewProps = {
  preview: BlueprintPreviewData
  className?: string
}

function Part({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <section className="flex min-w-0 flex-col gap-2">
      <h3 className="type-h3 min-w-0 break-words">{title}</h3>
      {note ? <p className="type-sm min-w-0 text-ink-muted">{note}</p> : null}
      {children}
    </section>
  )
}

/**
 * План теста под описание потребности (Арх. 5.4): три подписанные части, видны всегда —
 * тест категории, покрытие требований и «план под это описание — кандидату не выдаётся».
 */
export function BlueprintPreview({ preview, className }: BlueprintPreviewProps) {
  const catalog = useQuery(catalogQuery)
  const pulse = catalog.data ? isFeatureEnabled(catalog.data, 'pulse') : false
  const standard = preview.standard_slots ?? []
  const coverage = preview.coverage ?? []
  const needs = preview.need_slots ?? []
  return (
    <div className={cn('surface-card flex min-w-0 flex-col gap-5', className)}>
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <CategoryChip title={preview.target.title} />
        {preview.grade_guessed ? (
          <span className="type-caption text-ink-muted">грейд определён по описанию</span>
        ) : null}
      </div>
      <Part title="Тест категории — его получит кандидат">
        {standard.length === 0 ? (
          <p className="type-sm text-ink-muted">Состав теста пока недоступен</p>
        ) : (
          <ul className="flex min-w-0 flex-wrap gap-2">
            {standard.map((s) => (
              <li key={s.group.code} className="type-sm min-w-0 break-words rounded-full bg-fill px-3 py-1">
                {s.group.title} <span className="num text-ink-muted">· {s.slots}</span>
              </li>
            ))}
          </ul>
        )}
      </Part>
      <Part title="Что из требований проверяет тест">
        {coverage.length === 0 ? (
          <p className="type-sm text-ink-muted">Навыки в описании не найдены</p>
        ) : (
          <ul className="flex min-w-0 flex-col divide-y divide-line">
            {coverage.map((c) => (
              <li
                key={c.skill.code}
                className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-3 gap-y-1 py-2"
              >
                <span className="type-body min-w-0 break-words">
                  {c.skill.title}
                  <span className="type-caption ml-2 text-ink-muted">
                    {c.priority === 'must' ? 'обязательно' : 'желательно'}
                  </span>
                </span>
                <span className="type-sm min-w-0 text-ink-muted">{RELATION[c.relation] ?? c.relation}</span>
              </li>
            ))}
          </ul>
        )}
      </Part>
      <Part
        title="План под это описание — кандидату не выдаётся"
        note="Показывает, как изменился бы тест, если бы собирался под ваше описание."
      >
        {needs.length === 0 ? (
          <p className="type-sm text-ink-muted">Отличий от теста категории нет</p>
        ) : (
          <ul className="flex min-w-0 flex-wrap gap-2">
            {needs.map((n) => (
              <li
                key={n.group.code}
                className="type-sm min-w-0 break-words rounded-full border border-dashed border-line-strong px-3 py-1"
              >
                {n.group.title} <span className="num text-ink-muted">· {n.slots}</span>
                {n.delta !== 0 ? (
                  <span className="num ml-1 text-brand-700">{n.delta > 0 ? `+${n.delta}` : n.delta}</span>
                ) : null}
              </li>
            ))}
          </ul>
        )}
        <p className="type-caption text-ink-muted">
          {pulse
            ? 'Короткие задания под требования включены.'
            : 'Короткие задания под требования на этом стенде отключены.'}
        </p>
      </Part>
    </div>
  )
}
