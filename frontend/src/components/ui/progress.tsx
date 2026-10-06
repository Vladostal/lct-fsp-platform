import { Progress as ProgressPrimitive } from 'radix-ui'
import type * as React from 'react'
import { cn } from '@/lib/utils'

/** Полоса прогресса: трек fill, значение brand-600; заполнение — scaleX за 240 мс (E §5). */
function Progress({ className, value, ...props }: React.ComponentProps<typeof ProgressPrimitive.Root>) {
  return (
    <ProgressPrimitive.Root
      data-slot="progress"
      value={value}
      className={cn('relative h-2 w-full overflow-hidden rounded-full bg-fill', className)}
      {...props}
    >
      <ProgressPrimitive.Indicator
        data-slot="progress-indicator"
        className="size-full origin-left rounded-full bg-brand-600 transition-transform duration-(--dur-slow) ease-(--ease-enter)"
        style={{ transform: `scaleX(${Math.min(100, Math.max(0, value ?? 0)) / 100})` }}
      />
    </ProgressPrimitive.Root>
  )
}

export { Progress }
