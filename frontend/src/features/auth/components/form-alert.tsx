import type * as React from 'react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { errorMessage } from '@/lib/api'

/** Ошибка мутации рядом с кнопкой (E §2.0): ввод сохраняется, текст — по коду из общего словаря. */
export function FormAlert({ error, children }: { error: unknown; children?: React.ReactNode }) {
  if (!error) return null
  return (
    <Alert variant="destructive">
      <AlertDescription>
        <p>{errorMessage(error)}</p>
        {children}
      </AlertDescription>
    </Alert>
  )
}
