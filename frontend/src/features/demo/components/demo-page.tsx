import { useQueryClient } from '@tanstack/react-query'
import { useRouter } from '@tanstack/react-router'
import {
  BarChart3,
  Building2,
  Clock,
  History,
  KeyRound,
  LogIn,
  Mail,
  RotateCcw,
  Trash2,
  User,
  Users,
} from 'lucide-react'
import type * as React from 'react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import type { MeView } from '@/client'
import { DashedNote, ErrorState, ExternalLink, GoChevron, IconTile, PageHeader, SoftPill } from '@/components/app'
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
    <div className="page-container flex w-full min-w-0 flex-col gap-6 py-8 md:py-12">
      <PageHeader title={DEMO.title} description={DEMO.description} />
      {expired ? (
        <Alert variant="info">
          <AlertDescription>{DEMO.expired}</AlertDescription>
        </Alert>
      ) : null}
      <div className="brand-band surface-row flex min-w-0 items-start gap-3 p-4">
        <IconTile icon={Users} tone="warning" />
        <p className="type-sm min-w-0 self-center break-words text-ink">{DEMO.shared}</p>
      </div>

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
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-busy="true">
            <span role="status" className="sr-only">
              Загружаем аккаунты…
            </span>
            {[0, 1, 2].map((n) => (
              <Skeleton key={n} className="h-40 w-full" />
            ))}
          </div>
        ) : accounts.isError ? (
          <ErrorState error={accounts.error} onRetry={() => accounts.refetch()} compact />
        ) : accounts.data.length === 0 ? (
          <DashedNote icon={Users}>{DEMO.empty}</DashedNote>
        ) : (
          <ul className="grid min-w-0 gap-3 sm:grid-cols-2 lg:grid-cols-3 lg:gap-4">
            {accounts.data.map((a, index) => {
              const employer = a.role === 'employer'
              return (
                <li
                  key={a.key}
                  style={{ '--i': index } as React.CSSProperties}
                  className={`lift-card surface-row stagger flex min-w-0 animate-rise-in flex-col gap-3 p-4 ${employer ? 'accent-card' : ''}`}
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <IconTile tone={employer ? 'ink' : 'brand'} size="lg">
                      {a.title.trim().charAt(0).toUpperCase()}
                    </IconTile>
                    <div className="flex min-w-0 flex-col items-start gap-1">
                      <p className="type-h3 min-w-0 break-words">{a.title}</p>
                      <SoftPill size="sm" tone={employer ? 'solid' : 'brand'} icon={employer ? Building2 : User}>
                        {DEMO.roles[a.role] ?? a.role}
                      </SoftPill>
                    </div>
                  </div>
                  <ul aria-label={DEMO.columns.state} className="flex min-w-0 flex-1 flex-wrap content-start gap-1.5">
                    {stateParts(a.state_label).map((part) => (
                      <li
                        key={part}
                        className="type-sm max-w-full min-w-0 rounded-md bg-fill px-2.5 py-1 break-words text-ink"
                      >
                        {part}
                      </li>
                    ))}
                  </ul>
                  <Button
                    type="button"
                    variant="secondary"
                    className="w-full"
                    loading={login.isPending && login.variables === a.key}
                    disabled={login.isPending}
                    onClick={() => signIn(a.key)}
                  >
                    <LogIn aria-hidden="true" />
                    {DEMO.enter(a.title)}
                  </Button>
                </li>
              )
            })}
          </ul>
        )}
      </section>

      <div className="flex min-w-0 flex-col gap-3 lg:gap-4">
        {me?.is_demo ? (
          <section aria-labelledby="demo-restart" className="surface-row flex min-w-0 flex-col gap-3 p-4 md:p-5">
            <div className="flex min-w-0 items-center gap-3">
              <IconTile icon={RotateCcw} tone="warning" />
              <h2 id="demo-restart" className="type-h3 min-w-0">
                {DEMO.restart}
              </h2>
            </div>
            <p className="type-sm min-w-0 break-words text-ink-muted">{DEMO.restartHint}</p>
            <p className="flex min-w-0">
              <SoftPill icon={History} className="h-auto min-h-7 shrink py-0.5">
                <span className="num min-w-0">
                  {lastRestart ? DEMO.lastRestart(formatDateTime(lastRestart)) : DEMO.neverRestarted}
                </span>
              </SoftPill>
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
              <RotateCcw aria-hidden="true" />
              {DEMO.restart}
            </Button>
          </section>
        ) : null}

        <section aria-labelledby="demo-links" className="flex min-w-0 flex-col gap-3">
          <h2 id="demo-links" className="sr-only">
            {DEMO.links}
          </h2>
          <ul className="grid min-w-0 gap-3 sm:grid-cols-2 lg:gap-4">
            {MAILPIT_PUBLIC_URL ? (
              <li className="lift-card surface-row flex min-h-16 min-w-0 items-center gap-3 px-4 py-3">
                <IconTile icon={Mail} tone="soft" />
                <ExternalLink href={MAILPIT_PUBLIC_URL} className="tap-target min-w-0 flex-1">
                  {DEMO.mailbox}
                </ExternalLink>
              </li>
            ) : null}
            <li className="lift-card surface-row relative flex min-h-16 min-w-0 items-center gap-3 px-4 py-3">
              <IconTile icon={BarChart3} tone="soft" />
              <a
                className="type-body min-w-0 flex-1 font-medium break-words text-ink after:absolute after:inset-0 after:z-[1] hover:text-brand-700"
                href="/how-it-works"
              >
                {DEMO.reports}
              </a>
              <GoChevron />
            </li>
          </ul>
        </section>
      </div>

      <details className="surface-row group min-w-0 px-4">
        <summary className="type-sm flex min-h-14 cursor-pointer list-none items-center gap-3 font-medium text-ink-muted hover:text-ink">
          <IconTile icon={KeyRound} tone="neutral" size="sm" />
          {DEMO.host}
        </summary>
        <div className="pb-4">
          <HostBlock />
        </div>
      </details>
    </div>
  )
}

/** Строка состояния аккаунта приходит одной фразой: делим её по «; » и «: » на короткие плашки. */
function stateParts(label: string): string[] {
  const parts: string[] = []
  let current = ''
  let quoted = 0
  for (let i = 0; i < label.length; i++) {
    const ch = label[i]
    if (ch === '«') quoted++
    else if (ch === '»') quoted = Math.max(0, quoted - 1)
    // Внутри кавычек «…» не режем: это цитата статуса целиком.
    if ((ch === ';' || ch === ':') && quoted === 0 && label[i + 1] === ' ') {
      parts.push(current)
      current = ''
    } else current += ch
  }
  parts.push(current)
  return [...new Set(parts.map((x) => x.trim()).filter(Boolean))]
}

function HostBlock() {
  const [key, setKey] = useState(() => read(HOST_KEY_STORAGE, 'session'))
  const [draft, setDraft] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [confirmReset, setConfirmReset] = useState(false)
  const clock = useDemoClock(Boolean(key), key)
  const advance = useAdvanceClock(key)
  const reset = useResetDemo(key)
  const queryClient = useQueryClient()

  const bad = (e: unknown) => {
    if (hasStatus(e, 403) || hasStatus(e, 401)) {
      setError(DEMO.hostBad)
      setKey('')
      write(HOST_KEY_STORAGE, null, 'session')
    } else setError(errorMessage(e))
  }

  // Неверный ключ виден сразу, по запросу часов, а не только при первом действии.
  const clockError = clock.error
  useEffect(() => {
    if (!clockError) return
    if (hasStatus(clockError, 403) || hasStatus(clockError, 401)) {
      setError(DEMO.hostBad)
      setKey('')
      write(HOST_KEY_STORAGE, null, 'session')
    } else setError(errorMessage(clockError))
  }, [clockError])

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
            setError(null)
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
          <p className="flex min-w-0">
            <SoftPill icon={Clock} tone="brand" className="h-auto min-h-7 shrink py-0.5">
              <span className="num min-w-0">
                {DEMO.serverTime}: {clock.data ? formatDateTime(clock.data.now) : '—'}
              </span>
            </SoftPill>
          </p>
          <div className="flex min-w-0 flex-wrap gap-2">
            <Button type="button" variant="secondary" loading={advance.isPending} onClick={() => shift(24)}>
              {DEMO.plus1}
            </Button>
            <Button type="button" variant="secondary" loading={advance.isPending} onClick={() => shift(24 * 7)}>
              {DEMO.plus7}
            </Button>
            <Button type="button" variant="ghost" onClick={() => setConfirmReset(true)}>
              <Trash2 aria-hidden="true" />
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
                    // Демо-аккаунты пересозданы: список и всё, что открыто под демо-сессией, устарело.
                    void queryClient.invalidateQueries()
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
