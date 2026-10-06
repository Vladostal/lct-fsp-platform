import type * as React from 'react'
import { cn } from '@/lib/utils'

/*
 * Таблица данных (E §4.5): table-layout: fixed и colgroup с ширинами; горизонтальной прокрутки нет — вместо неё
 * вид меняется по ширине контейнера (@container) на стороне экрана. Числа — mono, по правому краю (класс num).
 */

function Table({ className, ...props }: React.ComponentProps<'table'>) {
  return (
    <table
      data-slot="table"
      className={cn('w-full table-fixed border-collapse text-left text-sm leading-5', className)}
      {...props}
    />
  )
}

function TableHeader({ className, ...props }: React.ComponentProps<'thead'>) {
  return <thead data-slot="table-header" className={cn('[&_tr]:border-b [&_tr]:border-line', className)} {...props} />
}

function TableBody({ className, ...props }: React.ComponentProps<'tbody'>) {
  return <tbody data-slot="table-body" className={cn('[&_tr:last-child]:border-0', className)} {...props} />
}

function TableFooter({ className, ...props }: React.ComponentProps<'tfoot'>) {
  return (
    <tfoot
      data-slot="table-footer"
      className={cn('border-t border-line bg-canvas font-medium [&>tr]:last:border-b-0', className)}
      {...props}
    />
  )
}

function TableRow({ className, ...props }: React.ComponentProps<'tr'>) {
  return (
    <tr
      data-slot="table-row"
      className={cn(
        'border-b border-line transition-colors duration-(--dur-fast) hover:bg-canvas data-[state=selected]:bg-brand-50',
        className,
      )}
      {...props}
    />
  )
}

function TableHead({ className, scope = 'col', ...props }: React.ComponentProps<'th'>) {
  return (
    <th
      data-slot="table-head"
      scope={scope}
      className={cn('h-11 min-w-0 px-3 text-left align-middle text-xs font-medium text-ink-muted', className)}
      {...props}
    />
  )
}

function TableCell({ className, ...props }: React.ComponentProps<'td'>) {
  return <td data-slot="table-cell" className={cn('min-w-0 px-3 py-3 align-middle', className)} {...props} />
}

/** Подпись таблицы: видна скринридеру (E §7); показать визуально — передать className. */
function TableCaption({ className = 'sr-only', ...props }: React.ComponentProps<'caption'>) {
  return <caption data-slot="table-caption" className={cn('text-sm text-ink-muted', className)} {...props} />
}

export { Table, TableBody, TableCaption, TableCell, TableFooter, TableHead, TableHeader, TableRow }
