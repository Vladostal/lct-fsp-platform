import { Link } from '@tanstack/react-router'
import { MailCheck } from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { formatDuration } from '@/lib/format'
import { AUTH } from '../content'
import { useCountdown, useResendVerification } from '../hooks'
import { AuthCard } from './auth-card'
import { FormAlert } from './form-alert'
import { MailboxHint } from './mailbox-hint'

const RESEND_COOLDOWN_S = 60

/**
 * P3. «Проверьте почту». Основной кнопки нет: действие пользователя — вне сайта.
 * Адрес показан целиком (переносится, не усекается). «Отправить ещё раз» блокируется на 60 с с отсчётом.
 */
export function CheckEmailPanel({ email }: { email: string }) {
  const resend = useResendVerification()
  const countdown = useCountdown()

  const onResend = () => {
    resend.mutate(email, { onSuccess: () => countdown.start(RESEND_COOLDOWN_S) })
  }

  return (
    <AuthCard
      title={AUTH.checkEmail.title}
      icon={MailCheck}
      description={
        <div className="flex min-w-0 flex-col items-start gap-3">
          <p>{AUTH.checkEmail.textBefore}</p>
          <strong className="type-body max-w-full rounded-md bg-brand-50 px-3 py-2 font-medium text-brand-700 [overflow-wrap:anywhere]">
            {email}
          </strong>
          <p>{AUTH.checkEmail.textAfter}</p>
        </div>
      }
    >
      <MailboxHint />
      {resend.isSuccess && countdown.active ? (
        <Alert variant="success" live>
          <AlertDescription>{AUTH.checkEmail.resent}</AlertDescription>
        </Alert>
      ) : null}
      <FormAlert error={resend.error} />
      <div className="flex min-w-0 flex-col gap-3">
        <Button
          type="button"
          variant="link"
          className="w-full"
          onClick={onResend}
          loading={resend.isPending}
          disabled={countdown.active}
        >
          {countdown.active ? (
            <span>
              {AUTH.checkEmail.resendIn} <span className="num">{formatDuration(countdown.left)}</span>
            </span>
          ) : (
            AUTH.checkEmail.resend
          )}
        </Button>
        <Button variant="link" className="w-full" asChild>
          <Link to="/signup">{AUTH.checkEmail.changeEmail}</Link>
        </Button>
      </div>
    </AuthCard>
  )
}
