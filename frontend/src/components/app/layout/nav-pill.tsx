import { Link, useLocation } from '@tanstack/react-router'
import type { LucideIcon } from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'

export type NavPillItem = {
  to: string
  label: string
  exact?: boolean
  badge?: number
  icon?: LucideIcon
}

export type NavPillProps = {
  items: readonly NavPillItem[]
  label: string
  variant: 'bar' | 'tabbar'
  /** Класс видимости для `bar` (в кабинете — xl+, в публичной шапке — md+). */
  barClassName?: string
}

function Badge({ value, className }: { value: number; className?: string }) {
  if (value <= 0) return null
  return (
    <span
      className={cn(
        'num grid h-5 min-w-5 shrink-0 place-items-center rounded-full bg-brand-600 px-1.5 text-xs leading-none font-medium text-white',
        className,
      )}
    >
      {value > 99 ? '99+' : value}
      <span className="sr-only"> ждут ответа</span>
    </span>
  )
}

/**
 * Навигация: `bar` — пилюля со скользящим индикатором под активным пунктом, `tabbar` — нижний плавающий
 * таб-бар для узких экранов (иконка, короткая подпись, красная точка у активного).
 */
export function NavPill({ items, label, variant, barClassName = 'hidden xl:flex' }: NavPillProps) {
  const { pathname } = useLocation()
  const listRef = useRef<HTMLElement>(null)
  const [box, setBox] = useState<{ x: number; w: number } | null>(null)
  const [ready, setReady] = useState(false)

  // Индикатор следует за активной ссылкой: меряем после смены маршрута и при изменении размеров.
  // biome-ignore lint/correctness/useExhaustiveDependencies: pathname — триггер перемера
  useLayoutEffect(() => {
    if (variant !== 'bar') return
    const root = listRef.current
    if (!root) return
    const measure = () => {
      const active = root.querySelector<HTMLElement>('[aria-current="page"]')
      setBox(active ? { x: active.offsetLeft, w: active.offsetWidth } : null)
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(root)
    const frame = window.requestAnimationFrame(() => setReady(true))
    return () => {
      observer.disconnect()
      window.cancelAnimationFrame(frame)
    }
  }, [pathname, variant])

  // Браузер не прокручивает уже видимый элемент в фокусе, даже если его закрывает плавающий таб-бар:
  // сдвигаем страницу сами, чтобы пользователь клавиатуры не терял фокус из виду.
  useEffect(() => {
    if (variant !== 'tabbar') return
    const onFocusIn = (event: FocusEvent) => {
      const target = event.target as HTMLElement | null
      // Перекрывать может таб-бар или липкая панель действий (тогда таб-бар скрыт).
      const bar = [listRef.current, ...document.querySelectorAll<HTMLElement>('[data-sticky="bottom"]')].find(
        (el) => el && el.getClientRects().length > 0,
      )
      if (!bar || !target || bar.contains(target)) return
      const overlap = target.getBoundingClientRect().bottom - bar.getBoundingClientRect().top
      if (overlap > -8) window.scrollBy({ top: overlap + 16, behavior: 'instant' })
    }
    document.addEventListener('focusin', onFocusIn)
    return () => document.removeEventListener('focusin', onFocusIn)
  }, [variant])

  if (variant === 'tabbar') {
    return (
      <nav
        ref={listRef}
        aria-label={label}
        data-tabbar
        data-sticky="bottom"
        className="shadow-float fixed inset-x-3 border border-line bg-surface bottom-[calc(12px+env(safe-area-inset-bottom))] z-20 mx-auto flex h-16 max-w-[440px] items-stretch rounded-xl xl:hidden"
      >
        {items.map((item) => {
          const Icon = item.icon
          return (
            <Link
              key={item.to}
              to={item.to}
              activeOptions={{ exact: item.exact ?? false }}
              className="group relative flex min-w-0 flex-1 flex-col items-center justify-center gap-0.5 rounded-xl px-0.5 text-ink-muted transition-colors duration-(--dur-fast) hover:text-ink aria-[current=page]:text-brand-700"
            >
              <span
                aria-hidden="true"
                className="absolute top-1.5 size-1 rounded-full bg-fsp-red opacity-0 transition-opacity duration-(--dur-fast) group-aria-[current=page]:opacity-100"
              />
              <span className="relative">
                {Icon ? <Icon aria-hidden="true" className="size-5" /> : null}
                {item.badge ? (
                  <Badge value={item.badge} className="absolute -top-2 -right-4 h-4 min-w-4 px-1 text-[10px]" />
                ) : null}
              </span>
              <span className="max-w-full truncate text-[11px] leading-4 font-medium">{item.label}</span>
            </Link>
          )
        })}
      </nav>
    )
  }

  return (
    <nav
      ref={listRef}
      aria-label={label}
      className={cn('relative h-10 items-center gap-1 rounded-full bg-fill p-1', barClassName)}
    >
      <span
        aria-hidden="true"
        data-ready={ready ? '' : undefined}
        className="nav-indicator shadow-card absolute top-1 left-0 h-8 rounded-full bg-surface"
        style={{ transform: `translateX(${box?.x ?? 0}px)`, width: box?.w ?? 0, opacity: box ? 1 : 0 }}
      />
      {items.map((item) => (
        <Link
          key={item.to}
          to={item.to}
          activeOptions={{ exact: item.exact ?? false }}
          className="tap-target relative z-10 inline-flex h-8 items-center gap-2 rounded-full px-4 text-sm font-medium whitespace-nowrap text-ink-muted transition-colors duration-(--dur-fast) hover:text-ink aria-[current=page]:text-brand-700"
        >
          {item.label}
          {item.badge ? <Badge value={item.badge} /> : null}
        </Link>
      ))}
    </nav>
  )
}
