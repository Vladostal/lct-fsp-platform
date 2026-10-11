import { zodResolver } from '@hookform/resolvers/zod'
import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { useForm } from 'react-hook-form'
import type { Role } from '@/client'
import { ConsentCheckbox, PasswordInput } from '@/components/app'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Form, FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { ROLE_LABELS } from '@/content/common'
import { applyFieldErrors, hasCode } from '@/lib/api'
import { legalDocQuery } from '@/lib/query'
import { AUTH } from '../content'
import { useSignup } from '../hooks'
import { rememberPendingEmail } from '../pending-email'
import { type SignupValues, signupSchema } from '../schemas'
import { AuthCard } from './auth-card'
import { FormAlert } from './form-alert'

const FIELDS = ['role', 'email', 'password', 'consent_processing', 'is_adult'] as const

/**
 * P2. Регистрация. Ответ сервера одинаков для нового и занятого адреса, поэтому после отправки всегда
 * открывается «Проверьте почту»: существование адреса не раскрывается. Версия текста согласия берётся
 * из `GET /legal/processing` и уходит в запросе (`consent_version`).
 */
export function SignupForm({ initialRole }: { initialRole?: Role }) {
  const navigate = useNavigate()
  const signup = useSignup()
  const consentDoc = useQuery(legalDocQuery('processing'))

  const form = useForm<SignupValues>({
    resolver: zodResolver(signupSchema),
    // Проверка — при отправке, а не при потере фокуса: сообщение под полем, появившись в момент нажатия на
    // следующий элемент, сдвигало бы форму, и нажатие приходилось бы мимо.
    defaultValues: {
      role: initialRole ?? 'candidate',
      email: '',
      password: '',
      consent_processing: false,
      is_adult: false,
    },
  })

  const role = form.watch('role')
  const consents = form.watch(['consent_processing', 'is_adult'])
  const bothChecked = consents.every(Boolean)
  const consentVersion = consentDoc.data?.version
  const canSubmit = bothChecked && Boolean(consentVersion)

  const onSubmit = form.handleSubmit((values) => {
    if (!consentVersion) return
    signup.mutate(
      {
        email: values.email,
        password: values.password,
        role: values.role,
        consent_processing: true,
        consent_version: consentVersion,
        is_adult: true,
      },
      {
        onSuccess: () => {
          rememberPendingEmail(values.email)
          return navigate({ to: '/signup/check-email' })
        },
        onError: (error) => applyFieldErrors(error, form.setError, FIELDS),
      },
    )
  })

  const fieldErrorsShown = hasCode(signup.error, 'validation_error') && Object.keys(form.formState.errors).length > 0

  return (
    <AuthCard
      title={AUTH.signup.title}
      description={AUTH.signup.description}
      footer={
        <>
          <span>{AUTH.signup.haveAccount}</span>
          <Link to="/login" className="text-link inline-flex min-h-11 items-center">
            {AUTH.signup.login}
          </Link>
        </>
      }
    >
      <Form {...form}>
        <form onSubmit={onSubmit} noValidate className="flex min-w-0 flex-col gap-4">
          <FormField
            control={form.control}
            name="role"
            render={({ field }) => (
              <FormItem>
                <FormLabel id="signup-role-label">{AUTH.signup.roleLabel}</FormLabel>
                <ToggleGroup
                  type="single"
                  aria-labelledby="signup-role-label"
                  value={field.value}
                  // Роль обязательна: повторное нажатие на выбранный вариант его не снимает.
                  onValueChange={(value) => value && field.onChange(value)}
                  className="grid grid-cols-1 gap-2 min-[400px]:grid-cols-2"
                >
                  {(['candidate', 'employer'] as const).map((value) => (
                    <ToggleGroupItem key={value} value={value} className="w-full justify-center gap-2">
                      {ROLE_LABELS[value]}
                    </ToggleGroupItem>
                  ))}
                </ToggleGroup>
                <p className="type-caption text-ink-muted" aria-live="polite">
                  {AUTH.signup.roleHint[role]}
                </p>
              </FormItem>
            )}
          />

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
                <FormLabel required>{AUTH.fields.password}</FormLabel>
                <FormControl>
                  <PasswordInput autoComplete="new-password" aria-required="true" {...field} />
                </FormControl>
                <FormDescription>{AUTH.fields.passwordHint}</FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />

          <div className="flex min-w-0 flex-col gap-3">
            <FormField
              control={form.control}
              name="consent_processing"
              render={({ field, fieldState }) => (
                <ConsentCheckbox
                  checked={field.value}
                  onCheckedChange={field.onChange}
                  name={field.name}
                  href="/legal/processing"
                  linkLabel={AUTH.signup.consentLink}
                  version={consentVersion}
                  error={fieldState.error?.message}
                  required
                >
                  {AUTH.signup.consent}
                </ConsentCheckbox>
              )}
            />
            <FormField
              control={form.control}
              name="is_adult"
              render={({ field, fieldState }) => (
                <ConsentCheckbox
                  checked={field.value}
                  onCheckedChange={field.onChange}
                  name={field.name}
                  error={fieldState.error?.message}
                  required
                >
                  {AUTH.signup.adult}
                </ConsentCheckbox>
              )}
            />
          </div>

          {consentDoc.isError ? (
            <Alert variant="warning">
              <AlertDescription>
                <p>{AUTH.signup.consentUnavailable}</p>
                <Button type="button" variant="link" onClick={() => consentDoc.refetch()}>
                  Повторить
                </Button>
              </AlertDescription>
            </Alert>
          ) : null}

          {fieldErrorsShown ? null : <FormAlert error={signup.error} />}

          <div className="flex min-w-0 flex-col gap-2">
            <Button
              type="submit"
              variant="primary"
              className="w-full"
              // Текст согласия ещё грузится: без его версии отправка невозможна, показываем ожидание, а не тишину.
              loading={signup.isPending || (bothChecked && consentDoc.isPending)}
              aria-disabled={!canSubmit || undefined}
              aria-describedby={canSubmit ? undefined : 'signup-disabled-reason'}
            >
              {AUTH.signup.submit}
            </Button>
            {/* Причина недоступности кнопки видна текстом, а не только в подсказке (E §7). */}
            {bothChecked ? null : (
              <p id="signup-disabled-reason" className="type-sm text-center text-ink-muted">
                {AUTH.signup.disabledReason}
              </p>
            )}
          </div>
        </form>
      </Form>
    </AuthCard>
  )
}
