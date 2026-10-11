import { Monitor, Moon, Sun } from 'lucide-react'
import { DropdownMenuLabel, DropdownMenuRadioGroup, DropdownMenuRadioItem } from '@/components/ui/dropdown-menu'
import { THEME } from '@/content/common'
import { type ThemePreference, useTheme } from '@/lib/theme'
import { cn } from '@/lib/utils'

const OPTIONS = [
  { value: 'system', icon: Monitor },
  { value: 'light', icon: Sun },
  { value: 'dark', icon: Moon },
] as const satisfies readonly { value: ThemePreference; icon: typeof Sun }[]

/** Переключатель темы для гостя (подвал): три кнопки-значка 44 × 44 px, выбранная отмечена `aria-pressed`. */
export function ThemeSwitch({ className }: { className?: string }) {
  const { preference, setPreference } = useTheme()
  return (
    // biome-ignore lint/a11y/useSemanticElements: группа кнопок-переключателей, не поля формы
    <div role="group" aria-label={THEME.label} data-slot="theme-switch" className={cn('flex shrink-0', className)}>
      {OPTIONS.map(({ value, icon: Icon }) => (
        <button
          key={value}
          type="button"
          aria-pressed={preference === value}
          aria-label={THEME.options[value]}
          title={THEME.options[value]}
          onClick={() => setPreference(value)}
          className="grid size-11 place-items-center rounded-full text-ink-muted transition-colors duration-(--dur-fast) hover:text-ink aria-pressed:bg-fill aria-pressed:text-ink"
        >
          <Icon aria-hidden="true" className="size-5" />
        </button>
      ))}
    </div>
  )
}

/** Тот же выбор строками меню пользователя: работает со стрелок, меню после выбора не закрывается. */
export function ThemeMenuItems() {
  const { preference, setPreference } = useTheme()
  return (
    <>
      <DropdownMenuLabel className="type-caption text-ink-muted">{THEME.label}</DropdownMenuLabel>
      <DropdownMenuRadioGroup value={preference} onValueChange={(value) => setPreference(value as ThemePreference)}>
        {OPTIONS.map(({ value, icon: Icon }) => (
          <DropdownMenuRadioItem key={value} value={value} onSelect={(event) => event.preventDefault()}>
            <Icon aria-hidden="true" />
            {THEME.options[value]}
          </DropdownMenuRadioItem>
        ))}
      </DropdownMenuRadioGroup>
    </>
  )
}
