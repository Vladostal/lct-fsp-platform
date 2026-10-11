import { zodResolver } from '@hookform/resolvers/zod'
import { Link } from '@tanstack/react-router'
import { CircleAlert, Loader2, MailCheck, MailWarning, ShieldCheck } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useForm } from 'react-hook-form'
import { PasswordInput } from '@/components/app'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { errorMessage, hasCode } from '@/lib/api'
import { AUTH } from '../content'
import { useEnterSession, useResendVerification, useVerifyEmail } from '../hooks'
import { type EmailOnlyValues, emailOnlySchema, type PasswordOnlyValues, passwordOnlySchema } from '../schemas'
import { AuthCard } from './auth-card'
import { FormAlert } from './form-alert'
import { MailboxHint } from './mailbox-hint'

type Stage = 'pending' | 'password' | 'expired' | 'invalid' | 'error'

/**
 * P4. Подтверждение адреса. При открытии один раз отправляется токен; успех открывает сессию и ведёт на
 * первый экран роли. Если ссылку открыли не в браузере регистрации, сервер отвечает 409 `password_required` —
 * экран просит пароль заявки (Арх. 10.2): так чужая регистрация на адрес не превращается в подтверждённый
 * аккаунт с известным посторонним паролем.
 */
export function VerifyEmailPanel({ token }: { token: string | undefined }) {
  const verify = useVerifyEmail()
  const enter = useEnterSession()
  const [stage, setStage] = useState<Stage>(token ? 'pending' : 'invalid')
  // Защита от двойного вызова в StrictMode: токен одноразовый, второй запрос получил бы token_invalid.
  const started = useRef(false)

  const { mutate } = verify
  const run = useCallback(() => {
    if (!token) return
    setStage('pending')
    mutate(
      { token },
      {
        onSuccess: (me) => enter(me),
        onError: (error) => {
          if (hasCode(error, 'password_required')) setStage('password')
          else if (hasCode(error, 'token_expired')) setStage('expired')
          else if (hasCode(error, 'token_invalid')) setStage('invalid')
          else setStage('error')
        },
      },
    )
  }, [token, mutate, enter])

  useEffect(() => {
    if (!token || started.current) return
    started.current = true
    run()
  }, [token, run])

  if (stage === 'pending') {
    return (
      <AuthCard title={AUTH.verify.title} icon={MailCheck}>
        <p className="type-body flex items-center gap-3 text-ink-muted" role="status">
          <Loader2 className="size-5 animate-spin" aria-hidden="true" />
          {AUTH.verify.pending}
        </p>
      </AuthCard>
    )
  }

  if (stage === 'password' && token) {
    return <PasswordStage token={token} onStage={setStage} />
  }

  if (stage === 'expired') {
    return <ExpiredStage />
  }

  if (stage === 'error') {
    return (
      <AuthCard title={AUTH.verify.title} icon={CircleAlert} iconTone="warning">
        <Alert variant="destructive">
          <AlertDescription>{errorMessage(verify.error)}</AlertDescription>
        </Alert>
        <Button variant="secondary" className="w-full" loading={verify.isPending} onClick={run}>
          Повторить
        </Button>
      </AuthCard>
    )
  }

  return (
    <AuthCard
      title={AUTH.verify.invalidTitle}
      description={AUTH.verify.invalidText}
      icon={MailWarning}
      iconTone="warning"
    >
      <Button variant="primary" className="w-full" asChild>
        <Link to="/login">{AUTH.verify.login}</Link>
      </Button>
    </AuthCard>
  )
}

function PasswordStage({ token, onStage }: { token: string; onStage: (stage: Stage) => void }) {
  const verify = useVerifyEmail()
  const enter = useEnterSession()
  const form = useForm<PasswordOnlyValues>({
    resolver: zodResolver(passwordOnlySchema),
    defaultValues: { password: '' },
  })

  const onSubmit = form.handleSubmit((values) => {
    verify.mutate(
      { token, password: values.password },
      {
        onSuccess: (me) => enter(me),
        onError: (error) => {
          if (hasCode(error, 'token_expired')) onStage('expired')
          else if (hasCode(error, 'token_invalid')) onStage('invalid')
          else if (hasCode(error, 'invalid_credentials')) {
            form.setError('password', { message: 'Пароль не подошёл' }, { shouldFocus: true })
          }
        },
      },
    )
  })

  const passwordMismatch = hasCode(verify.error, 'invalid_credentials')

  return (
    <AuthCard title={AUTH.verify.passwordTitle} description={AUTH.verify.passwordText} icon={ShieldCheck}>
      <Form {...form}>
        <form onSubmit={onSubmit} noValidate className="flex min-w-0 flex-col gap-5">
          <FormField
            control={form.control}
            name="password"
            render={({ field }) => (
              <FormItem>
                <FormLabel required>{AUTH.fields.password}</FormLabel>
                <FormControl>
                  <PasswordInput autoComplete="current-password" aria-required="true" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          {passwordMismatch ? null : <FormAlert error={verify.error} />}
          <Button type="submit" variant="primary" className="w-full" loading={verify.isPending}>
            {AUTH.verify.passwordSubmit}
          </Button>
        </form>
      </Form>
    </AuthCard>
  )
}

function ExpiredStage() {
  const resend = useResendVerification()
  const form = useForm<EmailOnlyValues>({
    resolver: zodResolver(emailOnlySchema),
    defaultValues: { email: '' },
  })
  const onSubmit = form.handleSubmit((values) => resend.mutate(values.email))

  return (
    <AuthCard
      title={AUTH.verify.expiredTitle}
      description={AUTH.verify.expiredText}
      icon={MailWarning}
      iconTone="warning"
    >
      {resend.isSuccess ? (
        <>
          <Alert variant="success" live>
            <AlertDescription>{AUTH.verify.sentNew}</AlertDescription>
          </Alert>
          <MailboxHint />
        </>
      ) : (
        <Form {...form}>
          <form onSubmit={onSubmit} noValidate className="flex min-w-0 flex-col gap-5">
            <FormField
              control={form.control}
              name="email"
              render={({ field }) => (
                <FormItem>
                  <FormLabel required>{AUTH.fields.email}</FormLabel>
                  <FormControl>
                    <Input type="email" inputMode="email" autoComplete="email" aria-required="true" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormAlert error={resend.error} />
            <Button type="submit" variant="primary" className="w-full" loading={resend.isPending}>
              {AUTH.verify.sendNew}
            </Button>
          </form>
        </Form>
      )}
    </AuthCard>
  )
}
