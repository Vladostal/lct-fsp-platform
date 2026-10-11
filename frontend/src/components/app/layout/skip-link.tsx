import { COMMON } from '@/content/common'

/** Первая ссылка страницы — «К содержимому», видна при фокусе (E §7). */
export function SkipLink() {
  return (
    <a
      href="#main"
      className="sr-only focus-visible:not-sr-only focus-visible:fixed focus-visible:top-2 focus-visible:left-2 focus-visible:z-[70] focus-visible:rounded-full focus-visible:bg-brand-600 focus-visible:px-5 focus-visible:py-2.5 focus-visible:text-base focus-visible:font-medium focus-visible:text-on-brand"
    >
      {COMMON.skipToContent}
    </a>
  )
}
