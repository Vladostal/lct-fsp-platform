import { createFileRoute } from '@tanstack/react-router'
import { z } from 'zod'
import { PageHeader } from '@/components/app'
import { FSP, FspBlock } from '@/features/fsp'
import { SettingsTabs } from '@/features/profile'

/** C13. Связь с ФСП ID: привязка с отдельным согласием, достижения, календарь. */
export const Route = createFileRoute('/candidate/_cabinet/settings/fsp')({
  validateSearch: z.object({
    result: z.enum(['linked', 'cancelled', 'already_linked', 'minor', 'error']).optional().catch(undefined),
    reason: z.string().max(40).optional().catch(undefined),
  }),
  component: Screen,
})

function Screen() {
  const { result, reason } = Route.useSearch()
  const { catalog } = Route.useRouteContext()
  return (
    <div className="mx-auto flex w-full max-w-[880px] min-w-0 flex-col gap-6">
      <SettingsTabs />
      <PageHeader title={FSP.title} description={FSP.description} />
      <FspBlock result={result} reason={reason} pulseEnabled={catalog?.features.pulse ?? false} />
    </div>
  )
}
