import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'
import type { Catalog } from '@/client'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { errorMessage, hasCode } from '@/lib/api'
import { formatDate } from '@/lib/format'
import { invalidateGuardData } from '@/lib/guards'
import { msUntil } from '@/lib/time'
import { assessmentKeys, putClaim } from '../api'
import { ASSESSMENT } from '../content'

const D = ASSESSMENT.category.declared

export type DeclaredGradeFormProps = {
  catalog: Catalog | null
  /** Название специализации, по которой теста пока нет. */
  specialization: string
  /** Уже заявленный грейд по этой специализации; null — грейд ещё не заявлен. */
  current: { gradeCode: string; assignedAt: string; changeAvailableAt: string } | null
  /** Есть категория по другой специализации: заявление грейда её заменит. */
  replaces?: boolean
}

/**
 * Заявить или сменить заявленный грейд там, где теста нет. Мастер сюда не возвращает (категория уже есть —
 * охрана считает шаги пройденными), поэтому форма стоит прямо на экране категории.
 * Первая смена свободна: у нового заявления `change_available_at` равен `assigned_at`; смена сдвигает срок на 90 дней.
 * Поэтому «ещё не менял» определяется равенством этих дат, а не часами: сразу после заявления срок совпадает
 * с текущим временем, и расхождение часов в секунду закрыло бы форму.
 */
export function DeclaredGradeForm({ catalog, specialization, current, replaces = false }: DeclaredGradeFormProps) {
  const queryClient = useQueryClient()
  const grades = [...(catalog?.grades ?? [])].sort((a, b) => a.order - b.order)
  const [selected, setSelected] = useState(current?.gradeCode ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const days = Number(catalog?.limits.assessment_grade_change_cooldown_days ?? 90)
  const changed = current != null && Date.parse(current.changeAvailableAt) !== Date.parse(current.assignedAt)
  const locked = current != null && changed && msUntil(current.changeAvailableAt) > 0
  const unchanged = selected === (current?.gradeCode ?? '')

  const submit = async () => {
    if (!selected || unchanged) return
    setSaving(true)
    setError(null)
    try {
      await putClaim(selected)
      await Promise.all([
        invalidateGuardData(queryClient),
        queryClient.invalidateQueries({ queryKey: assessmentKeys.evidence }),
        queryClient.invalidateQueries({ queryKey: assessmentKeys.consents }),
      ])
      toast.success(D.saved)
    } catch (e) {
      // Срок смены мог наступить иначе, чем думает экран (демо-часы): перечитываем состояние.
      if (hasCode(e, 'cooldown_active')) await invalidateGuardData(queryClient)
      setError(errorMessage(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex min-w-0 flex-col gap-3" data-slot="declared-grade-form">
      {current ? null : <p className="type-sm min-w-0">{D.first(specialization)}</p>}
      {replaces ? <p className="type-sm min-w-0 text-warning">{D.replaces}</p> : null}
      <ToggleGroup
        type="single"
        value={selected}
        aria-label={D.formLabel}
        disabled={locked || saving}
        onValueChange={(code) => {
          if (!code) return
          setSelected(code)
          setError(null)
        }}
      >
        {grades.map((g) => (
          <ToggleGroupItem key={g.code} value={g.code}>
            {g.title}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
      <p className="type-caption min-w-0 text-ink-muted">
        {locked && current
          ? D.locked(formatDate(current.changeAvailableAt))
          : changed
            ? D.unlocked(days)
            : D.free(days)}
      </p>
      {error ? <Alert variant="destructive">{error}</Alert> : null}
      <div>
        <Button
          variant={current ? 'secondary' : 'primary'}
          loading={saving}
          disabled={locked || saving || !selected || unchanged}
          onClick={submit}
        >
          {current ? D.change : D.save}
        </Button>
      </div>
    </div>
  )
}
