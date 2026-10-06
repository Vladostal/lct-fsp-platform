import { Link } from '@tanstack/react-router'
import { FileQuestion } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { COMMON } from '@/content/common'
import { usePageTitle } from './use-page-title'

export type NotFoundProps = {
  /** Куда вести: первый экран роли или лендинг. */
  homeHref?: string
}

/** 404 внутри текущего каркаса: «нет» и «чужое» не различаются (Арх. 11.3). */
export function NotFound({ homeHref = '/' }: NotFoundProps) {
  usePageTitle(COMMON.notFound.title)
  return (
    <div data-slot="not-found" className="flex min-w-0 flex-col items-center gap-4 px-4 py-12 text-center md:py-16">
      <span className="grid size-16 shrink-0 place-items-center rounded-full bg-fill text-ink-muted" aria-hidden="true">
        <FileQuestion className="size-10" strokeWidth={1.5} />
      </span>
      <div className="flex max-w-[52ch] min-w-0 flex-col gap-2">
        <h1 data-page-title tabIndex={-1} className="type-h1 text-ink outline-none">
          {COMMON.notFound.title}
        </h1>
        <p className="type-body text-ink-muted">{COMMON.notFound.text}</p>
      </div>
      <Button variant="secondary" asChild>
        <Link to={homeHref}>{COMMON.notFound.action}</Link>
      </Button>
    </div>
  )
}
