import { zodResolver } from '@hookform/resolvers/zod'
import { LogOut, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import type { MeView } from '@/client'
import { DemoChip, PageHeader, PasswordInput } from '@/components/app'
import { Alert, AlertDescription } from '@/components/ui/alert'
import {
  AlertDialog,
  AlertDialogBody,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Form, FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form'
import { ROLE_LABELS } from '@/content/common'
import { applyFieldErrors, hasCode } from '@/lib/api'
import { AUTH, deleteDialogDelay, REREGISTER_COOLDOWN_DAYS_DEFAULT } from '../content'
import { useChangePassword, useDeleteAccount, useLogout } from '../hooks'
import {
  type ChangePasswordValues,
  changePasswordSchema,
  type PasswordOnlyValues,
  passwordOnlySchema,
} from '../schemas'
import { FormAlert } from './form-alert'

export type AccountSettingsProps = {
  me: MeView
  /** Срок карантина адреса после удаления, дней (из `catalog.limits`, если сервер его отдаёт). */
  reregisterCooldownDays?: number
}

/**
 * C14, E10. Аккаунт: адрес (только чтение), смена пароля, выход и «Отозвать согласие и удалить данные»
 * с подтверждением паролем (Арх. 10.5). У демо-аккаунта смена пароля и удаление неактивны с подписью
 * «демо-аккаунт»: пароль у него публичный.
 */
export function AccountSettings({
  me,
  reregisterCooldownDays = REREGISTER_COOLDOWN_DAYS_DEFAULT,
}: AccountSettingsProps) {
  const A = AUTH.account
  const logout = useLogout()
  const [deleteOpen, setDeleteOpen] = useState(false)

  return (
    <div className="mx-auto flex w-full max-w-[880px] min-w-0 flex-col gap-6">
      <PageHeader title={A.title} description={A.description} />

      {me.is_demo ? (
        <Alert variant="info">
          <AlertDescription>{A.demoReadonlyText}</AlertDescription>
        </Alert>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>{A.emailCard}</CardTitle>
          <CardDescription>{A.emailNote}</CardDescription>
        </CardHeader>
        <dl className="grid min-w-0 gap-x-8 gap-y-4 sm:grid-cols-[minmax(0,1fr)_auto]">
          <div className="flex min-w-0 flex-col gap-1">
            <dt className="type-sm text-ink-muted">{A.emailLabel}</dt>
            <dd className="type-body font-medium text-ink [overflow-wrap:anywhere]">{me.email}</dd>
          </div>
          <div className="flex min-w-0 flex-col gap-1">
            <dt className="type-sm text-ink-muted">{A.roleLabel}</dt>
            <dd className="type-body flex flex-wrap items-center gap-2 font-medium text-ink">
              {ROLE_LABELS[me.role]}
              {me.is_demo ? <DemoChip /> : null}
            </dd>
          </div>
        </dl>
      </Card>

      <ChangePasswordCard disabled={me.is_demo} />

      <Card>
        <CardHeader>
          <CardTitle>{A.logoutCard}</CardTitle>
          <CardDescription>{A.logoutText}</CardDescription>
        </CardHeader>
        <div className="flex">
          <Button variant="secondary" onClick={() => logout.mutate()} loading={logout.isPending}>
            <LogOut aria-hidden="true" />
            {A.logout}
          </Button>
        </div>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{A.deleteCard}</CardTitle>
          <CardDescription>{A.deleteText}</CardDescription>
        </CardHeader>
        <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
          {/*
            Подпись задана архитектурой и длиннее 32 знаков: на узком экране кнопка обходится без иконки и
            набирается кеглем 14, чтобы текст остался в одну строку внутри кнопки.
          */}
          <Button
            variant="destructive"
            disabled={me.is_demo}
            onClick={() => setDeleteOpen(true)}
            className="max-[479px]:w-full max-[479px]:px-4 max-[479px]:text-sm"
          >
            <Trash2 aria-hidden="true" className="max-[479px]:hidden" />
            {A.deleteAction}
          </Button>
          {me.is_demo ? <span className="type-sm text-ink-muted">{A.demoReadonly}</span> : null}
        </div>
      </Card>

      <DeleteAccountDialog open={deleteOpen} onOpenChange={setDeleteOpen} days={reregisterCooldownDays} />
    </div>
  )
}

function ChangePasswordCard({ disabled }: { disabled: boolean }) {
  const A = AUTH.account
  const change = useChangePassword()
  const form = useForm<ChangePasswordValues>({
    resolver: zodResolver(changePasswordSchema),
    defaultValues: { current_password: '', new_password: '' },
  })

  const onSubmit = form.handleSubmit((values) => {
    change.mutate(values, {
      onSuccess: () => form.reset(),
      onError: (error) => {
        const applied = applyFieldErrors(error, form.setError, ['current_password', 'new_password'])
        // Сервер может прислать код без списка полей — привязываем его к полю текущего пароля сами.
        if (applied === 0 && hasCode(error, 'current_password_invalid')) {
          form.setError('current_password', { message: 'Текущий пароль не подошёл' }, { shouldFocus: true })
        }
      },
    })
  })

  const fieldError = hasCode(change.error, 'current_password_invalid', 'validation_error')

  return (
    <Card>
      <CardHeader>
        <CardTitle>{A.passwordCard}</CardTitle>
        <CardDescription>{A.passwordNote}</CardDescription>
      </CardHeader>
      <Form {...form}>
        <form onSubmit={onSubmit} noValidate className="flex min-w-0 flex-col gap-5">
          <fieldset disabled={disabled} className="grid min-w-0 gap-5 sm:grid-cols-2">
            <FormField
              control={form.control}
              name="current_password"
              render={({ field }) => (
                <FormItem>
                  <FormLabel required>{AUTH.fields.currentPassword}</FormLabel>
                  <FormControl>
                    <PasswordInput autoComplete="current-password" aria-required="true" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
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
          </fieldset>
          {change.isSuccess ? (
            <Alert variant="success" live>
              <AlertDescription>{A.passwordDone}</AlertDescription>
            </Alert>
          ) : null}
          {fieldError ? null : <FormAlert error={change.error} />}
          <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
            <Button
              type="submit"
              variant="primary"
              loading={change.isPending}
              disabled={disabled}
              className="max-[479px]:w-full"
            >
              {A.passwordSubmit}
            </Button>
            {disabled ? <span className="type-sm text-ink-muted">{A.demoReadonly}</span> : null}
          </div>
        </form>
      </Form>
    </Card>
  )
}

function DeleteAccountDialog({
  open,
  onOpenChange,
  days,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  days: number
}) {
  const A = AUTH.account
  const remove = useDeleteAccount()
  const form = useForm<PasswordOnlyValues>({
    resolver: zodResolver(passwordOnlySchema),
    defaultValues: { password: '' },
  })

  const onSubmit = form.handleSubmit((values) => {
    remove.mutate(values.password, {
      onError: (error) => {
        if (hasCode(error, 'current_password_invalid')) {
          form.setError('password', { message: 'Пароль не подошёл' }, { shouldFocus: true })
        }
      },
    })
  })

  const passwordError = hasCode(remove.error, 'current_password_invalid')

  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          form.reset()
          remove.reset()
        }
        onOpenChange(next)
      }}
    >
      <AlertDialogContent>
        <Form {...form}>
          <form onSubmit={onSubmit} noValidate className="flex min-h-0 flex-1 flex-col">
            <AlertDialogHeader>
              <AlertDialogTitle>{A.deleteDialogTitle}</AlertDialogTitle>
              <AlertDialogDescription>{A.deleteText}</AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogBody>
              {/* Последствие названо до нажатия, числом (Арх. 11.7, п. 4). */}
              <Alert variant="warning">
                <AlertDescription>
                  <p>{deleteDialogDelay(days)}</p>
                  <p>{A.deleteDialogKept}</p>
                </AlertDescription>
              </Alert>
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
              {passwordError ? null : <FormAlert error={remove.error} />}
            </AlertDialogBody>
            <AlertDialogFooter>
              <AlertDialogCancel type="button">{A.deleteCancel}</AlertDialogCancel>
              <Button type="submit" variant="destructive" loading={remove.isPending}>
                {A.deleteConfirm}
              </Button>
            </AlertDialogFooter>
          </form>
        </Form>
      </AlertDialogContent>
    </AlertDialog>
  )
}
