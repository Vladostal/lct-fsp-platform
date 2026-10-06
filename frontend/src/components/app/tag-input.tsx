import { Command as CommandPrimitive } from 'cmdk'
import { Plus, X } from 'lucide-react'
import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { Command, CommandEmpty, CommandGroup, CommandItem, CommandList } from '@/components/ui/command'
import { Popover, PopoverAnchor, PopoverContent } from '@/components/ui/popover'
import { cn } from '@/lib/utils'

export type TagOption = { code: string; title: string; aliases?: readonly string[] }
/** Выбранный тег: из справочника (`code`) либо свой (`code = null`). */
export type TagValue = { code: string | null; title: string }

export type TagInputProps = {
  value: readonly TagValue[]
  onChange: (value: TagValue[]) => void
  /** Справочник: поиск идёт по названию и алиасам. */
  options: readonly TagOption[]
  /** Наибольшее число тегов; счётчик «{n} из {max}». */
  max: number
  /** Разрешить свои теги вне справочника (у кандидата). */
  allowCustom?: boolean
  /** Наибольшая длина своего тега. */
  customMaxLength?: number
  /** Подсказка под полем после добавления своего тега. */
  customHint?: string
  placeholder?: string
  /**
   * Подпись поля. Компонент сам рисует её над полем и передаёт скринридеру: cmdk задаёт полю собственные
   * id и aria-labelledby, поэтому связать поле с внешним <label> нельзя.
   */
  label: string
  /** Не рисовать подпись над полем (она остаётся именем поля для скринридера). */
  hideLabel?: boolean
  required?: boolean
  invalid?: boolean
  disabled?: boolean
  id?: string
  className?: string
}

const normalize = (text: string) => text.trim().toLocaleLowerCase('ru')

/**
 * Поле тегов (E §3.3): Popover + Command; чипы с кнопкой удаления; счётчик.
 * Клавиатура: ввод, стрелки, Enter — добавить, Backspace в пустом поле — убрать последний, Esc — закрыть список.
 * Теги без дублей без учёта регистра.
 */
export function TagInput({
  value,
  onChange,
  options,
  max,
  allowCustom = false,
  customMaxLength = 40,
  customHint,
  placeholder = 'Начните вводить',
  label,
  hideLabel = false,
  required = false,
  invalid = false,
  disabled = false,
  id,
  className,
}: TagInputProps) {
  const autoId = useId()
  const counterId = `${id ?? autoId}-counter`
  const inputRef = useRef<HTMLInputElement>(null)
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)

  const full = value.length >= max
  const listOpen = open && !disabled && !full

  // cmdk всегда ставит полю aria-expanded="true", даже когда список закрыт. Исправляем после каждого рендера:
  // свои атрибуты cmdk записывает поверх переданных пропсов, поэтому пропсом это не задать.
  useEffect(() => {
    inputRef.current?.setAttribute('aria-expanded', listOpen ? 'true' : 'false')
  })
  const taken = useMemo(() => new Set(value.map((tag) => normalize(tag.title))), [value])
  const takenCodes = useMemo(() => new Set(value.map((tag) => tag.code).filter(Boolean)), [value])

  const q = normalize(query)
  const matches = useMemo(() => {
    const list = options.filter((option) => !takenCodes.has(option.code) && !taken.has(normalize(option.title)))
    if (!q) return list.slice(0, 50)
    return list
      .filter(
        (option) =>
          normalize(option.title).includes(q) || (option.aliases ?? []).some((alias) => normalize(alias).includes(q)),
      )
      .slice(0, 50)
  }, [options, q, taken, takenCodes])

  const exact = options.find((option) => normalize(option.title) === q)
  const canAddCustom = allowCustom && q.length > 0 && !exact && !taken.has(q) && query.trim().length <= customMaxLength
  const hasCustom = value.some((tag) => tag.code === null)

  const add = (tag: TagValue) => {
    if (full || taken.has(normalize(tag.title))) return
    onChange([...value, tag])
    setQuery('')
    inputRef.current?.focus()
  }
  const remove = (index: number) => {
    onChange(value.filter((_, i) => i !== index))
    inputRef.current?.focus()
  }

  return (
    <div data-slot="tag-input" className={cn('flex min-w-0 flex-col gap-2', className)}>
      {hideLabel ? null : (
        // Видимая подпись: имя полю даёт скрытый <label> cmdk, поэтому здесь она скрыта от скринридера,
        // а нажатие на неё переводит фокус в поле, как у обычной подписи.
        <span
          aria-hidden="true"
          className="w-fit text-sm leading-5 font-medium text-ink select-none"
          onClick={() => inputRef.current?.focus()}
        >
          {label}
          {required ? <span className="text-danger"> *</span> : null}
        </span>
      )}
      <Command label={label} shouldFilter={false} className="h-auto overflow-visible rounded-none bg-transparent">
        <Popover open={listOpen} onOpenChange={setOpen}>
          <PopoverAnchor asChild>
            {/* biome-ignore lint/a11y/noStaticElementInteractions: щелчок по рамке лишь переводит фокус в поле ввода */}
            {/* biome-ignore lint/a11y/useKeyWithClickEvents: с клавиатуры поле достижимо напрямую */}
            <div
              data-tap-area
              aria-invalid={invalid || undefined}
              className={cn(
                'flex min-h-11 w-full min-w-0 flex-wrap items-center gap-1.5 rounded-md border border-line-strong bg-surface px-2 py-1.5 transition-colors duration-(--dur-fast) focus-within:border-brand-600 hover:border-ink-muted aria-invalid:border-danger',
                disabled && 'cursor-not-allowed opacity-50',
              )}
              onClick={() => inputRef.current?.focus()}
            >
              {value.map((tag, index) => (
                <span
                  key={`${tag.code ?? 'custom'}-${tag.title}`}
                  className={cn(
                    'inline-flex min-h-7 max-w-full min-w-0 items-center gap-1 rounded-[14px] py-0.5 pr-1 pl-3 text-sm leading-5 font-medium',
                    tag.code === null
                      ? 'border border-dashed border-line-strong bg-surface text-ink-muted'
                      : 'border border-transparent bg-fill text-ink',
                  )}
                >
                  <span className="min-w-0">{tag.title}</span>
                  <button
                    type="button"
                    disabled={disabled}
                    aria-label={`Убрать ${tag.title}`}
                    onClick={(event) => {
                      event.stopPropagation()
                      remove(index)
                    }}
                    className="tap-target grid size-6 shrink-0 place-items-center rounded-full text-ink-muted transition-colors duration-(--dur-fast) hover:bg-line hover:text-ink"
                  >
                    <X className="size-3.5" aria-hidden="true" />
                  </button>
                </span>
              ))}
              <CommandPrimitive.Input
                ref={inputRef}
                value={query}
                disabled={disabled || full}
                placeholder={full ? '' : value.length === 0 ? placeholder : ''}
                aria-required={required || undefined}
                aria-describedby={counterId}
                aria-invalid={invalid || undefined}
                autoComplete="off"
                onValueChange={(text) => {
                  setQuery(text)
                  setOpen(true)
                }}
                onFocus={() => setOpen(true)}
                onKeyDown={(event) => {
                  if (event.key === 'Backspace' && query === '' && value.length > 0) {
                    event.preventDefault()
                    remove(value.length - 1)
                  }
                  if (event.key === 'Escape') setOpen(false)
                }}
                className="h-8 min-w-24 flex-1 bg-transparent px-1.5 text-base text-ink outline-none placeholder:text-ink-muted disabled:cursor-not-allowed"
              />
            </div>
          </PopoverAnchor>
          <PopoverContent
            align="start"
            sideOffset={6}
            // Список остаётся в DOM и при закрытом поповере: на него ссылается aria-controls поля.
            forceMount
            className="w-(--radix-popover-trigger-width) min-w-60 p-1 data-[state=closed]:hidden"
            onOpenAutoFocus={(event) => event.preventDefault()}
            onInteractOutside={(event) => {
              // Щелчок по самому полю не должен закрывать список.
              if (event.target instanceof Node && inputRef.current?.parentElement?.contains(event.target)) {
                event.preventDefault()
              }
            }}
          >
            <CommandList className="max-h-64">
              {matches.length === 0 && !canAddCustom ? (
                <CommandEmpty className="px-3 py-3 text-left text-sm text-ink-muted">
                  {q ? `В справочнике нет «${query.trim()}»` : 'Все подходящие значения уже добавлены'}
                </CommandEmpty>
              ) : null}
              {matches.length > 0 ? (
                <CommandGroup>
                  {matches.map((option) => (
                    <CommandItem
                      key={option.code}
                      value={option.code}
                      onSelect={() => add({ code: option.code, title: option.title })}
                      className="min-h-11 px-3 text-base"
                    >
                      <span className="min-w-0">{option.title}</span>
                    </CommandItem>
                  ))}
                </CommandGroup>
              ) : null}
              {canAddCustom ? (
                <CommandGroup>
                  <CommandItem
                    value={`__custom__${q}`}
                    onSelect={() => add({ code: null, title: query.trim() })}
                    className="min-h-11 px-3 text-base"
                  >
                    <Plus className="size-4 text-brand-700" aria-hidden="true" />
                    <span className="min-w-0">Добавить как свой тег: «{query.trim()}»</span>
                  </CommandItem>
                </CommandGroup>
              ) : null}
            </CommandList>
          </PopoverContent>
        </Popover>
      </Command>
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-x-4 gap-y-1">
        <p className="type-sm min-w-0 flex-1 basis-48 text-ink-muted">
          {allowCustom && query.trim().length > customMaxLength
            ? `Свой тег — не длиннее ${customMaxLength} знаков`
            : hasCustom && customHint
              ? customHint
              : ''}
        </p>
        <p id={counterId} className="type-caption num shrink-0 text-ink-muted" aria-live="polite">
          {value.length} из {max}
        </p>
      </div>
    </div>
  )
}
