import { cva, type VariantProps } from 'class-variance-authority'
import { CircleAlert, CircleCheck, Info, TriangleAlert } from 'lucide-react'
import type * as React from 'react'
import { cn } from '@/lib/utils'

/**
 * Плашка четырёх тонов с обязательной иконкой (E §3.2): статус передаётся иконкой и текстом, цвет лишь дублирует.
 * `destructive` получает role="alert" (ошибка мутации, E §7); остальные тона — обычный блок, если не задан `live`.
 */
const alertVariants = cva(
  'grid w-full min-w-0 grid-cols-[auto_minmax(0,1fr)] items-start gap-x-3 gap-y-1 rounded-lg px-4 py-3 text-sm leading-5',
  {
    variants: {
      variant: {
        info: 'bg-brand-50 text-ink [&>svg]:text-brand-700 **:data-[slot=alert-title]:text-brand-700',
        success: 'bg-success-bg text-ink [&>svg]:text-success **:data-[slot=alert-title]:text-success',
        warning: 'bg-warning-bg text-ink [&>svg]:text-warning **:data-[slot=alert-title]:text-warning',
        destructive: 'bg-danger-bg text-ink [&>svg]:text-danger **:data-[slot=alert-title]:text-danger',
      },
    },
    defaultVariants: {
      variant: 'info',
    },
  },
)

const ALERT_ICONS = {
  info: Info,
  success: CircleCheck,
  warning: TriangleAlert,
  destructive: CircleAlert,
} as const

type AlertProps = React.ComponentProps<'div'> &
  VariantProps<typeof alertVariants> & {
    /** Своя иконка вместо иконки тона; убрать иконку нельзя. */
    icon?: React.ReactNode
    /** Объявлять появление скринридеру (aria-live="polite") — для итогов фоновых действий. */
    live?: boolean
  }

function Alert({ className, variant = 'info', icon, live = false, children, ...props }: AlertProps) {
  const tone = variant ?? 'info'
  const Icon = ALERT_ICONS[tone]
  const role = tone === 'destructive' ? 'alert' : live ? 'status' : undefined
  return (
    <div
      data-slot="alert"
      data-variant={tone}
      role={role}
      className={cn(alertVariants({ variant }), className)}
      {...props}
    >
      {icon ?? <Icon className="size-5" aria-hidden="true" />}
      <div className="col-start-2 flex min-w-0 flex-col items-start gap-1">{children}</div>
    </div>
  )
}

function AlertTitle({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="alert-title"
      className={cn('max-w-full min-w-0 font-medium [overflow-wrap:anywhere]', className)}
      {...props}
    />
  )
}

/**
 * Текст плашки. Обычный блок, а не flex или grid: текст без обёртки — анонимный элемент, которому нельзя задать
 * min-width, и слово без пробелов распирало бы плашку. Абзацы и кнопки внутри разделяются отступом.
 */
function AlertDescription({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="alert-description"
      className={cn('w-full min-w-0 text-ink [overflow-wrap:anywhere] [&>*+*]:mt-2', className)}
      {...props}
    />
  )
}

export { Alert, AlertDescription, type AlertProps, AlertTitle }
