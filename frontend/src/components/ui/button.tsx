import { cva, type VariantProps } from 'class-variance-authority'
import { Loader2 } from 'lucide-react'
import { Slot } from 'radix-ui'
import type * as React from 'react'
import { cn } from '@/lib/utils'

/**
 * Кнопка — пилюля (E §3.1). Варианты:
 *  - primary: одна на экран (в main не больше одной кнопки [data-variant="primary"], Арх. 11.7 п. 1);
 *  - secondary (по умолчанию): контур brand-600;
 *  - ghost: без контура, фон появляется на hover;
 *  - destructive: контур и текст danger — только в подтверждениях отзыва, отвязки, сброса. Залитой красной нет;
 *  - link: ссылка в виде кнопки.
 * Размеры: md 44 px, sm 36 px (область нажатия расширена до 44 px), lg 52 px — только hero и мастер.
 */
const buttonVariants = cva(
  "relative inline-flex shrink-0 select-none items-center justify-center rounded-full border border-transparent font-medium whitespace-nowrap transition-colors duration-(--dur-fast) disabled:pointer-events-none disabled:opacity-50 aria-disabled:pointer-events-none aria-disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-5",
  {
    variants: {
      variant: {
        primary: 'bg-brand-600 text-white hover:bg-brand-700 active:bg-brand-900',
        secondary: 'border-brand-600 bg-surface text-brand-700 hover:bg-brand-50 active:bg-brand-100',
        ghost: 'text-brand-700 hover:bg-brand-50 active:bg-brand-100',
        destructive: 'border-danger bg-surface text-danger hover:bg-danger-bg active:bg-danger-bg',
        link: 'tap-target rounded-xs text-brand-700 underline decoration-1 underline-offset-3 hover:text-brand-600 hover:decoration-2 active:text-brand-900',
      },
      size: {
        md: 'h-11 gap-2 px-5 text-base',
        sm: "tap-target h-9 gap-1.5 px-4 text-sm [&_svg:not([class*='size-'])]:size-4",
        lg: 'h-13 gap-2 px-7 text-base',
        icon: 'size-11',
        'icon-sm': "tap-target size-9 [&_svg:not([class*='size-'])]:size-4",
      },
    },
    compoundVariants: [{ variant: 'link', className: 'h-auto min-h-6 px-0' }],
    defaultVariants: {
      variant: 'secondary',
      size: 'md',
    },
  },
)

type ButtonProps = React.ComponentProps<'button'> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
    /**
     * Мутация выполняется: aria-busy, спиннер поверх подписи (ширина кнопки не меняется), повторное нажатие
     * невозможно. Подпись скрывается прозрачностью, а не visibility: она остаётся именем кнопки для скринридера.
     */
    loading?: boolean
  }

function Button({
  className,
  variant = 'secondary',
  size = 'md',
  asChild = false,
  loading = false,
  disabled,
  children,
  ...props
}: ButtonProps) {
  const Comp = asChild ? Slot.Root : 'button'

  return (
    <Comp
      data-slot="button"
      data-variant={variant}
      data-size={size}
      aria-busy={loading || undefined}
      disabled={asChild ? undefined : disabled || loading}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    >
      {asChild ? (
        children
      ) : (
        <>
          <span className={cn('inline-flex min-w-0 items-center justify-center gap-[inherit]', loading && 'opacity-0')}>
            {children}
          </span>
          {loading ? (
            <span className="absolute inset-0 grid place-items-center" aria-hidden="true">
              <Loader2 className="animate-spin" />
            </span>
          ) : null}
        </>
      )}
    </Comp>
  )
}

export { Button, type ButtonProps, buttonVariants }
