import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'
import type { Catalog } from '@/client'
import { ErrorState, PageHeader, PageSkeleton } from '@/components/app'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle } from '@/components/ui/card'
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
    <div className="mx-auto flex w-full max-w-[880px] min-w-0 flex-col gap-6">
      <PageHeader title={PROFILE.cabinet.title} description={PROFILE.cabinet.description} />
      <Card>
        <CardHeader>
          <CardTitle>{PROFILE.cabinet.pdfCard}</CardTitle>
        </CardHeader>
        <p className="type-body mb-3 text-ink-muted">{PROFILE.cabinet.pdfText}</p>
        <Button variant="secondary" className="self-start" loading={pdfBusy} onClick={openPdf}>
          {PROFILE.cabinet.pdfDownload}
        </Button>
        {pdfError ? (
          <Alert variant="warning" className="mt-3">
            <AlertDescription>{pdfError}</AlertDescription>
          </Alert>
        ) : null}
      </Card>
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
