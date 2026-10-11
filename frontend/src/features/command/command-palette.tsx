import { useRouter } from '@tanstack/react-router'
import { LogOut, Search } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import type { MeView } from '@/client'
import { Button } from '@/components/ui/button'
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from '@/components/ui/command'
import { COMMON, NAV, USER_MENU } from '@/content/common'

export type CommandPaletteProps = {
  role: MeView['role']
  onLogout: () => void
}

const ACTIONS = {
  candidate: [
    { to: '/candidate/test/new', label: 'Пройти тест' },
    { to: '/candidate/settings/privacy', label: 'Скрыть профиль' },
  ],
  employer: [
    { to: '/employer/needs/new', label: 'Новая потребность' },
    { to: '/employer/search', label: 'Открыть банк' },
  ],
} as const

function isTyping(target: EventTarget | null) {
  const el = target as HTMLElement | null
  return Boolean(el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)))
}

/** Палитра команд: ⌘K / Ctrl+K или «/» вне полей ввода. Только переходы и выход, без чтения кэша. */
export function CommandPalette({ role, onLogout }: CommandPaletteProps) {
  const router = useRouter()
  const [open, setOpen] = useState(false)

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      // `code` — физическая клавиша: в русской раскладке `key` у тех же клавиш «л» и «.».
      if ((event.metaKey || event.ctrlKey) && (event.code === 'KeyK' || event.key.toLowerCase() === 'k')) {
        event.preventDefault()
        setOpen((value) => !value)
      } else if (
        (event.key === '/' || (event.code === 'Slash' && !event.shiftKey)) &&
        !isTyping(event.target) &&
        !event.metaKey &&
        !event.ctrlKey &&
        !event.altKey
      ) {
        event.preventDefault()
        setOpen(true)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const go = useCallback(
    (to: string) => {
      setOpen(false)
      void router.navigate({ to, viewTransition: true })
    },
    [router],
  )

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Поиск по разделам"
        className="hidden h-9 w-56 items-center gap-2 rounded-full bg-fill px-3 text-sm text-ink-muted transition-colors duration-(--dur-fast) hover:text-ink xl:flex"
      >
        <Search aria-hidden="true" className="size-4" />
        Найти…
        <kbd className="ml-auto text-xs whitespace-nowrap">⌘K</kbd>
      </button>
      <Button
        variant="ghost"
        size="icon"
        className="size-11 xl:hidden"
        aria-label="Поиск по разделам"
        onClick={() => setOpen(true)}
      >
        <Search aria-hidden="true" />
      </Button>
      {/* Монтируем только открытой: sr-only заголовок диалога вне портала иначе попадает в проверки вёрстки. */}
      {open ? (
        <CommandDialog
          open={open}
          onOpenChange={setOpen}
          title="Поиск по разделам"
          description="Переходы и действия"
          showCloseButton={false}
          className="glass shadow-float top-[20vh] max-w-[560px] translate-y-0 rounded-xl"
        >
          <CommandInput placeholder="Найти…" />
          <CommandList>
            <CommandEmpty>Ничего не найдено</CommandEmpty>
            <CommandGroup heading="Перейти">
              {[...NAV[role], ...USER_MENU[role]].map((item) => (
                <CommandItem key={item.to} value={item.label} onSelect={() => go(item.to)}>
                  {item.label}
                </CommandItem>
              ))}
            </CommandGroup>
            <CommandSeparator />
            <CommandGroup heading="Действия">
              {ACTIONS[role].map((item) => (
                <CommandItem key={item.label} value={item.label} onSelect={() => go(item.to)}>
                  {item.label}
                </CommandItem>
              ))}
            </CommandGroup>
            <CommandSeparator />
            <CommandGroup heading="Выйти">
              <CommandItem
                value={COMMON.logout}
                onSelect={() => {
                  setOpen(false)
                  onLogout()
                }}
              >
                <LogOut aria-hidden="true" />
                {COMMON.logout}
              </CommandItem>
            </CommandGroup>
          </CommandList>
        </CommandDialog>
      ) : null}
    </>
  )
}
