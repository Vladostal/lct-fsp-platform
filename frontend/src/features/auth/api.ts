/**
 * Функции-обёртки над эндпоинтами `identity` (Арх. 9.4). Экраны входа вызывают только их.
 * Пока в `src/client` нет операций настоящей схемы, запросы идут через `api` из lib/api.ts;
 * после выпуска клиента здесь меняются только тела функций — экраны и хуки остаются как есть.
 */
import type { LoginRequest, MeView, SignupRequest } from '@/client'
import { api } from '@/lib/api'

export type VerifyEmailBody = { token: string; password?: string }
export type ChangePasswordBody = { current_password: string; new_password: string }
export type ResetPasswordBody = { token: string; new_password: string }

/** Регистрация: ответ 202 одинаков для нового и занятого адреса. */
export function signup(body: SignupRequest): Promise<void> {
  return api.post('/auth/signup', body)
}

/** Повторная отправка письма подтверждения: всегда 202. */
export function resendVerification(email: string): Promise<void> {
  return api.post('/auth/resend-verification', { email })
}

/** Подтверждение адреса: открывает сессию. 409 `password_required` — нужен пароль заявки (Арх. 10.2). */
export function verifyEmail(body: VerifyEmailBody): Promise<MeView> {
  return api.post<MeView>('/auth/verify-email', body)
}

export function login(body: LoginRequest): Promise<MeView> {
  return api.post<MeView>('/auth/login', body)
}

export function logout(): Promise<void> {
  return api.post('/auth/logout')
}

/** Смена пароля: остальные сессии пользователя удаляются. */
export function changePassword(body: ChangePasswordBody): Promise<void> {
  return api.post('/auth/password', body)
}

/** Запрос ссылки сброса: ответ 202 одинаков для любого адреса. */
export function forgotPassword(email: string): Promise<void> {
  return api.post('/auth/password/forgot', { email })
}

/** Новый пароль по ссылке из письма: все сессии пользователя удаляются. */
export function resetPassword(body: ResetPasswordBody): Promise<void> {
  return api.post('/auth/password/reset', body)
}

/** Отзыв согласия на обработку и немедленное удаление аккаунта со всеми данными (Арх. 10.5). */
export function deleteAccount(password: string): Promise<void> {
  return api.post('/auth/account/delete', { password })
}
