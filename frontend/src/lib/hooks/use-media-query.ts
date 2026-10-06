import { useSyncExternalStore } from 'react'

/** Соответствует ли окно медиа-запросу; обновляется при изменении размера. */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const mq = window.matchMedia(query)
      mq.addEventListener('change', onChange)
      return () => mq.removeEventListener('change', onChange)
    },
    () => window.matchMedia(query).matches,
    () => false,
  )
}

/** Ниже 480 px ряд кнопок встаёт столбцом на всю ширину (E §4.2). */
export function useNarrowActions(): boolean {
  return useMediaQuery('(max-width: 479px)')
}

/** Ниже 768 px — мобильная раскладка. */
export function useIsMobile(): boolean {
  return useMediaQuery('(max-width: 767px)')
}
