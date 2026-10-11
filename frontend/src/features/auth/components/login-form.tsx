import { zodResolver } from '@hookform/resolvers/zod'
import { Link } from '@tanstack/react-router'
import { LogIn, MonitorPlay } from 'lucide-react'
import { useForm } from 'react-hook-form'
import { IconTile, PasswordInput } from '@/components/app'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { applyFieldErrors, hasCode } from '@/lib/api'
import { AUTH } from '../content'
import { useEnterSession, useLogin, useResendVerification } from '../hooks'
import { type LoginValues, loginSchema } from '../schemas'
import { AuthCard } from './auth-card'
import { FormAlert } from './form-alert'
import { MailboxHint } from './mailbox-hint'

export type LoginFormProps = {
  /** Адрес возврата после входа (уже проверенный `safeNext`). */
  next?: string | null
  /** Флаг `features.demo`: ссылка на демо-аккаунты. */
  demo?: boolean
}

/**
 * P5. Вход. Неверная пара — одно сообщение на форму (в том числе для несуществующего адреса);
 * верный пароль при неподтверждённом адресе — плашка с «Отправить письмо ещё раз» (Арх. 10.1).
 */
export function LoginForm({ next, demo = false }: LoginFormProps) {
  const login = useLogin()
  const resend = useResendVerification()
  const enter = useEnterSession()
  const form = useForm<LoginValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: '', password: '' },
  })

  const onSubmit = form.handleSubmit((values) => {
    resend.reset()
    login.mutate(values, {
      onSuccess: (me) => enter(me, next),
      onError: (error) => applyFieldErrors(error, form.setError, ['email', 'password']),
    })
  })

  const notVerified = hasCode(login.error, 'email_not_verified')

  return (
    <AuthCard
      title={AUTH.login.title}
      icon={LogIn}
      footer={
        <>
          <span>{AUTH.login.noAccount}</span>
          <Link to="/signup" className="text-link inline-flex min-h-11 items-center">
            {AUTH.login.signup}
          </Link>
        </>
      }
    >
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
          <FormField
            control={form.control}
            name="password"
            render={({ field }) => (
              <FormItem>
                <div className="flex min-w-0 flex-wrap items-center justify-between gap-x-4">
                  <FormLabel required>{AUTH.fields.password}</FormLabel>
                  <Link to="/password/forgot" className="text-link tap-target inline-flex min-h-6 items-center text-sm">
                    {AUTH.login.forgot}
                  </Link>
                </div>
                <FormControl>
                  <PasswordInput autoComplete="current-password" aria-required="true" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          <FormAlert error={login.error}>
            {notVerified && !resend.isSuccess ? (
              <Button
                type="button"
                variant="link"
                loading={resend.isPending}
                onClick={() => resend.mutate(form.getValues('email').trim().toLowerCase())}
              >
                {AUTH.login.resend}
              </Button>
            ) : null}
          </FormAlert>
          {notVerified && resend.isSuccess ? (
            <>
              <Alert variant="success" live>
                <AlertDescription>{AUTH.login.resent}</AlertDescription>
              </Alert>
              <MailboxHint />
            </>
          ) : null}
          {notVerified ? <FormAlert error={resend.error} /> : null}

          <Button type="submit" variant="primary" className="w-full" loading={login.isPending}>
            {AUTH.login.submit}
          </Button>
        </form>
      </Form>

      {demo ? (
        <div className="flex min-w-0 flex-wrap items-center gap-3 rounded-md bg-brand-50 p-3">
          <IconTile icon={MonitorPlay} tone="plain" className="text-brand-700" />
          <p className="type-sm min-w-0 flex-1 basis-40 text-ink">{AUTH.login.demoText}</p>
          <Button variant="secondary" className="bg-surface" asChild>
            <Link to="/demo">{AUTH.login.demo}</Link>
          </Button>
        </div>
      ) : null}
    </AuthCard>
  )
}
