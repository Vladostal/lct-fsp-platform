import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'
import type { MeView } from '@/client'
import { ErrorState, ExternalLink, PageHeader } from '@/components/app'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useEnterSession } from '@/features/auth'
import { errorMessage, hasCode, hasStatus } from '@/lib/api'
import { MAILPIT_PUBLIC_URL } from '@/lib/config'
import { formatDateTime, formatDuration } from '@/lib/format'
import { DEMO, RESTART_STORAGE } from '../content'
import { useDemoAccounts, useDemoLogin, useRestartScenario } from '../hooks'

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
        void queryClient.invalidateQueries()
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
    <div className="mx-auto flex w-full min-w-0 max-w-[880px] flex-col gap-6">
      <PageHeader title={DEMO.title} description={DEMO.description} />
      {expired ? (
        <Alert variant="info">
          <AlertDescription>{DEMO.expired}</AlertDescription>
        </Alert>
      ) : null}
      <Alert variant="info">
        <AlertDescription>{DEMO.shared}</AlertDescription>
      </Alert>

      <section aria-labelledby="demo-accounts" className="flex min-w-0 flex-col gap-3">
        <h2 id="demo-accounts" className="type-h2">
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
          <ul className="flex min-w-0 flex-col gap-3">
            {accounts.data.map((a) => (
              <li
                key={a.key}
                className="surface-row flex min-w-0 flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between"
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
        <section aria-labelledby="demo-restart" className="surface-card flex min-w-0 flex-col gap-3 p-5">
          <h2 id="demo-restart" className="type-h3">
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
        <h2 id="demo-links" className="type-h3">
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
    </div>
  )
}
