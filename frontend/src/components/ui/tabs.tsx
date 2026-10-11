import { Tabs as TabsPrimitive } from 'radix-ui'
import type * as React from 'react'
import { cn } from '@/lib/utils'

/** Вкладки с одной линией; индикатор активной вкладки плавно прорастает слева (transform). Список прокручивается внутри себя на узких экранах. */
function Tabs({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Root>) {
  return <TabsPrimitive.Root data-slot="tabs" className={cn('flex min-w-0 flex-col gap-4', className)} {...props} />
}

function TabsList({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.List>) {
  return (
    <TabsPrimitive.List
      data-slot="tabs-list"
      className={cn(
        'flex w-full min-w-0 items-stretch gap-5 overflow-x-auto border-b border-line [scrollbar-width:none]',
        className,
      )}
      {...props}
    />
  )
}

function TabsTrigger({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      data-slot="tabs-trigger"
      className={cn(
        "relative inline-flex h-11 shrink-0 items-center justify-center gap-2 text-sm font-medium whitespace-nowrap text-ink-muted transition-colors duration-(--dur-fast) hover:text-ink disabled:pointer-events-none disabled:opacity-50 data-[state=active]:text-ink [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        'after:absolute after:inset-x-0 after:bottom-0 after:h-0.5 after:rounded-full after:bg-brand-600 after:origin-left after:scale-x-0 after:transition-transform after:duration-(--dur-slow) after:ease-(--ease-enter) data-[state=active]:after:scale-x-100',
        '-outline-offset-2',
        className,
      )}
      {...props}
    />
  )
}

function TabsContent({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Content>) {
  return <TabsPrimitive.Content data-slot="tabs-content" className={cn('min-w-0 flex-1', className)} {...props} />
}

export { Tabs, TabsContent, TabsList, TabsTrigger }
