import { zodResolver } from '@hookform/resolvers/zod'
import { Link } from '@tanstack/react-router'
import { CircleCheck, MailCheck, MailWarning } from 'lucide-react'
import { useForm } from 'react-hook-form'
import { PasswordInput } from '@/components/app'
import { Button } from '@/components/ui/button'
import { Form, FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { applyFieldErrors, hasCode } from '@/lib/api'
import { AUTH } from '../content'
import { useForgotPassword, useResetPassword } from '../hooks'
import { type EmailOnlyValues, emailOnlySchema, type ResetPasswordValues, resetPasswordSchema } from '../schemas'
import { AuthCard } from './auth-card'
import { FormAlert } from './form-alert'
import { MailboxHint } from './mailbox-hint'

const backToLogin = (
  <Link to="/login" className="text-link inline-flex min-h-11 items-center">
    {AUTH.forgot.backToLogin}
  </Link>
)

/**
 * P5a. Запрос ссылки сброса пароля. Ответ одинаков для любого адреса — экран не сообщает, есть ли аккаунт.
 */
export function ForgotPasswordForm() {
  const forgot = useForgotPassword()
  const form = useForm<EmailOnlyValues>({
    resolver: zodResolver(emailOnlySchema),
    defaultValues: { email: '' },
  })
  const onSubmit = form.handleSubmit((values) =>
    forgot.mutate(values.email, { onError: (error) => applyFieldErrors(error, form.setError, ['email']) }),
  )

  if (forgot.isSuccess) {
    return (
      <AuthCard title={AUTH.forgot.sentTitle} description={AUTH.forgot.sentText} icon={MailCheck} footer={backToLogin}>
        <MailboxHint />
      </AuthCard>
    )
  }

  return (
    <AuthCard title={AUTH.forgot.title} description={AUTH.forgot.description} footer={backToLogin}>
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
          <FormAlert error={forgot.error} />
          <Button type="submit" variant="primary" className="w-full" loading={forgot.isPending}>
            {AUTH.forgot.submit}
          </Button>
        </form>
      </Form>
    </AuthCard>
  )
}

/** P5a. Новый пароль по ссылке из письма (токен действует час и срабатывает один раз). */
export function ResetPasswordForm({ token }: { token: string | undefined }) {
  const reset = useResetPassword()
  const form = useForm<ResetPasswordValues>({
    resolver: zodResolver(resetPasswordSchema),
    defaultValues: { new_password: '' },
  })
  const badLink = !token || hasCode(reset.error, 'token_invalid', 'token_expired')

  if (reset.isSuccess) {
    return (
      <AuthCard title={AUTH.reset.doneTitle} description={AUTH.reset.doneText} icon={CircleCheck} iconTone="success">
        <Button variant="primary" className="w-full" asChild>
          <Link to="/login">{AUTH.reset.login}</Link>
        </Button>
      </AuthCard>
    )
  }

  if (badLink) {
    return (
      <AuthCard
        title={AUTH.reset.badLinkTitle}
        description={AUTH.reset.badLinkText}
        icon={MailWarning}
        iconTone="warning"
        footer={backToLogin}
      >
        <Button variant="primary" className="w-full" asChild>
          <Link to="/password/forgot">{AUTH.reset.requestNew}</Link>
        </Button>
      </AuthCard>
    )
  }

  const onSubmit = form.handleSubmit((values) =>
    reset.mutate(
      { token, new_password: values.new_password },
      { onError: (error) => applyFieldErrors(error, form.setError, ['new_password']) },
    ),
  )

  return (
    <AuthCard title={AUTH.reset.title} description={AUTH.reset.description} footer={backToLogin}>
      <Form {...form}>
        <form onSubmit={onSubmit} noValidate className="flex min-w-0 flex-col gap-5">
          <FormField
            control={form.control}
            name="new_password"
            render={({ field }) => (
              <FormItem>
                <FormLabel required>{AUTH.fields.newPassword}</FormLabel>
                <FormControl>
                  <PasswordInput autoComplete="new-password" aria-required="true" {...field} />
                </FormControl>
                <FormDescription>{AUTH.fields.passwordHint}</FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormAlert error={reset.error} />
          <Button type="submit" variant="primary" className="w-full" loading={reset.isPending}>
            {AUTH.reset.submit}
          </Button>
        </form>
      </Form>
    </AuthCard>
  )
}
