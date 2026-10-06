import { createFileRoute, notFound } from '@tanstack/react-router'
import { Showcase } from '@/components/app/showcase/showcase'
import { isDemoEnabled } from '@/lib/features'

/**
 * P7. Витрина компонентов `/demo/components` (при `features.demo`): статическая страница без запросов —
 * каждый общий компонент в обычном виде и с проверочными строками (E §4.6). По ней идёт автопроверка вёрстки.
 */
export const Route = createFileRoute('/_public/demo/components')({
  beforeLoad: ({ context }) => {
    if (!isDemoEnabled(context.catalog)) throw notFound()
  },
  component: Showcase,
})
