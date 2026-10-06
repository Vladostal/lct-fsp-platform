import { FileText, Upload } from 'lucide-react'
import { useRef, useState } from 'react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { errorMessage, errorText } from '@/lib/api'
import { cn } from '@/lib/utils'
import { PROFILE } from '../content'

export type ResumeStatus = 'idle' | 'uploading' | 'parsing' | 'parsed'

export type ResumeDropzoneProps = {
  status: ResumeStatus
  /** Ошибка последней загрузки; форма при этом остаётся рабочей. */
  error?: unknown
  fileName?: string | null
  onFile: (file: File) => void
  className?: string
}

const MAX_BYTES = 5 * 1024 * 1024

/** Проверка до отправки: те же тексты, что у кодов `resume_too_large` и `resume_not_pdf`. */
function precheck(file: File): string | null {
  const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')
  if (!isPdf) return errorText('resume_not_pdf')
  if (file.size > MAX_BYTES) return errorText('resume_too_large')
  return null
}

/** Загрузка резюме: перетаскивание или выбор файла. Состояния: idle → uploading → parsing → parsed. */
export function ResumeDropzone({ status, error, fileName, onFile, className }: ResumeDropzoneProps) {
  const R = PROFILE.resume
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)
  const busy = status === 'uploading' || status === 'parsing'
  const failure = localError ?? (error ? errorMessage(error) : null)

  const take = (file: File | undefined) => {
    if (!file || busy) return
    const problem = precheck(file)
    setLocalError(problem)
    if (!problem) onFile(file)
  }

  return (
    <div className={cn('flex min-w-0 flex-col gap-3', className)}>
      {/* biome-ignore lint/a11y/noStaticElementInteractions: зона перетаскивания; выбор файла доступен кнопкой */}
      <div
        onDragOver={(event) => {
          event.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault()
          setDragging(false)
          take(event.dataTransfer.files[0])
        }}
        className={cn(
          'flex min-w-0 flex-col items-center gap-3 rounded-lg border border-dashed border-line-strong bg-surface px-4 py-6 text-center transition-colors',
          dragging && 'border-brand-600 bg-brand-50',
        )}
      >
        <span
          className="flex size-10 items-center justify-center rounded-full bg-fill text-ink-muted"
          aria-hidden="true"
        >
          {status === 'parsed' ? <FileText className="size-5" /> : <Upload className="size-5" />}
        </span>
        <p className="type-body min-w-0 max-w-full text-ink [overflow-wrap:anywhere]">
          {status === 'uploading' ? R.uploading : status === 'parsing' ? R.parsing : (fileName ?? R.hint)}
        </p>
        {busy ? (
          <Progress
            className="max-w-xs"
            value={status === 'uploading' ? 30 : 75}
            aria-label={status === 'uploading' ? R.uploading : R.parsing}
          />
        ) : (
          <>
            <Button type="button" variant="secondary" onClick={() => inputRef.current?.click()}>
              {status === 'parsed' ? R.replace : R.choose}
            </Button>
            <p className="type-caption text-ink-muted">{status === 'parsed' ? R.hint : R.note}</p>
          </>
        )}
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          className="sr-only"
          tabIndex={-1}
          aria-label={R.title}
          onChange={(event) => {
            take(event.target.files?.[0])
            event.target.value = ''
          }}
        />
      </div>
      {failure ? (
        <Alert variant="destructive">
          <AlertTitle>{R.failedTitle}</AlertTitle>
          <AlertDescription>{failure}</AlertDescription>
        </Alert>
      ) : null}
    </div>
  )
}
