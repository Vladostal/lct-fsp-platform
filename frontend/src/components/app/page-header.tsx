import { Link } from '@tanstack/react-router'
import { ChevronLeft } from 'lucide-react'
import type * as React from 'react'
import { Fragment } from 'react'
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '@/components/ui/breadcrumb'
import { cn } from '@/lib/utils'
import { usePageTitle } from './use-page-title'

export type Crumb = { label: string; href?: string }

export type PageHeaderProps = {
  /** Заголовок страницы — единственный h1; переносится до трёх строк и не усекается. */
  title: React.ReactNode
  /** Заголовок документа, если `title` — не строка. */
  documentTitle?: string
  /** Моноширинная подпись над заголовком. */
  eyebrow?: React.ReactNode
  description?: React.ReactNode
  /** Действия справа от заголовка; основная кнопка страницы — не больше одной. */
  actions?: React.ReactNode
  /** Хлебные крошки: последняя — текущая страница. */
  breadcrumbs?: readonly Crumb[]
  /** Ссылка «назад» над заголовком (вместо крошек на узких экранах). */
  back?: { label: string; href: string }
  /** Дополнительная строка под описанием: чипы, статусы. */
  meta?: React.ReactNode
  className?: string
}

/**
 * Шапка страницы: отвечает на вопрос «где я» (E §0, принцип 2). Заголовок получает фокус при смене маршрута
 * (`data-page-title`, tabIndex −1) и задаёт `document.title`.
 */
export function PageHeader({
  title,
  documentTitle,
  eyebrow,
  description,
  actions,
  breadcrumbs,
  back,
  meta,
  className,
}: PageHeaderProps) {
  usePageTitle(documentTitle ?? (typeof title === 'string' ? title : undefined))

  return (
    <header className={cn('flex min-w-0 flex-col gap-3', className)}>
      {breadcrumbs && breadcrumbs.length > 0 ? (
        <Breadcrumb>
          <BreadcrumbList>
            {breadcrumbs.map((crumb, index) => {
              const last = index === breadcrumbs.length - 1
              const linked = !last && !!crumb.href
              // Разделитель — соседний пункт списка: <li> внутри <li> недопустим.
              return (
                <Fragment key={`${crumb.label}-${crumb.href ?? index}`}>
                  <BreadcrumbItem className="min-w-0">
                    {linked ? (
                      <BreadcrumbLink asChild>
                        <Link to={crumb.href} className="text-link">
                          {crumb.label}
                        </Link>
                      </BreadcrumbLink>
                    ) : (
                      <BreadcrumbPage className="min-w-0">{crumb.label}</BreadcrumbPage>
                    )}
                  </BreadcrumbItem>
                  {linked ? <BreadcrumbSeparator /> : null}
                </Fragment>
              )
            })}
          </BreadcrumbList>
        </Breadcrumb>
      ) : null}
      {back && !(breadcrumbs && breadcrumbs.length > 0) ? (
        <Link
          to={back.href}
          className="inline-flex min-h-11 w-fit items-center gap-1 text-sm font-medium text-brand-700 hover:text-brand-600"
        >
          <ChevronLeft className="size-4" aria-hidden="true" />
          <span className="underline decoration-1 underline-offset-3">{back.label}</span>
        </Link>
      ) : null}
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-x-6 gap-y-4">
        <div className="flex min-w-0 flex-1 basis-80 flex-col gap-2">
          {eyebrow && !(breadcrumbs && breadcrumbs.length > 0) ? <p className="type-eyebrow">{eyebrow}</p> : null}
          <h1 data-page-title tabIndex={-1} className="type-h1 min-w-0 text-ink outline-none">
            {title}
          </h1>
          {description ? <div className="type-sm max-w-[60ch] min-w-0 text-ink-muted">{description}</div> : null}
          {meta ? <div className="flex min-w-0 flex-wrap items-center gap-2 pt-1">{meta}</div> : null}
        </div>
        {actions ? (
          <div className="flex min-w-0 shrink-0 flex-wrap items-center gap-3 max-[479px]:w-full max-[479px]:flex-col max-[479px]:items-stretch">
            {actions}
          </div>
        ) : null}
      </div>
    </header>
  )
}
