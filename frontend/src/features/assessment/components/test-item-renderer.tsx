// biome-ignore-all lint/a11y/useSemanticElements: role=group/region задаёт E §4.3 для блоков кода и вариантов
// biome-ignore-all lint/a11y/noNoninteractiveTabindex: прокручиваемый блок должен получать фокус с клавиатуры (E §4.3)
import { Check } from 'lucide-react'
import { useId } from 'react'
import type { ItemTable as ItemTableData, TestItemView } from '@/client'
import { Alert } from '@/components/ui/alert'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { cn } from '@/lib/utils'
import { ASSESSMENT } from '../content'

/** Введённое значение: строка (числа, текст, один вариант), массив (несколько), номер строки кода. */
export type ItemValue = string | string[] | number | null

const NUMERIC = /^[+-]?(\d+([.,]\d*)?|[.,]\d+)$/

export const KNOWN_KINDS = ['numeric_input', 'text_input', 'single_choice', 'multi_choice', 'pick_line'] as const

export function isKnownKind(kind: string): boolean {
  return (KNOWN_KINDS as readonly string[]).includes(kind)
}

/** Тело `answer` и готовность кнопки «Ответить» по виду задания (E §2.2, C5). */
export function buildAnswer(
  item: Pick<TestItemView, 'kind'>,
  value: ItemValue,
): { valid: boolean; answer: Record<string, unknown> | null } {
  switch (item.kind) {
    case 'numeric_input': {
      const raw = typeof value === 'string' ? value : ''
      const valid = NUMERIC.test(raw.replace(/\s+/g, ''))
      return { valid, answer: valid ? { value: raw } : null }
    }
    case 'text_input': {
      const raw = typeof value === 'string' ? value : ''
      const valid = raw.trim().length > 0
      return { valid, answer: valid ? { value: raw } : null }
    }
    case 'single_choice':
      return typeof value === 'string' && value
        ? { valid: true, answer: { option_id: value } }
        : { valid: false, answer: null }
    case 'multi_choice':
      return Array.isArray(value) && value.length > 0
        ? { valid: true, answer: { option_ids: value } }
        : { valid: false, answer: null }
    case 'pick_line':
      return typeof value === 'number' ? { valid: true, answer: { line: value } } : { valid: false, answer: null }
    default:
      return { valid: false, answer: null }
  }
}

/** Таблица задания: широкая прокручивается внутри своего блока. */
export function ItemTable({ table }: { table: ItemTableData }) {
  return (
    <figure className="min-w-0 max-w-full">
      <figcaption className="type-caption num mb-1 text-ink-muted">{table.title}</figcaption>
      <div
        role="region"
        aria-label={`Таблица ${table.title}`}
        tabIndex={0}
        className="max-w-full overflow-x-auto rounded-md border border-line bg-surface"
      >
        <table className="type-sm num w-full border-collapse">
          <thead>
            <tr className="bg-fill text-left">
              {table.columns.map((c) => (
                <th key={c} scope="col" className="whitespace-nowrap px-3 py-2 font-medium">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row, r) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: строки таблицы задания не имеют идентификаторов
              <tr key={r} className="border-t border-line">
                {row.map((cell, c) => (
                  // biome-ignore lint/suspicious/noArrayIndexKey: ячейки позиционные
                  <td key={c} className="whitespace-nowrap px-3 py-2">
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </figure>
  )
}

/** Блок кода: нумерация строк, код не переносится, прокручивается сам блок. */
export function CodeBlock({ code }: { code: { language: string; text: string } }) {
  const lines = code.text.replace(/\n$/, '').split('\n')
  return (
    <div
      role="region"
      aria-label={ASSESSMENT.test.codeLabel}
      tabIndex={0}
      className="max-w-full overflow-x-auto rounded-md border border-line bg-fill"
    >
      <pre className="num type-sm w-max min-w-full py-2">
        {lines.map((line, i) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: строки кода позиционные
          <div key={i} className="flex gap-3 px-3">
            <span className="w-6 shrink-0 select-none text-right text-ink-muted">{i + 1}</span>
            <code className="whitespace-pre">{line || ' '}</code>
          </div>
        ))}
      </pre>
    </div>
  )
}

const CARD =
  'surface-row flex min-h-12 min-w-0 cursor-pointer items-center gap-3 rounded-md border border-line p-3 font-normal'

export type TestItemRendererProps = {
  item: TestItemView
  value: ItemValue
  onChange: (value: ItemValue) => void
  /** Enter в однострочном поле: экран отправляет ответ, если кнопка активна. */
  onSubmit?: () => void
  disabled?: boolean
}

/** Условие, таблицы, код и ввод по виду задания; верность ответа не показывается (E §2.2, C5). */
export function TestItemRenderer({ item, value, onChange, onSubmit, disabled }: TestItemRendererProps) {
  const inputId = useId()
  const options = item.options ?? []
  return (
    <div className="flex min-w-0 flex-col gap-4">
      {item.tables?.map((t) => (
        <ItemTable key={t.title} table={t} />
      ))}
      {item.code && item.kind !== 'pick_line' ? <CodeBlock code={item.code} /> : null}
      {item.kind === 'numeric_input' || item.kind === 'text_input' ? (
        <div className="flex min-w-0 flex-col gap-1.5">
          <Label htmlFor={inputId}>Ответ</Label>
          <div className="flex min-w-0 items-center gap-3">
            <Input
              id={inputId}
              className={cn('min-w-0 max-w-sm', item.kind === 'text_input' && 'num')}
              inputMode={item.kind === 'numeric_input' ? 'decimal' : undefined}
              autoComplete="off"
              maxLength={item.kind === 'text_input' ? (item.input?.max_length ?? undefined) : undefined}
              placeholder={item.input?.placeholder ?? undefined}
              value={typeof value === 'string' ? value : ''}
              disabled={disabled}
              onChange={(e) => onChange(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.ctrlKey && !e.metaKey) {
                  e.preventDefault()
                  onSubmit?.()
                }
              }}
            />
            {item.input?.unit ? <span className="type-sm shrink-0 text-ink-muted">{item.input.unit}</span> : null}
          </div>
          {item.kind === 'numeric_input' ? (
            <p className="type-caption text-ink-muted">{ASSESSMENT.test.unitDecimalHint}</p>
          ) : null}
        </div>
      ) : null}
      {item.kind === 'single_choice' ? (
        <RadioGroup
          aria-label="Варианты ответа"
          value={typeof value === 'string' ? value : ''}
          onValueChange={onChange}
          disabled={disabled}
        >
          {options.map((o) => (
            <Label key={o.id} className={cn(CARD, value === o.id && 'border-brand-600 bg-brand-50')}>
              <RadioGroupItem value={o.id} />
              <span className="min-w-0 break-words">{o.text}</span>
            </Label>
          ))}
        </RadioGroup>
      ) : null}
      {item.kind === 'multi_choice' ? (
        <div role="group" aria-label="Варианты ответа" className="grid gap-3">
          <p className="type-caption text-ink-muted">{ASSESSMENT.test.multiHint}</p>
          {options.map((o) => {
            const checked = Array.isArray(value) && value.includes(o.id)
            return (
              <Label key={o.id} className={cn(CARD, checked && 'border-brand-600 bg-brand-50')}>
                <Checkbox
                  checked={checked}
                  disabled={disabled}
                  onCheckedChange={(on) => {
                    const current = Array.isArray(value) ? value : []
                    onChange(on === true ? [...current, o.id] : current.filter((id) => id !== o.id))
                  }}
                />
                <span className="min-w-0 break-words">{o.text}</span>
              </Label>
            )
          })}
        </div>
      ) : null}
      {item.kind === 'pick_line' && item.code ? (
        <PickLine code={item.code} value={value} onChange={onChange} disabled={disabled} />
      ) : null}
      {!isKnownKind(item.kind) ? <Alert variant="warning">{ASSESSMENT.test.unknownKind}</Alert> : null}
    </div>
  )
}

/** Выбор строки кода: каждая строка — радио (номер и код), нумерация с 1. */
function PickLine({
  code,
  value,
  onChange,
  disabled,
}: {
  code: { text: string }
  value: ItemValue
  onChange: (value: ItemValue) => void
  disabled?: boolean
}) {
  const lines = code.text.replace(/\n$/, '').split('\n')
  return (
    <RadioGroup
      aria-label="Выберите строку"
      value={typeof value === 'number' ? String(value) : ''}
      onValueChange={(v) => onChange(Number(v))}
      disabled={disabled}
      className="max-w-full gap-0 overflow-x-auto rounded-md border border-line"
    >
      {lines.map((line, i) => {
        const n = i + 1
        const selected = value === n
        return (
          <Label
            // biome-ignore lint/suspicious/noArrayIndexKey: строки кода позиционные
            key={i}
            className={cn(
              'num type-sm flex w-max min-w-full cursor-pointer items-center gap-3 border-l-[3px] border-l-transparent px-3 py-1.5 font-normal hover:bg-fill',
              selected && 'border-l-brand-600 bg-brand-50',
            )}
          >
            <RadioGroupItem value={String(n)} className="size-4" />
            <span className="w-6 shrink-0 text-right text-ink-muted">{n}</span>
            <code className="whitespace-pre">{line || ' '}</code>
            {selected ? <Check className="size-4 shrink-0 text-brand-700" aria-hidden="true" /> : null}
          </Label>
        )
      })}
    </RadioGroup>
  )
}
