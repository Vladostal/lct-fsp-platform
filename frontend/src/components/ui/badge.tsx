import { cva, type VariantProps } from 'class-variance-authority'
import { Slot } from 'radix-ui'
import type * as React from 'react'
import { cn } from '@/lib/utils'

/** Бейдж — один размер h-6 (12 / 16), rounded-sm; подпись не переносится (E §3.1, §4.3). */
const badgeVariants = cva(
  'inline-flex w-fit max-w-full shrink-0 items-center justify-center gap-1.5 rounded-sm border border-transparent font-medium whitespace-nowrap [&>svg]:pointer-events-none [&>svg]:shrink-0',
  {
    variants: {
      variant: {
        neutral: 'bg-fill text-ink',
        info: 'bg-brand-50 text-brand-700',
        success: 'bg-success-bg text-success',
        warning: 'bg-warning-bg text-warning',
        danger: 'bg-danger-bg text-danger',
        /* Синонимы прежних видов: чужие экраны компилируются, вид один. */
        outline: 'bg-fill text-ink',
        solid: 'bg-brand-50 text-brand-700',
      },
      size: {
        md: 'h-6 px-2 text-xs leading-4 [&>svg]:size-3.5',
        sm: 'h-6 px-2 text-xs leading-4 [&>svg]:size-3.5',
      },
    },
    defaultVariants: {
      variant: 'neutral',
      size: 'md',
    },
  },
)

type BadgeProps = React.ComponentProps<'span'> & VariantProps<typeof badgeVariants> & { asChild?: boolean }

function Badge({ className, variant = 'neutral', size = 'md', asChild = false, ...props }: BadgeProps) {
  const Comp = asChild ? Slot.Root : 'span'
  return (
    <Comp
      data-slot="badge"
      data-variant={variant}
      className={cn(badgeVariants({ variant, size }), className)}
      {...props}
    />
  )
}

export { Badge, type BadgeProps, badgeVariants }
