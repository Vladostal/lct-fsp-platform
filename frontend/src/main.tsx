import './styles/theme.css'
import { QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from '@tanstack/react-router'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { toast } from 'sonner'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { COMMON } from '@/content/common'
import { setupApiClient } from '@/lib/api'
import { queryClient } from '@/lib/query'
import { installSessionGuard } from '@/lib/session'
import { router } from './router'

setupApiClient()

// 401 на запрос кабинета: кэш `me` уже очищен, остаётся увести пользователя и объяснить, что произошло (Арх. 11.3).
installSessionGuard(({ href, reason }) => {
  toast.info(reason === 'demo_restarted' ? COMMON.demoRestarted : COMMON.sessionExpired)
  void router.navigate({ href, replace: true, ignoreBlocker: true })
})

const container = document.getElementById('root')
if (!container) throw new Error('Не найден корневой элемент #root')

createRoot(container).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delayDuration={300}>
        <RouterProvider router={router} />
        <Toaster />
      </TooltipProvider>
    </QueryClientProvider>
  </StrictMode>,
)
