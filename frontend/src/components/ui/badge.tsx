import { cva, type VariantProps } from 'class-variance-authority'
import { Slot } from 'radix-ui'
import type * as React from 'react'
import { cn } from '@/lib/utils'

/** Бейдж — пилюля высотой 28 (текст 14 / 20) или 24 (12 / 16); подпись не переносится (E §3.1, §4.3). */
const badgeVariants = cva(
  'inline-flex w-fit max-w-full shrink-0 items-center justify-center gap-1.5 rounded-full border border-transparent font-medium whitespace-nowrap [&>svg]:pointer-events-none [&>svg]:shrink-0',
  {
    variants: {
      variant: {
        neutral: 'bg-fill text-ink',
        info: 'bg-brand-50 text-brand-700',
        success: 'bg-success-bg text-success',
        warning: 'bg-warning-bg text-warning',
        danger: 'bg-danger-bg text-danger',
        outline: 'border-line-strong bg-surface text-ink',
        solid: 'bg-brand-600 text-white',
      },
      size: {
        md: 'h-7 px-3 text-sm leading-5 [&>svg]:size-4',
        sm: 'h-6 px-2.5 text-xs leading-4 [&>svg]:size-3.5',
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
