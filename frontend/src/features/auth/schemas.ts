/** Проверки форм входа и регистрации (zod; правила — Арх. 10.1, приложение E §2.1 P2). */
import { z } from 'zod'
import { AUTH } from './content'

const V = AUTH.validation

/** E-mail: пробелы по краям обрезаются, регистр — нижний, не длиннее 254 знаков. */
export const emailSchema = z
  .string()
  .trim()
  .toLowerCase()
  .min(1, V.emailRequired)
  .max(254, V.emailTooLong)
  .regex(/^[^\s@]+@[^\s@]+\.[^\s@]+$/, V.emailFormat)

/** Новый пароль: 8–128 знаков. */
export const newPasswordSchema = z.string().min(1, V.passwordRequired).min(8, V.passwordShort).max(128, V.passwordLong)

/** Пароль при входе: правила длины не раскрываем, только «не пусто». */
export const currentPasswordSchema = z.string().min(1, V.passwordRequired).max(128, V.passwordLong)

export const roleSchema = z.enum(['candidate', 'employer'])

export const signupSchema = z.object({
  role: roleSchema,
  email: emailSchema,
  password: newPasswordSchema,
  consent_processing: z.boolean().refine((value) => value, V.consentRequired),
  is_adult: z.boolean().refine((value) => value, V.adultRequired),
})
export type SignupValues = z.infer<typeof signupSchema>

export const loginSchema = z.object({
  email: emailSchema,
  password: currentPasswordSchema,
})
export type LoginValues = z.infer<typeof loginSchema>

export const emailOnlySchema = z.object({ email: emailSchema })
export type EmailOnlyValues = z.infer<typeof emailOnlySchema>

export const passwordOnlySchema = z.object({ password: currentPasswordSchema })
export type PasswordOnlyValues = z.infer<typeof passwordOnlySchema>

export const resetPasswordSchema = z.object({ new_password: newPasswordSchema })
export type ResetPasswordValues = z.infer<typeof resetPasswordSchema>

export const changePasswordSchema = z
  .object({
    current_password: currentPasswordSchema,
    new_password: newPasswordSchema,
  })
  .refine((value) => value.current_password !== value.new_password, {
    path: ['new_password'],
    message: V.samePassword,
  })
export type ChangePasswordValues = z.infer<typeof changePasswordSchema>

/** Параметры адреса экранов входа (`validateSearch`). */
export const signupSearchSchema = z.object({ role: roleSchema.optional().catch(undefined) })
export const checkEmailSearchSchema = z.object({ email: z.string().optional().catch(undefined) })
export const tokenSearchSchema = z.object({ token: z.string().optional().catch(undefined) })
export const loginSearchSchema = z.object({ next: z.string().optional().catch(undefined) })
