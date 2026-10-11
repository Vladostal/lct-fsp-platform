import type { TestBlueprintView } from '@/client'
import { PLURALS, plural } from '@/lib/format'

const ITEMS = PLURALS.task

/** Строка объёма теста: базовый и предельный объём и время (Арх. 11.8, C3/C4). */
export function blueprintLine(bp: TestBlueprintView): string {
  const base = `${bp.items_min} ${plural(bp.items_min, ITEMS)} · до ${bp.time_limit_min} мин`
  return `${base}; если результат окажется на границе — до ${bp.items_max} ${plural(bp.items_max, ITEMS)} и до ${bp.time_limit_max_min} мин`
}

export function Tile({ value, label }: { value: string; label?: string }) {
  return (
    <div className="surface-card flex min-w-0 flex-col justify-center gap-0.5 p-3">
      <span className="type-body min-w-0 break-words font-numeric font-medium tabular-nums">{value}</span>
      {label ? <span className="type-caption min-w-0 text-ink-muted">{label}</span> : null}
    </div>
  )
}
