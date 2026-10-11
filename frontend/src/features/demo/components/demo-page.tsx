import { useQueryClient } from '@tanstack/react-query'
import { useRouter } from '@tanstack/react-router'
import { useState } from 'react'
import { toast } from 'sonner'
import type { MeView } from '@/client'
import { ErrorState, ExternalLink, PageHeader } from '@/components/app'
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
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { useEnterSession } from '@/features/auth'
import { errorMessage, hasCode, hasStatus } from '@/lib/api'
import { MAILPIT_PUBLIC_URL } from '@/lib/config'
import { formatDateTime, formatDuration } from '@/lib/format'
import { DEMO, HOST_KEY_STORAGE, RESTART_STORAGE } from '../content'
import {
  useAdvanceClock,
  useDemoAccounts,
  useDemoClock,
  useDemoLogin,
  useResetDemo,
  useRestartScenario,
} from '../hooks'

function read(key: string, storage: 'session' | 'local'): string {
  try {
    return (storage === 'session' ? sessionStorage : localStorage).getItem(key) ?? ''
  } catch {
    return ''
  }
}
function write(key: string, value: string | null, storage: 'session' | 'local') {
  try {
    const s = storage === 'session' ? sessionStorage : localStorage
    if (value === null) s.removeItem(key)
    else s.setItem(key, value)
  } catch {
    /* хранилище недоступно */
  }
}

type Props = { me: MeView | null; expired: boolean }

export function DemoPage({ me, expired }: Props) {
  const accounts = useDemoAccounts()
  const login = useDemoLogin()
  const enter = useEnterSession()
  const restart = useRestartScenario()
  const queryClient = useQueryClient()
  const router = useRouter()
  const [lastRestart, setLastRestart] = useState(() => read(RESTART_STORAGE, 'local'))
  const [restartNote, setRestartNote] = useState<string | null>(null)
  const [loginError, setLoginError] = useState<string | null>(null)

  const signIn = (key: string) => {
    setLoginError(null)
    login.mutate(key, {
      onSuccess: (user) => void enter(user),
      onError: (e) => setLoginError(errorMessage(e)),
    })
  }

  const doRestart = () => {
    setRestartNote(null)
    restart.mutate(undefined, {
      onSuccess: (r) => {
        setLastRestart(r.restarted_at)
        write(RESTART_STORAGE, r.restarted_at, 'local')
        toast.success(DEMO.restartDone)
        // Перезапуск удаляет и сессию вызвавшего: перечитываем `me`, чтобы страница сразу стала гостевой.
        void queryClient.invalidateQueries().then(() => router.invalidate())
      },
      onError: (e) => {
        if (hasCode(e, 'rate_limited')) {
          const sec = Number((e.params as Record<string, unknown>).retry_after)
          setRestartNote(
            `${DEMO.restartTooSoon}${Number.isFinite(sec) && sec > 0 ? ` Следующий — через ${formatDuration(sec)}.` : ''}`,
          )
        } else if (hasStatus(e, 403)) setRestartNote(DEMO.restartForbidden)
        else setRestartNote(errorMessage(e))
      },
    })
  }

  return (
    <div className="mx-auto flex w-full min-w-0 max-w-[880px] flex-col gap-8">
      <PageHeader title={DEMO.title} description={DEMO.description} />
      {expired ? (
        <Alert variant="info">
          <AlertDescription>{DEMO.expired}</AlertDescription>
        </Alert>
      ) : null}
      <p className="type-sm text-ink-muted">{DEMO.shared}</p>

      <section aria-labelledby="demo-accounts" className="flex min-w-0 flex-col gap-3">
        <h2 id="demo-accounts" className="type-eyebrow">
          {DEMO.accounts}
        </h2>
        {loginError ? (
          <Alert variant="destructive">
            <AlertDescription>{loginError}</AlertDescription>
          </Alert>
        ) : null}
        {accounts.isPending ? (
          <div className="flex flex-col gap-2" aria-busy="true">
            <span role="status" className="sr-only">
              Загружаем аккаунты…
            </span>
            {[0, 1, 2].map((n) => (
              <Skeleton key={n} className="h-16 w-full" />
            ))}
          </div>
        ) : accounts.isError ? (
          <ErrorState error={accounts.error} onRetry={() => accounts.refetch()} compact />
        ) : accounts.data.length === 0 ? (
          <p className="type-sm text-ink-muted">{DEMO.empty}</p>
        ) : (
          <ul className="flex min-w-0 flex-col divide-y divide-line">
            {accounts.data.map((a) => (
              <li
                key={a.key}
                className="flex min-w-0 flex-col gap-3 py-4 sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="min-w-0">
                  <p className="type-h3 min-w-0 break-words">{a.title}</p>
                  <p className="type-sm min-w-0 break-words text-ink-muted">
                    {DEMO.roles[a.role] ?? a.role} · {a.state_label}
                  </p>
                </div>
                <Button
                  type="button"
                  variant="secondary"
                  className="shrink-0"
                  loading={login.isPending && login.variables === a.key}
                  disabled={login.isPending}
                  onClick={() => signIn(a.key)}
                >
                  {DEMO.enter(a.title)}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {me?.is_demo ? (
        <section aria-labelledby="demo-restart" className="flex min-w-0 flex-col gap-3">
          <h2 id="demo-restart" className="type-eyebrow">
            {DEMO.restart}
          </h2>
          <p className="type-sm text-ink-muted">{DEMO.restartHint}</p>
          <p className="type-sm num">
            {lastRestart ? DEMO.lastRestart(formatDateTime(lastRestart)) : DEMO.neverRestarted}
          </p>
          {restartNote ? (
            <Alert variant="warning">
              <AlertDescription>{restartNote}</AlertDescription>
            </Alert>
          ) : null}
          <Button
            type="button"
            variant="secondary"
            className="self-start"
            loading={restart.isPending}
            onClick={doRestart}
          >
            {DEMO.restart}
          </Button>
        </section>
      ) : null}

      <section aria-labelledby="demo-links" className="flex min-w-0 flex-col gap-2">
        <h2 id="demo-links" className="type-eyebrow">
          {DEMO.links}
        </h2>
        <ul className="flex min-w-0 flex-col gap-1">
          {MAILPIT_PUBLIC_URL ? (
            <li>
              <ExternalLink href={MAILPIT_PUBLIC_URL}>{DEMO.mailbox}</ExternalLink>
            </li>
          ) : null}
          <li>
            <a className="text-link" href="/how-it-works">
              {DEMO.reports}
            </a>
          </li>
        </ul>
      </section>

      <details className="group min-w-0">
        <summary className="type-sm tap-target cursor-pointer list-none text-ink-muted hover:text-ink">
          {DEMO.host}
        </summary>
        <div className="pt-3">
          <HostBlock />
        </div>
      </details>
    </div>
  )
}

function HostBlock() {
  const [key, setKey] = useState(() => read(HOST_KEY_STORAGE, 'session'))
  const [draft, setDraft] = useState('')
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirmReset, setConfirmReset] = useState(false)
  const clock = useDemoClock(Boolean(key), key)
  const advance = useAdvanceClock(key)
  const reset = useResetDemo(key)

  const bad = (e: unknown) => {
    if (hasStatus(e, 403) || hasStatus(e, 401)) {
      setError(DEMO.hostBad)
      setKey('')
      write(HOST_KEY_STORAGE, null, 'session')
    } else setError(errorMessage(e))
  }

  const shift = (hours: number, force = false) => {
    setError(null)
    advance.mutate(
      { hours, force },
      {
        onSuccess: () => {
          toast.success(DEMO.clockDone)
          void clock.refetch()
        },
        onError: (e) => {
          if (hasCode(e, 'sessions_in_progress') && !force) {
            if (window.confirm(DEMO.inProgress)) shift(hours, true)
          } else bad(e)
        },
      },
    )
  }

  if (!key && !open) {
    return (
      <p>
        <Button type="button" variant="link" size="sm" onClick={() => setOpen(true)}>
          {DEMO.host}
        </Button>
      </p>
    )
  }

  return (
    <section aria-labelledby="demo-host" className="flex min-w-0 flex-col gap-3">
      <h2 id="demo-host" className="type-h3">
        {DEMO.host}
      </h2>
      {error ? (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
      {!key ? (
        <form
          className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-end"
          onSubmit={(e) => {
            e.preventDefault()
            if (!draft.trim()) return
            write(HOST_KEY_STORAGE, draft.trim(), 'session')
            setKey(draft.trim())
            setDraft('')
          }}
        >
          <div className="flex min-w-0 flex-1 flex-col gap-1.5">
            <Label htmlFor="host-key">{DEMO.hostKey}</Label>
            <Input
              id="host-key"
              type="password"
              autoComplete="off"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
            />
          </div>
          <Button type="submit" variant="secondary">
            {DEMO.hostSave}
          </Button>
        </form>
      ) : (
        <>
          <p className="type-sm num">
            {DEMO.serverTime}: {clock.data ? formatDateTime(clock.data.now) : '—'}
          </p>
          <div className="flex min-w-0 flex-wrap gap-2">
            <Button type="button" variant="secondary" loading={advance.isPending} onClick={() => shift(24)}>
              {DEMO.plus1}
            </Button>
            <Button type="button" variant="secondary" loading={advance.isPending} onClick={() => shift(24 * 7)}>
              {DEMO.plus7}
            </Button>
            <Button type="button" variant="ghost" onClick={() => setConfirmReset(true)}>
              {DEMO.reset}
            </Button>
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setKey('')
                write(HOST_KEY_STORAGE, null, 'session')
              }}
            >
              {DEMO.hostForget}
            </Button>
          </div>
        </>
      )}
      <AlertDialog open={confirmReset} onOpenChange={setConfirmReset}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{DEMO.resetTitle}</AlertDialogTitle>
          </AlertDialogHeader>
          <AlertDialogBody>
            <AlertDialogDescription>{DEMO.resetText}</AlertDialogDescription>
          </AlertDialogBody>
          <AlertDialogFooter>
            <AlertDialogCancel>{DEMO.cancel}</AlertDialogCancel>
            <Button
              type="button"
              variant="destructive"
              loading={reset.isPending}
              onClick={() =>
                reset.mutate(undefined, {
                  onSuccess: () => {
                    setConfirmReset(false)
                    toast.success(DEMO.resetDone)
                  },
                  onError: (e) => {
                    setConfirmReset(false)
                    bad(e)
                  },
                })
              }
            >
              {DEMO.resetConfirm}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  )
}
