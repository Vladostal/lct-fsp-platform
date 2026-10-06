import { cva, type VariantProps } from 'class-variance-authority'
import { Toggle as TogglePrimitive } from 'radix-ui'
import type * as React from 'react'
import { cn } from '@/lib/utils'

/** Чип-переключатель: пилюля; выбранное — граница brand-600 и фон brand-50 (плюс иконка в содержимом, E §7). */
const toggleVariants = cva(
  "inline-flex min-w-0 items-center justify-center gap-2 rounded-full border font-medium whitespace-nowrap transition-colors duration-(--dur-fast) disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default:
          'border-transparent bg-transparent text-ink-muted hover:bg-fill hover:text-ink data-[state=on]:bg-brand-50 data-[state=on]:text-brand-700',
        outline:
          'border-line-strong bg-surface text-ink hover:border-ink-muted hover:bg-fill data-[state=on]:border-brand-600 data-[state=on]:bg-brand-50 data-[state=on]:text-brand-700',
      },
      size: {
        default: 'h-11 px-4 text-base',
        sm: 'tap-target h-9 px-3 text-sm',
        lg: 'h-13 px-5 text-base',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  },
)

function Toggle({
  className,
  variant,
  size,
  ...props
}: React.ComponentProps<typeof TogglePrimitive.Root> & VariantProps<typeof toggleVariants>) {
  return (
    <TogglePrimitive.Root data-slot="toggle" className={cn(toggleVariants({ variant, size, className }))} {...props} />
  )
}

export { Toggle, toggleVariants }
