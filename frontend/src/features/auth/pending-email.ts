/**
 * Адрес незавершённой регистрации для экрана «Проверьте почту».
 *
 * Хранится в `sessionStorage` вкладки, а не в адресной строке: адрес почты — персональные данные, и в параметре
 * запроса он попадал бы в историю браузера и журналы веб-сервера. Хранилище может быть недоступно (приватный
 * режим, запрет в настройках) — тогда экран вернёт на регистрацию.
 */
const KEY = 'signup.pendingEmail'

export function rememberPendingEmail(email: string): void {
  try {
    sessionStorage.setItem(KEY, email)
  } catch {
    // хранилище недоступно: экран «Проверьте почту» вернёт на форму регистрации
  }
}

export function pendingEmail(): string | undefined {
  try {
    return sessionStorage.getItem(KEY) ?? undefined
  } catch {
    return undefined
  }
}
