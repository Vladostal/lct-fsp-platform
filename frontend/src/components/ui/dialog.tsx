import { XIcon } from 'lucide-react'
import { Dialog as DialogPrimitive } from 'radix-ui'
import type * as React from 'react'
import { ActionRow } from '@/components/ui/action-row'
import { cn } from '@/lib/utils'

/*
 * Диалог (E §4.4, §4.5): ширина до 520 px, высота не больше 100dvh − 32 px, прокручивается тело (DialogBody),
 * заголовок и кнопки видны всегда. Ниже 768 px диалог прижат к низу, на всю ширину, верхний радиус 24.
 * Слой 50. Появление — проявление и масштаб 0,98 → 1 за 160 мс.
 */

/** Общая геометрия слоя для Dialog и AlertDialog. */
const dialogContentClassName =
  'fixed inset-x-0 bottom-0 z-50 mx-auto flex max-h-[calc(100dvh-32px)] w-full max-w-[520px] flex-col rounded-t-xl bg-surface text-ink shadow-pop duration-(--dur-base) data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:animate-in data-[state=open]:fade-in-0 md:top-1/2 md:bottom-auto md:-translate-y-1/2 md:rounded-xl md:data-[state=open]:zoom-in-[0.98]'

const dialogOverlayClassName =
  'fixed inset-0 z-50 bg-black/50 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:animate-in data-[state=open]:fade-in-0'

function Dialog(props: React.ComponentProps<typeof DialogPrimitive.Root>) {
  return <DialogPrimitive.Root data-slot="dialog" {...props} />
}

function DialogTrigger(props: React.ComponentProps<typeof DialogPrimitive.Trigger>) {
  return <DialogPrimitive.Trigger data-slot="dialog-trigger" {...props} />
}

function DialogPortal(props: React.ComponentProps<typeof DialogPrimitive.Portal>) {
  return <DialogPrimitive.Portal data-slot="dialog-portal" {...props} />
}

function DialogClose(props: React.ComponentProps<typeof DialogPrimitive.Close>) {
  return <DialogPrimitive.Close data-slot="dialog-close" {...props} />
}

function DialogOverlay({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Overlay>) {
  return (
    <DialogPrimitive.Overlay data-slot="dialog-overlay" className={cn(dialogOverlayClassName, className)} {...props} />
  )
}

function DialogContent({
  className,
  children,
  showCloseButton = true,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Content> & { showCloseButton?: boolean }) {
  return (
    <DialogPortal>
      <DialogOverlay />
      <DialogPrimitive.Content data-slot="dialog-content" className={cn(dialogContentClassName, className)} {...props}>
        {children}
        {showCloseButton ? (
          <DialogPrimitive.Close
            data-slot="dialog-close"
            aria-label="Закрыть"
            className="absolute top-3 right-3 grid size-11 place-items-center rounded-full text-ink-muted transition-colors duration-(--dur-fast) hover:bg-fill hover:text-ink"
          >
            <XIcon className="size-5" aria-hidden="true" />
          </DialogPrimitive.Close>
        ) : null}
      </DialogPrimitive.Content>
    </DialogPortal>
  )
}

function DialogHeader({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="dialog-header"
      className={cn('flex shrink-0 flex-col gap-2 px-4 pt-6 pr-14 pb-4 md:px-6 md:pr-16', className)}
      {...props}
    />
  )
}

/** Прокручиваемое тело диалога. */
function DialogBody({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="dialog-body"
      className={cn('flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-4 pb-2 md:px-6', className)}
      {...props}
    />
  )
}

/**
 * Кнопки диалога: передаются в порядке «вторичные, затем основная»; ниже 480 px — столбцом на всю ширину,
 * основная первой (порядок меняется в DOM, см. ActionRow).
 */
function DialogFooter({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <ActionRow
      data-slot="dialog-footer"
      className={cn('shrink-0 px-4 pt-4 pb-[calc(16px+env(safe-area-inset-bottom))] md:px-6 md:pb-6', className)}
      {...props}
    />
  )
}

function DialogTitle({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Title>) {
  return <DialogPrimitive.Title data-slot="dialog-title" className={cn('type-h2', className)} {...props} />
}

function DialogDescription({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Description>) {
  return (
    <DialogPrimitive.Description
      data-slot="dialog-description"
      className={cn('type-sm text-ink-muted', className)}
      {...props}
    />
  )
}

export {
  Dialog,
  DialogBody,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogOverlay,
  DialogPortal,
  DialogTitle,
  DialogTrigger,
  dialogContentClassName,
  dialogOverlayClassName,
}
