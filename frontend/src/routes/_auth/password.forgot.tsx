import { createFileRoute } from '@tanstack/react-router'
import { ForgotPasswordForm } from '@/features/auth'

/** P5a. Запрос ссылки сброса пароля `/password/forgot`. */
export const Route = createFileRoute('/_auth/password/forgot')({
  component: ForgotPasswordForm,
})
