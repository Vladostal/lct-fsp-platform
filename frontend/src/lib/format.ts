/**
 * Форматы чисел, денег, дат и склонения (E §6.5). Все функции чистые; «сейчас» передаётся параметром
 * (по умолчанию — время сервиса из lib/time.ts), чтобы подписи сроков не зависели от часов браузера.
 */
import { serverNow } from '@/lib/time'

const NBSP = ' '
/** Короткое тире с неразрывными пробелами — для диапазонов. */
const RANGE_DASH = `${NBSP}–${NBSP}`

const numberFormat = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const decimalFormat = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const pluralRules = new Intl.PluralRules('ru')

/** Целое число с разрядами через неразрывный пробел: «180 000». */
export function formatNumber(value: number): string {
  // Intl ставит узкий неразрывный пробел (U+202F); в mono-шрифте он уже обычного, поэтому приводим к U+00A0.
  return numberFormat.format(value).replace(/[ \s]/g, NBSP)
}

/** Число с дробной частью через запятую: «0,8». */
export function formatDecimal(value: number): string {
  return decimalFormat.format(value).replace(/[ \s]/g, NBSP).replace('-', '−')
}

/** Сумма в рублях: «180 000 ₽». */
export function formatMoney(value: number): string {
  return `${formatNumber(value)}${NBSP}₽`
}

/**
 * Вилка: «180 000 – 240 000 ₽». `compact` — для узких ячеек, когда обе границы кратны 1000: «180–240 тыс. ₽»;
 * если хотя бы одна граница не кратна 1000, возвращается полный вид.
 */
export function formatSalaryRange(from: number, to: number, options: { compact?: boolean } = {}): string {
  if (options.compact && from % 1000 === 0 && to % 1000 === 0) {
    return `${formatNumber(from / 1000)}–${formatNumber(to / 1000)}${NBSP}тыс.${NBSP}₽`
  }
  return `${formatNumber(from)}${RANGE_DASH}${formatNumber(to)}${NBSP}₽`
}

/** Текстовая замена вилки для скринридера. */
export function salaryRangeAriaLabel(from: number, to: number): string {
  return `от ${formatNumber(from)} до ${formatNumber(to)} рублей в месяц`
}

export type PluralForms = readonly [one: string, few: string, many: string]

/** Формы слов, которые встречаются на нескольких экранах. */
export const PLURALS = {
  candidate: ['кандидат', 'кандидата', 'кандидатов'],
  day: ['день', 'дня', 'дней'],
  hour: ['час', 'часа', 'часов'],
  minute: ['минута', 'минуты', 'минут'],
  second: ['секунда', 'секунды', 'секунд'],
  task: ['задание', 'задания', 'заданий'],
  slot: ['слот', 'слота', 'слотов'],
  field: ['поле', 'поля', 'полей'],
  invitation: ['приглашение', 'приглашения', 'приглашений'],
  need: ['потребность', 'потребности', 'потребностей'],
  skill: ['навык', 'навыка', 'навыков'],
  profile: ['профиль', 'профиля', 'профилей'],
  test: ['тест', 'теста', 'тестов'],
} as const satisfies Record<string, PluralForms>

/** Форма слова для числа: plural(3, PLURALS.day) → «дня». */
export function plural(count: number, forms: PluralForms): string {
  const rule = pluralRules.select(Math.abs(count))
  if (rule === 'one') return forms[0]
  if (rule === 'few') return forms[1]
  return forms[2]
}

/** Число со словом: pluralize(3, PLURALS.day) → «3 дня». */
export function pluralize(count: number, forms: PluralForms): string {
  return `${formatNumber(count)}${NBSP}${plural(count, forms)}`
}

function toDate(value: string | Date): Date {
  return value instanceof Date ? value : new Date(value)
}

const dayMonth = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short' })
const dayMonthYear = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' })
const hourMinute = new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit' })

function cleanDate(text: string): string {
  // «12 окт. 2025 г.» → «12 окт. 2025»; пробелы внутри даты — неразрывные.
  return text.replace(/\s?г\.$/, '').replace(/\s/g, NBSP)
}

/** Дата: «12 окт.»; с годом, если год не текущий: «12 окт. 2025». Часовой пояс — браузера. */
export function formatDate(value: string | Date, now: Date = serverNow()): string {
  const date = toDate(value)
  if (Number.isNaN(date.getTime())) return ''
  const sameYear = date.getFullYear() === now.getFullYear()
  return cleanDate((sameYear ? dayMonth : dayMonthYear).format(date))
}

/** Время: «14:02». */
export function formatTime(value: string | Date): string {
  const date = toDate(value)
  if (Number.isNaN(date.getTime())) return ''
  return hourMinute.format(date)
}

/** Дата и время: «12 окт., 14:02». */
export function formatDateTime(value: string | Date, now: Date = serverNow()): string {
  const date = toDate(value)
  if (Number.isNaN(date.getTime())) return ''
  return `${formatDate(date, now)},${NBSP}${formatTime(date)}`
}

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

/**
 * Остаток срока словами: «3 дня»; меньше 48 ч — в часах, меньше часа — в минутах (E §6.5).
 * Для прошедшего срока возвращает null.
 */
export function formatRemaining(until: string | Date, now: Date = serverNow()): string | null {
  const ms = toDate(until).getTime() - now.getTime()
  if (Number.isNaN(ms) || ms <= 0) return null
  if (ms < HOUR) return pluralize(Math.max(1, Math.ceil(ms / MINUTE)), PLURALS.minute)
  if (ms < 2 * DAY) return pluralize(Math.floor(ms / HOUR), PLURALS.hour)
  return pluralize(Math.floor(ms / DAY), PLURALS.day)
}

/**
 * Срок с абсолютной датой и остатком: «ответить до 12 окт. · осталось 3 дня»; истёк — «срок истёк 12 окт.».
 * `verb` — действие в инфинитиве («ответить», «связаться»).
 */
export function formatDeadline(until: string | Date, verb = 'ответить', now: Date = serverNow()): string {
  const date = formatDate(until, now)
  const remaining = formatRemaining(until, now)
  if (remaining === null) return `срок истёк ${date}`
  return `${verb} до ${date} · осталось${NBSP}${remaining}`
}

/** Давность: «сегодня», «вчера», «12 дней назад». */
export function formatAgo(value: string | Date, now: Date = serverNow()): string {
  const days = Math.floor((now.getTime() - toDate(value).getTime()) / DAY)
  if (days <= 0) return 'сегодня'
  if (days === 1) return 'вчера'
  return `${pluralize(days, PLURALS.day)} назад`
}

/** Длительность в секундах для текстов лимитов: «45 с», «2 мин», «3 ч». */
export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return `0${NBSP}с`
  if (seconds < 60) return `${Math.ceil(seconds)}${NBSP}с`
  if (seconds < 3600) return `${Math.ceil(seconds / 60)}${NBSP}мин`
  return `${Math.ceil(seconds / 3600)}${NBSP}ч`
}

/** Таймер «мм:сс» (или «ч:мм:сс»); отрицательный остаток показывается как 00:00. */
export function formatTimer(msLeft: number): string {
  const total = Math.max(0, Math.floor(msLeft / 1000))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  const mm = String(minutes).padStart(2, '0')
  const ss = String(seconds).padStart(2, '0')
  return hours > 0 ? `${hours}:${mm}:${ss}` : `${mm}:${ss}`
}

/**
 * Перечисление: «A», «A и B», «A, B и C», «A, B, C и ещё {k}» (E §6.5).
 * `max` — сколько элементов назвать до «и ещё».
 */
export function formatList(items: readonly string[], max = 3): string {
  const list = items.filter(Boolean)
  if (list.length === 0) return ''
  if (list.length === 1) return list[0] as string
  if (list.length <= max) {
    return `${list.slice(0, -1).join(', ')} и ${list[list.length - 1]}`
  }
  return `${list.slice(0, max).join(', ')} и ещё${NBSP}${list.length - max}`
}

/** Имя кандидата для работодателя: раскрытое имя либо «Кандидат К-1042» (E §3.3). */
export function candidateTitle(displayName: string | null | undefined, publicCode: string): string {
  return displayName?.trim() || `Кандидат ${publicCode}`
}

/** Инициалы для аватара: по имени и фамилии, иначе — первая буква адреса. */
export function initials(source: string): string {
  const text = source.trim()
  if (!text) return '•'
  if (text.includes('@')) return (text[0] as string).toUpperCase()
  const parts = text.split(/\s+/).filter(Boolean)
  const first = parts[0]?.[0] ?? ''
  const second = parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? '') : ''
  return `${first}${second}`.toUpperCase()
}
