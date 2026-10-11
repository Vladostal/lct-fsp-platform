import { useQuery } from '@tanstack/react-query'
import { Download, FileText } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import type { Catalog } from '@/client'
import { ErrorState, IconTile, PageHeader, PageSkeleton } from '@/components/app'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { API_PREFIX } from '@/lib/config'
import { candidateProfileQuery, conditionsQuery } from '../api'
import { PROFILE } from '../content'
import { ProfileForm } from './profile-form'

type ScreenProps = { userId: string; catalog: Catalog | null; category?: string | null }

function useProfileData() {
  const profile = useQuery({ ...candidateProfileQuery, staleTime: 0, refetchOnMount: 'always' })
  const conditions = useQuery({ ...conditionsQuery(), staleTime: 0, refetchOnMount: 'always' })
  return { profile, conditions }
}

/** C1. Шаг 1 мастера: профиль, резюме и условия. */
export function ProfileStep({ userId, catalog, category }: ScreenProps) {
  const { profile, conditions } = useProfileData()
  if (profile.isPending || conditions.isPending) return <PageSkeleton variant="form" />
  if (profile.isError || conditions.isError) {
    return (
      <ErrorState
        error={profile.error ?? conditions.error}
        onRetry={() => {
          void profile.refetch()
          void conditions.refetch()
        }}
      />
    )
  }
  return (
    <div className="flex min-w-0 flex-col gap-6">
      <PageHeader title={PROFILE.wizard.title} description={PROFILE.wizard.description} />
      <ProfileForm
        mode="wizard"
        profile={profile.data}
        conditions={conditions.data}
        catalog={catalog}
        userId={userId}
        category={category}
      />
    </div>
  )
}

/** C11. Профиль и резюме в кабинете. */
export function ProfileCabinet({ userId, catalog, category }: ScreenProps) {
  const { profile, conditions } = useProfileData()
  const [pdfError, setPdfError] = useState<string | null>(null)
  const [pdfBusy, setPdfBusy] = useState(false)

  // Проверка перед открытием: 409 `profile_incomplete` показывается текстом, а не пустой вкладкой.
  const openPdf = async () => {
    setPdfError(null)
    setPdfBusy(true)
    try {
      const response = await fetch(`${API_PREFIX}/candidate/profile/pdf`, { credentials: 'same-origin' })
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { code?: string } | null
        setPdfError(
          body?.code === 'profile_incomplete'
            ? PROFILE.cabinet.pdfIncomplete
            : 'Не удалось получить PDF. Попробуйте ещё раз',
        )
        return
      }
      const url = URL.createObjectURL(await response.blob())
      window.open(url, '_blank', 'noopener')
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
    } catch {
      toast.error('Не удалось получить PDF. Попробуйте ещё раз')
    } finally {
      setPdfBusy(false)
    }
  }

  if (profile.isPending || conditions.isPending) return <PageSkeleton variant="form" />
  if (profile.isError || conditions.isError) {
    return (
      <ErrorState
        error={profile.error ?? conditions.error}
        onRetry={() => {
          void profile.refetch()
          void conditions.refetch()
        }}
      />
    )
  }
  return (
    <div className="mx-auto flex w-full max-w-3xl min-w-0 flex-col gap-6">
      <PageHeader title={PROFILE.cabinet.title} />
      <div className="accent-card surface-card flex min-w-0 animate-rise-in flex-wrap items-center gap-x-4 gap-y-3">
        <IconTile icon={FileText} tone="solid" size="xl" />
        <div className="flex min-w-0 flex-1 basis-40 flex-col">
          <h2 className="type-h2 min-w-0">{PROFILE.cabinet.pdfCard}</h2>
          <p className="type-sm min-w-0 text-ink-muted">{PROFILE.cabinet.pdfText}</p>
        </div>
        <Button variant="secondary" loading={pdfBusy} onClick={openPdf}>
          <Download aria-hidden="true" />
          {PROFILE.cabinet.pdfDownload}
        </Button>
        {pdfError ? (
          <Alert variant="warning" className="basis-full">
            <AlertDescription>{pdfError}</AlertDescription>
          </Alert>
        ) : null}
      </div>
      <ProfileForm
        mode="cabinet"
        profile={profile.data}
        conditions={conditions.data}
        catalog={catalog}
        userId={userId}
        category={category}
      />
    </div>
  )
}
