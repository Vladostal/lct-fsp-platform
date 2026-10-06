import { Check, Copy } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { COMMON } from '@/content/common'
import { cn } from '@/lib/utils'

export type CopyButtonProps = {
  /** Что копируется. */
  value: string
  /** Что это за значение — для имени кнопки: «Скопировать e-mail». */
  label?: string
  size?: 'icon' | 'icon-sm'
  className?: string
}

/** Копирует значение, на 2 с меняет иконку на галочку и объявляет «Скопировано» (E §3.3). */
export function CopyButton({ value, label, size = 'icon-sm', className }: CopyButtonProps) {
  const [copied, setCopied] = useState(false)
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => () => window.clearTimeout(timer.current), [])

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value)
    } catch {
      // Буфер обмена недоступен (нет разрешения или небезопасный контекст) — запасной путь через выделение.
      const area = document.createElement('textarea')
      area.value = value
      area.setAttribute('readonly', '')
      area.style.position = 'fixed'
      area.style.opacity = '0'
      document.body.appendChild(area)
      area.select()
      document.execCommand('copy')
      area.remove()
    }
    setCopied(true)
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setCopied(false), 2000)
  }

  return (
    <>
      <Button
        type="button"
        variant="ghost"
        size={size}
        data-slot="copy-button"
        aria-label={label ? `${COMMON.copy} ${label}` : COMMON.copy}
        onClick={copy}
        className={cn('shrink-0', className)}
      >
        {copied ? <Check className="text-success" aria-hidden="true" /> : <Copy aria-hidden="true" />}
      </Button>
      <span className="sr-only" aria-live="polite">
        {copied ? COMMON.copied : ''}
      </span>
    </>
  )
}
