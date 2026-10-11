import { useSyncExternalStore } from 'react'

/**
 * Тема оформления. Выбор пользователя (`light` | `dark` | `system`) лежит в localStorage под ключом `fsp-theme`;
 * на <html> стоит атрибут `data-theme="light" | "dark"` — по нему theme.css переопределяет токены.
 * До первой отрисовки атрибут ставит встроенный скрипт в index.html (та же логика, без мигания).
 */
export type ThemePreference = 'light' | 'dark' | 'system'
export type ResolvedTheme = 'light' | 'dark'

export const THEME_STORAGE_KEY = 'fsp-theme'
const DARK_QUERY = '(prefers-color-scheme: dark)'
const listeners = new Set<() => void>()

export function getThemePreference(): ThemePreference {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY)
    if (stored === 'light' || stored === 'dark') return stored
  } catch {
    // Хранилище недоступно (приватный режим, запрет cookie) — работаем по системной теме.
  }
  return 'system'
}

export function resolveTheme(preference: ThemePreference): ResolvedTheme {
  if (preference !== 'system') return preference
  return window.matchMedia(DARK_QUERY).matches ? 'dark' : 'light'
}

function apply(): void {
  document.documentElement.dataset.theme = resolveTheme(getThemePreference())
  for (const listener of listeners) listener()
}

export function setThemePreference(preference: ThemePreference): void {
  try {
    if (preference === 'system') window.localStorage.removeItem(THEME_STORAGE_KEY)
    else window.localStorage.setItem(THEME_STORAGE_KEY, preference)
  } catch {
    // Выбор не сохранится между визитами, но в этой вкладке тема всё равно сменится.
    document.documentElement.dataset.theme = resolveTheme(preference)
    for (const listener of listeners) listener()
    return
  }
  apply()
}

/** Подписка на системную тему и на смену выбора в другой вкладке. Вызывается один раз при старте. */
export function initTheme(): void {
  apply()
  window.matchMedia(DARK_QUERY).addEventListener('change', apply)
  window.addEventListener('storage', (event) => {
    if (event.key === THEME_STORAGE_KEY || event.key === null) apply()
  })
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

const currentTheme = (): ResolvedTheme => (document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light')

export function useTheme(): {
  preference: ThemePreference
  theme: ResolvedTheme
  setPreference: (preference: ThemePreference) => void
} {
  const theme = useSyncExternalStore(subscribe, currentTheme, () => 'light' as const)
  const preference = useSyncExternalStore(subscribe, getThemePreference, () => 'system' as const)
  return { preference, theme, setPreference: setThemePreference }
}
