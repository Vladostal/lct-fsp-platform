/** Проверяемые размеры окна (E §4.1) и наименьшая поддерживаемая ширина (E §9.1, G15). */
export const VIEWPORTS = [
  { name: '1280', width: 1280, height: 800 },
  { name: '768', width: 768, height: 1024 },
  { name: '375', width: 375, height: 812 },
] as const

export const MIN_VIEWPORT = { name: '320', width: 320, height: 640 } as const

export type Viewport = { name: string; width: number; height: number }
