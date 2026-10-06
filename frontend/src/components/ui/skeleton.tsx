import type * as React from 'react'
import { cn } from '@/lib/utils'

/** Скелетон: фон fill, пульсация задаётся в theme.css по [data-slot="skeleton"]; при reduced-motion статичен. */
function Skeleton({ className, ...props }: React.ComponentProps<'div'>) {
  return <div data-slot="skeleton" aria-hidden="true" className={cn('rounded-md bg-fill', className)} {...props} />
}

export { Skeleton }
