import { CircleAlert, CircleCheck, Info, Loader2, TriangleAlert } from 'lucide-react'
import { Toaster as Sonner, type ToasterProps } from 'sonner'
import { useIsMobile } from '@/lib/hooks/use-media-query'
import { useTheme } from '@/lib/theme'

/**
 * Toast (E §4.4): ≥ 768 px — справа снизу со сдвигом над панелью действий (--action-bar-space выставляет
 * StickyActionBar); < 768 px — сверху по центру. Одновременно не больше трёх. Фокус toast не забирает.
 */
function Toaster(props: ToasterProps) {
  const mobile = useIsMobile()
  const { theme } = useTheme()
  return (
    <Sonner
      theme={theme}
      position={mobile ? 'top-center' : 'bottom-right'}
      visibleToasts={3}
      duration={5000}
      offset={{ bottom: 'calc(var(--action-bar-space, 0px) + 16px)', right: 24 }}
      mobileOffset={{ top: 72 }}
      containerAriaLabel="Уведомления"
      className="toaster group"
      icons={{
        success: <CircleCheck className="size-5 text-success" />,
        info: <Info className="size-5 text-brand-700" />,
        warning: <TriangleAlert className="size-5 text-warning" />,
        error: <CircleAlert className="size-5 text-danger" />,
        loading: <Loader2 className="size-5 animate-spin text-ink-muted" />,
      }}
      toastOptions={{
        classNames: {
          toast: 'font-sans',
          title: 'text-sm font-medium',
          description: 'text-sm',
        },
      }}
      style={
        {
          '--normal-bg': 'var(--color-surface)',
          '--normal-text': 'var(--color-ink)',
          '--normal-border': 'var(--color-line)',
          '--border-radius': 'var(--radius-lg)',
          '--width': '380px',
          zIndex: 60,
        } as React.CSSProperties
      }
      {...props}
    />
  )
}

export { Toaster }
