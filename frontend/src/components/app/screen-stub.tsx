import { Construction } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { COMMON } from '@/content/common'
import { PageHeader } from './page-header'

export type ScreenStubProps = {
  /** Идентификатор экрана по карте (Арх. 11.2): «C7», «E4». */
  screen: string
  /** Название экрана — заголовок страницы. */
  title: string
  /** Что появится на экране — одно предложение. */
  description?: string
}

/**
 * Заглушка листового маршрута: «экран в работе». Дерево маршрутов стабильно с первого дня, а файл маршрута
 * целиком заменяет пакет экрана (план, раздел 3).
 */
export function ScreenStub({ screen, title, description }: ScreenStubProps) {
  return (
    <div className="flex min-w-0 flex-col gap-6" data-slot="screen-stub" data-screen={screen}>
      <PageHeader title={title} eyebrow={`${screen} · ${COMMON.stub.eyebrow}`} description={description} />
      <Card className="items-center text-center">
        <span
          className="grid size-16 shrink-0 place-items-center rounded-full bg-brand-50 text-brand-700"
          aria-hidden="true"
        >
          <Construction className="size-10" strokeWidth={1.5} />
        </span>
        <p className="type-body max-w-[52ch] text-ink-muted">{COMMON.stub.text}</p>
      </Card>
    </div>
  )
}
