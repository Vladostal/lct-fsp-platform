import { ExternalLink as ExternalLinkIcon } from 'lucide-react'
import type * as React from 'react'
import { COMMON } from '@/content/common'
import { cn } from '@/lib/utils'

/** Внешняя ссылка: новая вкладка, rel="noopener noreferrer", иконка и скрытый текст «откроется в новой вкладке» (E §7). */
export function ExternalLink({ className, children, ...props }: React.ComponentProps<'a'>) {
  return (
    <a
      target="_blank"
      rel="noopener noreferrer"
      className={cn('text-link inline-flex max-w-full min-w-0 items-center gap-1 [overflow-wrap:anywhere]', className)}
      {...props}
    >
      <span className="min-w-0">{children}</span>
      <ExternalLinkIcon className="size-4" aria-hidden="true" />
      <span className="sr-only">({COMMON.newTab})</span>
    </a>
  )
}
