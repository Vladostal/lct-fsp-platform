import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useBlocker, useNavigate } from '@tanstack/react-router'
import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import type { AnswerResult, TestItemView, TestProgress, TestSessionView } from '@/client'
import { ErrorState, FocusHeaderSlot, StickyActionBar, usePageTitle } from '@/components/app'
import { Alert } from '@/components/ui/alert'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import { errorMessage, hasCode, hasStatus, isApiError } from '@/lib/api'
import { invalidateGuardData } from '@/lib/guards'
import { syncServerTime } from '@/lib/time'
import { draft, postAnswer, sessionQuery } from '../api'
import { ASSESSMENT } from '../content'
import { buildAnswer, type ItemValue, isKnownKind, TestItemRenderer } from './test-item-renderer'
import { TestTimer, useTestRemaining } from './test-timer'

type Live = {
  item: TestItemView | null
  progress: TestProgress
  expiresAt: string
  offsetMs: number
}

/** Сегменты по числу заданий минимальной формы; доп. блоки при росте формы просто добавляются в конец. */
function SegmentedProgress({ answered, total }: { answered: number; total: number }) {
  return (
    <div
      role="progressbar"
      aria-label="Прогресс теста"
      aria-valuemin={0}
      aria-valuemax={total}
      aria-valuenow={answered}
      className="flex h-1 w-full gap-0.5"
    >
      {Array.from({ length: total }, (_, i) => (
        <span
          // biome-ignore lint/suspicious/noArrayIndexKey: сегменты одинаковы, порядок фиксирован
          key={i}
          className={`flex-1 rounded-full transition-colors duration-(--dur-fast) ${
            i < answered ? 'bg-brand-600' : i === answered ? 'bg-brand-600/40' : 'bg-line'
          }`}
        />
      ))}
    </div>
  )
}

function fromServer(
  src: Pick<TestSessionView, 'progress' | 'expires_at' | 'server_now'> & { item?: TestItemView | null },
): Live {
  syncServerTime(src.server_now)
  return {
    item: src.item ?? null,
    progress: src.progress,
    expiresAt: src.expires_at,
    offsetMs: new Date(src.server_now).getTime() - Date.now(),
  }
}

function readDraft(sessionId: string, item: TestItemView): ItemValue {
  const raw = draft.read(`test:${sessionId}:${item.id}`)
  if (raw == null) return item.kind === 'multi_choice' ? [] : null
  try {
    return JSON.parse(raw) as ItemValue
  } catch {
    return null
  }
}

export function TestScreen({ sessionId }: { sessionId: string }) {
  const query = useQuery(sessionQuery(sessionId))
  usePageTitle('Тест')
  // Сбой фонового обновления при уже загруженной сессии тест не прерывает: задание и таймер остаются на экране.
  if (query.isError && !query.data) {
    return <ErrorState error={query.error} onRetry={() => query.refetch()} homeHref="/candidate" />
  }
  if (!query.data) {
    return (
      <div className="page-container flex max-w-[880px] flex-col gap-4 py-8" aria-busy="true">
        <Skeleton className="h-6 w-24" />
        <Skeleton className="h-10 w-3/4" />
        <Skeleton className="h-32 w-full" />
      </div>
    )
  }
  return <TestRunner sessionId={sessionId} session={query.data} refetch={() => query.refetch()} />
}

function TestRunner({
  sessionId,
  session,
  refetch,
}: {
  sessionId: string
  session: TestSessionView
  refetch: () => Promise<{ data?: TestSessionView }>
}) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [live, setLive] = useState<Live>(() => fromServer(session))
  const [value, setValue] = useState<ItemValue>(() => (session.item ? readDraft(sessionId, session.item) : null))
  const [busy, setBusy] = useState(false)
  const [netError, setNetError] = useState<{ skipped: boolean } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [growth, setGrowth] = useState<string | null>(null)
  const [skipOpen, setSkipOpen] = useState(false)
  const leaving = useRef(false)
  const titleRef = useRef<HTMLHeadingElement>(null)
  const shownAt = useRef(Date.now())
  const telemetry = useRef({ focusLost: 0, pasted: false })
  const expiredHandled = useRef(false)

  const item = live.item
  const remaining = useTestRemaining(live.expiresAt, live.offsetMs)
  const { valid, answer } = item ? buildAnswer(item, value) : { valid: false, answer: null }

  const goResult = useCallback(
    async (expired = false) => {
      // Закрытие сессии видят сразу и таймер, и обновлённый запрос, и ответ на отправку: уходим один раз.
      if (leaving.current) return
      leaving.current = true
      if (expired) toast(ASSESSMENT.test.expired)
      await invalidateGuardData(queryClient)
      await navigate({ to: '/candidate/test/$sessionId/result', params: { sessionId }, replace: true })
    },
    [navigate, queryClient, sessionId],
  )

  // Сессия уже закрыта — на результат.
  useEffect(() => {
    if (session.status !== 'in_progress') void goResult(session.status === 'expired')
  }, [session.status, goResult])

  // Смена задания: фокус на заголовок, прокрутка вверх, сброс телеметрии.
  const itemId = item?.id
  // biome-ignore lint/correctness/useExhaustiveDependencies: срабатывает только при смене задания
  useEffect(() => {
    shownAt.current = Date.now()
    telemetry.current = { focusLost: 0, pasted: false }
    window.scrollTo({ top: 0 })
    titleRef.current?.focus({ preventScroll: true })
  }, [itemId])

  // Телеметрия: смена видимости вкладки и вставки из буфера.
  useEffect(() => {
    const onVisibility = () => {
      if (document.hidden) telemetry.current.focusLost += 1
    }
    const onPaste = () => {
      telemetry.current.pasted = true
    }
    document.addEventListener('visibilitychange', onVisibility)
    document.addEventListener('paste', onPaste)
    return () => {
      document.removeEventListener('visibilitychange', onVisibility)
      document.removeEventListener('paste', onPaste)
    }
  }, [])

  // Время вышло: сервер закрывает сессию, клиент уходит на результат.
  useEffect(() => {
    if (remaining > 0 || expiredHandled.current) return
    expiredHandled.current = true
    void refetch().then((r) => {
      if (r.data && r.data.status !== 'in_progress') void goResult(r.data.status === 'expired')
      else expiredHandled.current = false
    })
  }, [remaining, refetch, goResult])

  useBlocker({
    shouldBlockFn: () => !leaving.current && !window.confirm(ASSESSMENT.test.leave),
    enableBeforeUnload: () => !leaving.current,
  })

  const submit = async (skipped: boolean) => {
    if (!item || busy) return
    if (!skipped && !valid) return
    setBusy(true)
    setError(null)
    setNetError(null)
    setGrowth(null)
    try {
      const result: AnswerResult = await postAnswer(sessionId, {
        item_id: item.id,
        answer: skipped ? null : answer,
        skipped,
        client: {
          time_spent_ms: Date.now() - shownAt.current,
          focus_lost: telemetry.current.focusLost,
          pasted: telemetry.current.pasted,
        },
      })
      draft.clear(`test:${sessionId}:${item.id}`)
      if (result.finished) {
        await goResult()
        return
      }
      const next = fromServer({ ...result, item: result.next_item })
      if (next.progress.min_total > live.progress.min_total) {
        const extra = next.progress.min_total - live.progress.min_total
        const minutes = Math.max(
          0,
          Math.round((new Date(next.expiresAt).getTime() - new Date(live.expiresAt).getTime()) / 60000),
        )
        setGrowth(`Результат на границе — добавлено ${extra} заданий и ${minutes} мин`)
      }
      setLive(next)
      setValue(next.item ? readDraft(sessionId, next.item) : null)
    } catch (e) {
      if (hasCode(e, 'session_expired')) await goResult(true)
      else if (hasCode(e, 'session_finished')) await goResult()
      else if (hasCode(e, 'item_already_answered')) {
        const r = await refetch()
        if (r.data?.item) {
          setLive(fromServer(r.data))
          setValue(readDraft(sessionId, r.data.item))
        }
      } else if (isApiError(e) && e.status === 0) setNetError({ skipped })
      else if (hasStatus(e, 404)) {
        // Сессии больше нет: вопрос «уйти из теста?» не нужен.
        leaving.current = true
        await navigate({ to: '/candidate' })
      } else setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  const change = (next: ItemValue) => {
    setValue(next)
    if (item) draft.write(`test:${sessionId}:${item.id}`, JSON.stringify(next))
  }

  // Ctrl/⌘+Enter отправляет ответ из любого места.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault()
        void submit(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const { answered, min_total } = live.progress
  const percent = min_total > 0 ? Math.min(100, (answered / min_total) * 100) : 0
  const known = item ? isKnownKind(item.kind) : false

  return (
    <div className="page-container flex min-w-0 max-w-[880px] flex-col gap-5 py-6 md:py-8">
      <FocusHeaderSlot>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex min-w-0 items-center justify-between gap-3">
            <span className="num type-sm shrink-0">
              {Math.min(answered + 1, min_total)} из {min_total}
            </span>
          </div>
          {min_total > 30 ? (
            <Progress value={percent} className="h-1" aria-label="Прогресс теста" />
          ) : (
            <SegmentedProgress answered={answered} total={min_total} />
          )}
        </div>
        <TestTimer remainingMs={remaining} />
      </FocusHeaderSlot>

      {growth ? (
        <Alert variant="info" live>
          {growth}
        </Alert>
      ) : null}

      {item ? (
        <section className="flex min-w-0 flex-col gap-4" aria-labelledby="item-title">
          <p className="type-eyebrow min-w-0 text-ink-muted">{item.skill_label}</p>
          <h1 id="item-title" ref={titleRef} tabIndex={-1} className="type-h1 min-w-0 break-words outline-none">
            {item.prompt}
          </h1>
          <TestItemRenderer
            item={item}
            value={value}
            onChange={change}
            onSubmit={() => submit(false)}
            disabled={busy}
          />
        </section>
      ) : session.status !== 'in_progress' ? null : (
        <ErrorState
          title="Задание не загрузилось"
          onRetry={() => void refetch().then((r) => r.data && setLive(fromServer(r.data)))}
          homeHref="/candidate"
        />
      )}

      {netError ? (
        <Alert variant="warning" live>
          <span className="min-w-0">{ASSESSMENT.test.networkError}</span>{' '}
          <Button size="sm" variant="secondary" onClick={() => submit(netError.skipped)}>
            {ASSESSMENT.test.retry}
          </Button>
        </Alert>
      ) : null}
      {error ? <Alert variant="destructive">{error}</Alert> : null}

      <StickyActionBar
        width="focus"
        secondary={
          <Button variant="ghost" disabled={busy || !item} onClick={() => setSkipOpen(true)}>
            {ASSESSMENT.test.skip}
          </Button>
        }
      >
        <Button variant="primary" loading={busy} disabled={!known || !valid || busy} onClick={() => submit(false)}>
          {ASSESSMENT.test.answer}
        </Button>
      </StickyActionBar>

      <AlertDialog open={skipOpen} onOpenChange={setSkipOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{ASSESSMENT.test.skipTitle}</AlertDialogTitle>
            <AlertDialogDescription>{ASSESSMENT.test.skipText}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{ASSESSMENT.test.cancel}</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                setSkipOpen(false)
                void submit(true)
              }}
            >
              {ASSESSMENT.test.skipConfirm}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
