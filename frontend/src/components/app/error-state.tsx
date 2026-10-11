import { Link } from '@tanstack/react-router'
import { CloudOff, FileQuestion, Lock, RotateCw } from 'lucide-react'
import type * as React from 'react'
import { Button } from '@/components/ui/button'
import { COMMON } from '@/content/common'
import { errorMessage, isApiError } from '@/lib/api'
import { cn } from '@/lib/utils'

export type ErrorStateProps = {
  /** Пойманная ошибка: по ней выбираются заголовок, текст и код. */
  error?: unknown
  title?: string
  text?: React.ReactNode
  /** «Повторить» — обычно `refetch` запроса или `router.invalidate()`. */
  onRetry?: () => void
  retrying?: boolean
  /** Куда вести из состояний «нет доступа» и «не найдено». */
  homeHref?: string
  headingLevel?: 1 | 2 | 3
  compact?: boolean
  className?: string
}

/**
 * Ошибка загрузки внутри каркаса (E §2.0): навигация остаётся на месте.
 *   5xx и сеть — «Не удалось загрузить данные», «Повторить», код ошибки mono 12 px;
 *   403 — «Нет доступа к этому разделу» со ссылкой на первый экран роли;
 *   404 — «Здесь ничего нет» («нет» и «чужое» не различаются).
 */
export function ErrorState({
  error,
  title,
  text,
  onRetry,
  retrying = false,
  homeHref,
  headingLevel = 2,
  compact = false,
  className,
}: ErrorStateProps) {
  const Heading = `h${headingLevel}` as 'h1' | 'h2' | 'h3'
  const status = isApiError(error) ? error.status : null
  const kind = status === 403 ? 'forbidden' : status === 404 ? 'notFound' : 'load'

  const Icon = kind === 'forbidden' ? Lock : kind === 'notFound' ? FileQuestion : CloudOff
  const resolvedTitle =
    title ??
    (kind === 'forbidden'
      ? COMMON.forbidden.title
      : kind === 'notFound'
        ? COMMON.notFound.title
        : COMMON.loadError.title)
  const resolvedText =
    text ??
    (kind === 'forbidden'
      ? null
      : kind === 'notFound'
        ? COMMON.notFound.text
        : error !== undefined && isApiError(error) && !error.isUnavailable
          ? errorMessage(error)
          : COMMON.loadError.text)
  const code = isApiError(error) ? `${error.status || 'сеть'} · ${error.code}` : null

  return (
    <div
      data-slot="error-state"
      role="alert"
      className={cn(
        'flex min-w-0 flex-col items-center gap-4 text-center',
        compact ? 'px-4 py-8' : 'px-4 py-12 md:py-16',
        className,
      )}
    >
      <span className="grid size-16 shrink-0 place-items-center rounded-full bg-fill text-ink-muted" aria-hidden="true">
        <Icon className="size-10" strokeWidth={1.5} />
      </span>
      <div className="flex max-w-[52ch] min-w-0 flex-col gap-2">
        <Heading className="type-h3 text-ink">{resolvedTitle}</Heading>
        {resolvedText ? <p className="type-body text-ink-muted">{resolvedText}</p> : null}
      </div>
      <div className="flex min-w-0 flex-col items-center gap-3 max-[479px]:w-full max-[479px]:items-stretch">
        {kind === 'load' && onRetry ? (
          <Button variant="secondary" onClick={onRetry} loading={retrying}>
            <RotateCw aria-hidden="true" />
            {COMMON.retry}
          </Button>
        ) : null}
        {kind !== 'load' || homeHref ? (
          <Button variant={kind === 'load' && onRetry ? 'ghost' : 'secondary'} asChild>
            <Link to={homeHref ?? '/'}>{kind === 'forbidden' ? COMMON.forbidden.action : COMMON.notFound.action}</Link>
          </Button>
        ) : null}
      </div>
      {code ? <p className="type-caption num text-ink-muted">{code}</p> : null}
    </div>
  )
}
