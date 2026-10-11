import { XIcon } from 'lucide-react'
import { Dialog as SheetPrimitive } from 'radix-ui'
import type * as React from 'react'
import { ActionRow } from '@/components/ui/action-row'
import { dialogOverlayClassName } from '@/components/ui/dialog'
import { cn } from '@/lib/utils'

/*
 * Боковая панель (E §4.4): собственная прокрутка содержимого (SheetBody), шапка и панель действий липкие внутри,
 * прокрутка страницы под ней заблокирована. Правая панель — карточка кандидата шириной min(760px, 100vw);
 * левая — меню навигации. Вход — сдвиг на 16 px и проявление за 240 мс, выход — 120 мс.
 */

function Sheet(props: React.ComponentProps<typeof SheetPrimitive.Root>) {
  return <SheetPrimitive.Root data-slot="sheet" {...props} />
}

function SheetTrigger(props: React.ComponentProps<typeof SheetPrimitive.Trigger>) {
  return <SheetPrimitive.Trigger data-slot="sheet-trigger" {...props} />
}

function SheetClose(props: React.ComponentProps<typeof SheetPrimitive.Close>) {
  return <SheetPrimitive.Close data-slot="sheet-close" {...props} />
}

function SheetPortal(props: React.ComponentProps<typeof SheetPrimitive.Portal>) {
  return <SheetPrimitive.Portal data-slot="sheet-portal" {...props} />
}

function SheetOverlay({ className, ...props }: React.ComponentProps<typeof SheetPrimitive.Overlay>) {
  return (
    <SheetPrimitive.Overlay data-slot="sheet-overlay" className={cn(dialogOverlayClassName, className)} {...props} />
  )
}

function SheetContent({
  className,
  children,
  side = 'right',
  showCloseButton = true,
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Content> & {
  side?: 'right' | 'left'
  showCloseButton?: boolean
}) {
  return (
    <SheetPortal>
      <SheetOverlay />
      <SheetPrimitive.Content
        data-slot="sheet-content"
        data-side={side}
        className={cn(
          'fixed inset-y-0 z-50 flex h-dvh flex-col bg-surface text-ink shadow-pop duration-(--dur-slow) ease-(--ease-enter) data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:animate-in data-[state=open]:fade-in-0',
          side === 'right' &&
            'right-0 w-[min(760px,100vw)] data-[state=closed]:slide-out-to-right-4 data-[state=open]:slide-in-from-right-4',
          side === 'left' &&
            'left-0 w-[min(320px,100vw)] data-[state=closed]:slide-out-to-left-4 data-[state=open]:slide-in-from-left-4',
          className,
        )}
        {...props}
      >
        {children}
        {showCloseButton ? (
          <SheetPrimitive.Close
            data-slot="sheet-close"
            aria-label="Закрыть"
            className="absolute top-3 right-3 grid size-11 place-items-center rounded-full text-ink-muted transition-colors duration-(--dur-fast) hover:bg-fill hover:text-ink"
          >
            <XIcon className="size-5" aria-hidden="true" />
          </SheetPrimitive.Close>
        ) : null}
      </SheetPrimitive.Content>
    </SheetPortal>
  )
}

function SheetHeader({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="sheet-header"
      className={cn('flex shrink-0 flex-col gap-1.5 border-b border-line px-4 pt-5 pr-16 pb-4 md:px-6', className)}
      {...props}
    />
  )
}

/** Прокручиваемое содержимое панели. */
function SheetBody({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="sheet-body"
      className={cn('flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto px-4 py-4 md:px-6 md:py-6', className)}
      {...props}
    />
  )
}

/** Панель действий внутри Sheet: всегда видна, учитывает безопасную зону снизу; порядок кнопок — как в ActionRow. */
function SheetFooter({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <ActionRow
      data-slot="sheet-footer"
      className={cn(
        'relative z-10 shrink-0 border-t border-line bg-surface px-4 pt-3 pb-[calc(12px+env(safe-area-inset-bottom))] shadow-bar md:px-6 [&_[data-slot=button]]:h-11',
        className,
      )}
      {...props}
    />
  )
}

function SheetTitle({ className, ...props }: React.ComponentProps<typeof SheetPrimitive.Title>) {
  return <SheetPrimitive.Title data-slot="sheet-title" className={cn('type-h2 min-w-0', className)} {...props} />
}

function SheetDescription({ className, ...props }: React.ComponentProps<typeof SheetPrimitive.Description>) {
  return (
    <SheetPrimitive.Description
      data-slot="sheet-description"
      className={cn('type-sm min-w-0 text-ink-muted', className)}
      {...props}
    />
  )
}

export {
  Sheet,
  SheetBody,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
}
