import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ChevronDown, Lock } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import type { PrivacySettings as PrivacyValues } from '@/client'
import { fspGetLinkOptions } from '@/client/@tanstack/react-query.gen'
import { ErrorState, PageHeader, PageSkeleton } from '@/components/app'
import { Alert, AlertDescription } from '@/components/ui/alert'
import {
  AlertDialog,
  AlertDialogBody,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Switch } from '@/components/ui/switch'
import { errorMessage } from '@/lib/api'
import { formatDate } from '@/lib/format'
import { useMediaQuery } from '@/lib/hooks/use-media-query'
import {
  candidateProfileQuery,
  consentsQuery,
  privacyQuery,
  usePrivacyMutation,
  usePublicationConsent,
  useResumeInvitations,
  useVisibilityMutation,
} from '../api'
import { PRIVACY } from '../content'
import { AccessLog } from './access-log'
import { PrivacyPreview } from './privacy-preview'
import { SettingsTabs } from './settings-tabs'

type ToggleKey = keyof Omit<PrivacyValues, 'hidden_domains'>

function ToggleRow({
  id,
  label,
  note,
  checked,
  disabled,
  disabledNote,
  onChange,
}: {
  id: ToggleKey
  label: string
  note?: string
  checked: boolean
  disabled?: boolean
  disabledNote?: React.ReactNode
  onChange: (value: boolean) => void
}) {
  return (
    <li className="flex min-w-0 items-start justify-between gap-4 py-3">
      <div className="flex min-w-0 flex-col gap-0.5">
        <label htmlFor={`privacy-${id}`} className="type-body min-w-0 font-medium text-ink">
          {label}
        </label>
        {disabled && disabledNote ? (
          <span className="type-caption text-ink-muted">{disabledNote}</span>
        ) : note ? (
          <span className="type-caption text-ink-muted">{note}</span>
        ) : null}
      </div>
      <Switch id={`privacy-${id}`} checked={checked && !disabled} disabled={disabled} onCheckedChange={onChange} />
    </li>
  )
}

/** C12. Приватность и согласия: показ профиля, что видно до и после согласия, согласия, журнал, предпросмотр. */
export function PrivacySettings() {
  const T = PRIVACY
  const wide = useMediaQuery('(min-width: 1024px)')
  const [revokeOpen, setRevokeOpen] = useState(false)
  const privacy = useQuery(privacyQuery())
  const consents = useQuery(consentsQuery())
  const profile = useQuery(candidateProfileQuery)
  const fsp = useQuery({ ...fspGetLinkOptions(), retry: false })
  const mutate = usePrivacyMutation((error) => toast.error(errorMessage(error) || T.saveFailed))
  const visibility = useVisibilityMutation()
  const resume = useResumeInvitations()
  const publication = usePublicationConsent()

  if (privacy.isPending || consents.isPending || profile.isPending) return <PageSkeleton variant="form" />
  if (privacy.isError || consents.isError || profile.isError) {
    const failed = [privacy, consents, profile].find((q) => q.isError)
    return (
      <ErrorState
        error={failed?.error}
        onRetry={() => {
          void privacy.refetch()
          void consents.refetch()
          void profile.refetch()
        }}
      />
    )
  }

  const values = privacy.data
  const state = consents.data.visibility
  const person = profile.data
  const fspLinked = fsp.data?.status === 'linked'
  const set = (key: ToggleKey) => (value: boolean) => mutate.mutate({ [key]: value })
  const flag = (key: ToggleKey, fallback = true) => values[key] ?? fallback

  const toggleVisible = (next: boolean) =>
    visibility.mutate(next ? 'visible' : 'paused', { onError: (error) => toast.error(errorMessage(error)) })

  const stateText =
    state.state === 'visible'
      ? T.show.visible
      : state.state === 'unpublished'
        ? T.show.unpublished
        : state.state === 'not_ready'
          ? T.show.notReady
          : state.pause_reason === 'auto_silence' && state.auto_paused_until
            ? T.show.autoPaused(formatDate(state.auto_paused_until))
            : T.show.paused

  const publicationConsent = consents.data.publication
  const processing = consents.data.processing

  const settings = (
    <div className="flex min-w-0 flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>{T.show.title}</CardTitle>
        </CardHeader>
        <div className="flex min-w-0 items-start justify-between gap-4">
          <div className="flex min-w-0 flex-col gap-1">
            <label htmlFor="privacy-visible" className="type-body font-medium text-ink">
              {T.show.label}
            </label>
            <p className="type-sm text-ink-muted" data-testid="visibility-text">
              {stateText}
            </p>
          </div>
          <Switch
            id="privacy-visible"
            checked={state.state === 'visible'}
            disabled={state.state === 'not_ready' || visibility.isPending}
            onCheckedChange={toggleVisible}
          />
        </div>
        {state.pause_reason === 'auto_silence' && state.state === 'paused' ? (
          <Button
            variant="secondary"
            className="mt-3"
            loading={resume.isPending}
            onClick={() => resume.mutate(undefined, { onError: (e) => toast.error(errorMessage(e)) })}
          >
            {T.show.resume}
          </Button>
        ) : null}
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{T.before.title}</CardTitle>
        </CardHeader>
        <ul className="flex min-w-0 flex-col gap-1 border-b border-line pb-3">
          {T.before.always.map((line) => (
            <li key={line} className="type-sm flex min-w-0 items-center gap-2 text-ink">
              <Lock className="size-3.5 shrink-0 text-ink-muted" aria-hidden="true" />
              <span className="min-w-0">{line}</span>
              <span className="type-caption shrink-0 text-ink-muted">· {T.before.locked}</span>
            </li>
          ))}
        </ul>
        <ul className="flex min-w-0 flex-col divide-y divide-line">
          <ToggleRow
            id="show_city"
            label={T.toggles.show_city.label}
            checked={flag('show_city')}
            onChange={set('show_city')}
          />
          <ToggleRow
            id="show_experience"
            label={T.toggles.show_experience.label}
            checked={flag('show_experience')}
            onChange={set('show_experience')}
          />
          <ToggleRow
            id="show_declared_stack"
            label={T.toggles.show_declared_stack.label}
            note={T.toggles.show_declared_stack.note}
            checked={flag('show_declared_stack')}
            onChange={set('show_declared_stack')}
          />
          <ToggleRow
            id="show_about"
            label={T.toggles.show_about.label}
            note={T.toggles.show_about.note}
            checked={flag('show_about', false)}
            onChange={set('show_about')}
          />
          <ToggleRow
            id="show_fsp_summary"
            label={T.toggles.show_fsp_summary.label}
            note={T.toggles.show_fsp_summary.note}
            checked={flag('show_fsp_summary')}
            disabled={!fspLinked}
            disabledNote={
              <>
                {T.noFsp} ·{' '}
                <Link to="/candidate/settings/fsp" className="text-link">
                  {T.linkFsp}
                </Link>
              </>
            }
            onChange={set('show_fsp_summary')}
          />
        </ul>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{T.after.title}</CardTitle>
        </CardHeader>
        <p className="type-sm flex items-center gap-2 border-b border-line pb-3 text-ink">
          <Lock className="size-3.5 shrink-0 text-ink-muted" aria-hidden="true" />
          {T.after.always}
        </p>
        <ul className="flex min-w-0 flex-col divide-y divide-line">
          <ToggleRow
            id="reveal_phone"
            label={T.toggles.reveal_phone.label}
            checked={flag('reveal_phone', false)}
            disabled={!person.phone}
            disabledNote={
              <>
                {T.noPhone} ·{' '}
                <Link to="/candidate/profile" className="text-link">
                  {T.toProfile}
                </Link>
              </>
            }
            onChange={set('reveal_phone')}
          />
          <ToggleRow
            id="reveal_telegram"
            label={T.toggles.reveal_telegram.label}
            checked={flag('reveal_telegram', false)}
            disabled={!person.telegram}
            disabledNote={T.noTelegram}
            onChange={set('reveal_telegram')}
          />
          <ToggleRow
            id="reveal_link"
            label={T.toggles.reveal_link.label}
            checked={flag('reveal_link', false)}
            disabled={!person.link}
            disabledNote={T.noLink}
            onChange={set('reveal_link')}
          />
          <ToggleRow
            id="reveal_fsp_details"
            label={T.toggles.reveal_fsp_details.label}
            checked={flag('reveal_fsp_details', false)}
            disabled={!fspLinked}
            disabledNote={T.noFsp}
            onChange={set('reveal_fsp_details')}
          />
        </ul>
        <p className="type-caption mt-3 text-ink-muted">{T.after.note}</p>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{T.consents.title}</CardTitle>
        </CardHeader>
        <ul className="flex min-w-0 flex-col divide-y divide-line">
          <li className="flex min-w-0 flex-col gap-0.5 py-3 first:pt-0">
            <span className="type-body font-medium text-ink">{T.consents.processing}</span>
            <span className="type-sm text-ink-muted">
              {processing.granted && processing.granted_at
                ? T.consents.granted(
                    formatDate(processing.granted_at),
                    processing.version ?? processing.current_version,
                  )
                : T.consents.notGranted}
            </span>
          </li>
          <li className="flex min-w-0 flex-wrap items-center justify-between gap-3 py-3">
            <div className="flex min-w-0 flex-col gap-0.5">
              <span className="type-body font-medium text-ink">{T.consents.publication}</span>
              <span className="type-sm text-ink-muted" data-testid="publication-consent">
                {publicationConsent.granted && publicationConsent.granted_at
                  ? T.consents.granted(
                      formatDate(publicationConsent.granted_at),
                      publicationConsent.version ?? publicationConsent.current_version,
                    )
                  : T.consents.notGranted}
              </span>
            </div>
            {publicationConsent.granted ? (
              <Button variant="secondary" size="sm" onClick={() => setRevokeOpen(true)}>
                {T.consents.revoke}
              </Button>
            ) : (
              <Button
                variant="secondary"
                size="sm"
                loading={publication.isPending}
                onClick={() =>
                  publication.mutate(
                    { action: 'grant', version: publicationConsent.current_version },
                    { onError: (error) => toast.error(errorMessage(error)) },
                  )
                }
              >
                {T.consents.grant}
              </Button>
            )}
          </li>
          <li className="flex min-w-0 flex-wrap items-center justify-between gap-3 py-3 last:pb-0">
            <span className="type-body font-medium text-ink">{T.consents.fsp}</span>
            <Link to="/candidate/settings/fsp" className="text-link inline-flex min-h-11 items-center">
              {T.consents.fspOpen}
            </Link>
          </li>
        </ul>
      </Card>

      <Card>
        <AccessLog />
      </Card>
    </div>
  )

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <SettingsTabs />
      <PageHeader title={T.title} description={T.description} />
      {mutate.isError ? (
        <Alert variant="destructive">
          <AlertDescription>{errorMessage(mutate.error)}</AlertDescription>
        </Alert>
      ) : null}
      {wide ? (
        <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_420px] items-start gap-8">
          {settings}
          <div className="sticky top-24 min-w-0">
            <PrivacyPreview />
          </div>
        </div>
      ) : (
        <>
          {settings}
          <Collapsible className="surface-card min-w-0">
            <CollapsibleTrigger className="type-h3 tap-target group flex w-full min-w-0 items-center justify-between gap-2 text-left">
              {T.preview.title}
              <ChevronDown
                className="size-4 shrink-0 transition-transform group-data-[state=open]:rotate-180"
                aria-hidden="true"
              />
            </CollapsibleTrigger>
            <CollapsibleContent className="pt-3">
              <PrivacyPreview />
            </CollapsibleContent>
          </Collapsible>
        </>
      )}

      <AlertDialog open={revokeOpen} onOpenChange={setRevokeOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{T.consents.revokeTitle}</AlertDialogTitle>
          </AlertDialogHeader>
          <AlertDialogBody>
            <AlertDialogDescription>{T.consents.revokeText}</AlertDialogDescription>
          </AlertDialogBody>
          <AlertDialogFooter>
            <AlertDialogCancel>{T.consents.cancel}</AlertDialogCancel>
            <Button
              variant="destructive"
              loading={publication.isPending}
              onClick={() =>
                publication.mutate(
                  { action: 'revoke', version: publicationConsent.current_version },
                  {
                    onSuccess: () => setRevokeOpen(false),
                    onError: (error) => {
                      setRevokeOpen(false)
                      toast.error(errorMessage(error))
                    },
                  },
                )
              }
            >
              {T.consents.revoke}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
