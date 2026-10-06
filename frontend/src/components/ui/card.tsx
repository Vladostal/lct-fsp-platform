import type * as React from 'react'
import { cn } from '@/lib/utils'

/** Карточка: фон surface, радиус 24 (16 при < 768), отступ 24 (16), мягкая тень без границы (E §3.1). */
function Card({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="card"
      className={cn(
        'flex min-w-0 flex-col gap-4 rounded-lg bg-surface p-4 text-ink shadow-card md:gap-6 md:rounded-xl md:p-6',
        className,
      )}
      {...props}
    />
  )
}

function CardHeader({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="card-header"
      className={cn(
        'grid min-w-0 auto-rows-min items-start gap-1.5 has-data-[slot=card-action]:grid-cols-[minmax(0,1fr)_auto] has-data-[slot=card-action]:gap-x-4',
        className,
      )}
      {...props}
    />
  )
}

/** Заголовок карточки — h2 по умолчанию; уровень меняется пропом `as`, чтобы уровни шли без пропусков (E §7). */
function CardTitle({
  className,
  as: Comp = 'h2',
  ...props
}: React.ComponentProps<'h2'> & { as?: 'h2' | 'h3' | 'h4' | 'div' }) {
  return <Comp data-slot="card-title" className={cn('type-h2 min-w-0', className)} {...props} />
}

function CardDescription({ className, ...props }: React.ComponentProps<'p'>) {
  return <p data-slot="card-description" className={cn('type-sm min-w-0 text-ink-muted', className)} {...props} />
}

function CardAction({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="card-action"
      className={cn('col-start-2 row-span-2 row-start-1 shrink-0 self-start justify-self-end', className)}
      {...props}
    />
  )
}

function CardContent({ className, ...props }: React.ComponentProps<'div'>) {
  return <div data-slot="card-content" className={cn('min-w-0', className)} {...props} />
}

function CardFooter({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div data-slot="card-footer" className={cn('flex min-w-0 flex-wrap items-center gap-3', className)} {...props} />
  )
}

export { Card, CardAction, CardContent, CardDescription, CardFooter, CardHeader, CardTitle }
