import { useEffect } from 'react'
import { pageTitle } from '@/lib/config'

/** Заголовок документа «{экран} · {APP_NAME}» меняется вместе с маршрутом (E §7). */
export function usePageTitle(screen: string | null | undefined): void {
  useEffect(() => {
    document.title = pageTitle(screen)
  }, [screen])
}
