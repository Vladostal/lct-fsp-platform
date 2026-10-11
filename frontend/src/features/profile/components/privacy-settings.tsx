import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import {
  AlignLeft,
  Briefcase,
  Check,
  ChevronDown,
  Eye,
  EyeOff,
  FileCheck2,
  Gauge,
  Handshake,
  Layers,
  Link2,
  Lock,
  type LucideIcon,
  MapPin,
  Megaphone,
  Minus,
  Phone,
  ScanEye,
  Send,
  ShieldCheck,
  Trophy,
  UserRound,
  Users,
} from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import type { PrivacySettings as PrivacyValues } from '@/client'
import { fspGetLinkOptions } from '@/client/@tanstack/react-query.gen'
import { ErrorState, IconTile, PageHeader, PageSkeleton, SoftPill, type TileTone } from '@/components/app'
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
import { Card } from '@/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Switch } from '@/components/ui/switch'
import { errorMessage } from '@/lib/api'
import { formatDate } from '@/lib/format'
import { useMediaQuery } from '@/lib/hooks/use-media-query'
import { cn } from '@/lib/utils'
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
import { CardHead } from './card-head'
import { PrivacyPreview } from './privacy-preview'
import { SettingsTabs } from './settings-tabs'

type ToggleKey = keyof Omit<PrivacyValues, 'hidden_domains'>

function ToggleRow({
  id,
  icon,
  iconTone = 'brand',
  label,
  note,
  checked,
  disabled,
  disabledNote,
  onChange,
}: {
  id: ToggleKey
  icon: LucideIcon
  iconTone?: TileTone
  label: string
  note?: string
  checked: boolean
  disabled?: boolean
  disabledNote?: React.ReactNode
  onChange: (value: boolean) => void
}) {
  const on = checked && !disabled
  return (
    <li className="flex min-w-0 items-center gap-3 py-2.5">
      <IconTile icon={icon} tone={on ? iconTone : 'neutral'} size="xs" className={cn(!on && 'text-ink-muted')} />
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <label htmlFor={`privacy-${id}`} className="type-body min-w-0 font-medium text-ink">
          {label}
        </label>
        {disabled && disabledNote ? (
          <span className="type-caption text-ink-muted">{disabledNote}</span>
        ) : note ? (
          <span className="type-caption text-ink-muted">{note}</span>
        ) : null}
      </div>
      <Switch id={`privacy-${id}`} checked={on} disabled={disabled} onCheckedChange={onChange} />
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

  const visible = state.state === 'visible'
  const consentPill = (granted: boolean, text: string, testId?: string) => (
    <SoftPill
      tone={granted ? 'success' : 'neutral'}
      icon={granted ? Check : Minus}
      size="sm"
      className="h-auto min-h-6 shrink rounded-xl py-0.5 [&>svg]:size-3.5 [&>svg]:shrink-0"
    >
      <span className="min-w-0 [overflow-wrap:anywhere]" data-testid={testId}>
        {text}
      </span>
    </SoftPill>
  )

  const settings = (
    <div className="flex min-w-0 flex-col gap-4">
      <div className={cn('surface-card flex min-w-0 animate-rise-in flex-col gap-3', visible && 'accent-card')}>
        <div className="flex min-w-0 items-center gap-3">
          <IconTile icon={visible ? Eye : EyeOff} tone={visible ? 'success' : 'neutral'} size="xl" />
          <div className="flex min-w-0 flex-1 flex-col gap-0.5">
            <h2 className="type-caption font-semibold tracking-wide text-ink-muted uppercase">{T.show.title}</h2>
            <label htmlFor="privacy-visible" className="type-h3 min-w-0 text-ink">
              {T.show.label}
            </label>
          </div>
          <Switch
            id="privacy-visible"
            checked={visible}
            disabled={state.state === 'not_ready' || visibility.isPending}
            onCheckedChange={toggleVisible}
          />
        </div>
        <p className="type-sm min-w-0 text-ink-muted" data-testid="visibility-text">
          {stateText}
        </p>
        {state.pause_reason === 'auto_silence' && state.state === 'paused' ? (
          <Button
            variant="secondary"
            className="self-start"
            loading={resume.isPending}
            onClick={() => resume.mutate(undefined, { onError: (e) => toast.error(errorMessage(e)) })}
          >
            {T.show.resume}
          </Button>
        ) : null}
      </div>

      <Card className="gap-4">
        <CardHead icon={Users} title={T.before.title} />
        {/* Всегда видимое — пилюли с замком: скрыть нельзя. */}
        <div className="flex min-w-0 flex-col gap-2 rounded-lg bg-fill p-3">
          <p className="type-caption flex items-center gap-1.5 font-semibold tracking-wide text-ink-muted uppercase">
            <Lock className="size-3.5" aria-hidden="true" />
            {T.before.locked}
          </p>
          <ul className="flex min-w-0 flex-wrap gap-1.5">
            {T.before.always.map((line) => (
              <li key={line} className="max-w-full min-w-0">
                <SoftPill size="sm" className="h-auto min-h-6 rounded-xl bg-surface py-0.5 text-ink">
                  {line}
                </SoftPill>
              </li>
            ))}
          </ul>
        </div>
        <ul className="flex min-w-0 flex-col divide-y divide-line">
          <ToggleRow
            id="show_city"
            icon={MapPin}
            label={T.toggles.show_city.label}
            checked={flag('show_city')}
            onChange={set('show_city')}
          />
          <ToggleRow
            id="show_experience"
            icon={Briefcase}
            label={T.toggles.show_experience.label}
            checked={flag('show_experience')}
            onChange={set('show_experience')}
          />
          <ToggleRow
            id="show_declared_stack"
            icon={Layers}
            label={T.toggles.show_declared_stack.label}
            note={T.toggles.show_declared_stack.note}
            checked={flag('show_declared_stack')}
            onChange={set('show_declared_stack')}
          />
          <ToggleRow
            id="show_about"
            icon={AlignLeft}
            label={T.toggles.show_about.label}
            note={T.toggles.show_about.note}
            checked={flag('show_about', false)}
            onChange={set('show_about')}
          />
          <ToggleRow
            id="show_fsp_summary"
            icon={Trophy}
            iconTone="accent"
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
        <p className="type-caption flex min-w-0 items-start gap-2 text-ink-muted">
          <Gauge className="mt-px size-3.5 shrink-0" aria-hidden="true" />
          <span className="min-w-0">{T.before.strengthNote}</span>
        </p>
      </Card>

      <Card className="gap-4">
        <CardHead icon={Handshake} tone="success" title={T.after.title} />
        <ul className="flex min-w-0 flex-col divide-y divide-line">
          <li className="flex min-w-0 items-center gap-3 py-2.5">
            <IconTile icon={UserRound} tone="success" size="xs" />
            <span className="type-body min-w-0 flex-1 font-medium text-ink">{T.after.always}</span>
            <SoftPill tone="success" icon={Check} size="sm" className="[&>svg]:size-3.5">
              {T.after.alwaysPill}
            </SoftPill>
          </li>
          <ToggleRow
            id="reveal_phone"
            icon={Phone}
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
            icon={Send}
            label={T.toggles.reveal_telegram.label}
            checked={flag('reveal_telegram', false)}
            disabled={!person.telegram}
            disabledNote={T.noTelegram}
            onChange={set('reveal_telegram')}
          />
          <ToggleRow
            id="reveal_link"
            icon={Link2}
            label={T.toggles.reveal_link.label}
            checked={flag('reveal_link', false)}
            disabled={!person.link}
            disabledNote={T.noLink}
            onChange={set('reveal_link')}
          />
          <ToggleRow
            id="reveal_fsp_details"
            icon={Trophy}
            iconTone="accent"
            label={T.toggles.reveal_fsp_details.label}
            checked={flag('reveal_fsp_details', false)}
            disabled={!fspLinked}
            disabledNote={T.noFsp}
            onChange={set('reveal_fsp_details')}
          />
        </ul>
        <p className="type-caption min-w-0 text-ink-muted">{T.after.note}</p>
      </Card>

      <Card className="gap-4">
        <CardHead icon={ShieldCheck} title={T.consents.title} />
        <ul className="flex min-w-0 flex-col divide-y divide-line">
          <li className="flex min-w-0 items-start gap-3 py-3 first:pt-0">
            <IconTile icon={FileCheck2} tone={processing.granted ? 'success' : 'neutral'} size="xs" />
            <div className="flex min-w-0 flex-1 flex-col items-start gap-1">
              <span className="type-body font-medium text-ink">{T.consents.processing}</span>
              {consentPill(
                Boolean(processing.granted && processing.granted_at),
                processing.granted && processing.granted_at
                  ? T.consents.granted(
                      formatDate(processing.granted_at),
                      processing.version ?? processing.current_version,
                    )
                  : T.consents.notGranted,
              )}
            </div>
          </li>
          <li className="flex min-w-0 flex-wrap items-start gap-3 py-3">
            <IconTile icon={Megaphone} tone={publicationConsent.granted ? 'success' : 'neutral'} size="xs" />
            <div className="flex min-w-0 flex-1 basis-52 flex-col items-start gap-1">
              <span className="type-body font-medium text-ink">{T.consents.publication}</span>
              {consentPill(
                Boolean(publicationConsent.granted && publicationConsent.granted_at),
                publicationConsent.granted && publicationConsent.granted_at
                  ? T.consents.granted(
                      formatDate(publicationConsent.granted_at),
                      publicationConsent.version ?? publicationConsent.current_version,
                    )
                  : T.consents.notGranted,
                'publication-consent',
              )}
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
          <li className="flex min-w-0 flex-wrap items-center gap-x-3 py-1 last:pb-0">
            <IconTile icon={Trophy} tone="accent" size="xs" />
            <span className="type-body min-w-0 flex-1 basis-32 font-medium text-ink">{T.consents.fsp}</span>
            <Link to="/candidate/settings/fsp" className="text-link inline-flex min-h-11 items-center">
              {T.consents.fspOpen}
            </Link>
          </li>
        </ul>
      </Card>

      <Card className="gap-4">
        <AccessLog />
      </Card>
    </div>
  )

  return (
    <div className="mx-auto flex w-full max-w-5xl min-w-0 flex-col gap-6">
      <SettingsTabs />
      <PageHeader title={T.title} description={T.description} />
      {mutate.isError ? (
        <Alert variant="destructive">
          <AlertDescription>{errorMessage(mutate.error)}</AlertDescription>
        </Alert>
      ) : null}
      {wide ? (
        <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_380px] items-start gap-6">
          {settings}
          <div className="sticky top-24 min-w-0">
            <PrivacyPreview />
          </div>
        </div>
      ) : (
        <>
          {settings}
          <Collapsible className="surface-card min-w-0">
            <CollapsibleTrigger className="type-h3 tap-target group flex w-full min-w-0 items-center gap-3 text-left">
              <IconTile icon={ScanEye} tone="solid" size="sm" />
              <span className="min-w-0 flex-1">{T.preview.title}</span>
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
