import { Link } from '@tanstack/react-router'
import { APP_NAME } from '@/lib/config'
import { cn } from '@/lib/utils'

export type AppLogoProps = {
  /** Куда ведёт логотип: лендинг для гостя, первый экран роли для вошедшего. */
  href?: string
  /** Скрывать название продукта на узких экранах (шапка кабинета на 375 px). */
  compact?: boolean
  className?: string
}

/**
 * Логотип ФСП и название продукта (E §1.5). Файл логотипа — из брендбука, без изменений (`/logo_mobile.svg`),
 * высота 28 px; в тёмной теме — копия с белыми буквами (`/logo_mobile_dark.svg`, цвета знака те же); свободное поле вокруг знака обеспечивают отступы шапки.
 */
export function AppLogo({ href = '/', compact = false, className }: AppLogoProps) {
  return (
    <Link
      to={href}
      data-slot="app-logo"
      aria-label={`${APP_NAME} — на первый экран`}
      className={cn('flex min-h-11 shrink-0 items-center gap-3 rounded-md', className)}
    >
      <img src="/logo_mobile.svg" alt="ФСП" width={83} height={28} className="only-light h-7 w-auto shrink-0" />
      <img src="/logo_mobile_dark.svg" alt="ФСП" width={83} height={28} className="only-dark h-7 w-auto shrink-0" />
      <span
        className={cn(
          'border-l border-line pl-3 text-base leading-6 font-medium whitespace-nowrap text-ink',
          compact && 'max-[479px]:hidden',
        )}
      >
        {APP_NAME}
      </span>
    </Link>
  )
}
