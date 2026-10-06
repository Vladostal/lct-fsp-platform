import type { ContactKind, DiscloseField } from '@/client'
import { formatDate } from '@/lib/format'

export const CONTACT_KIND_LABELS: Record<ContactKind, string> = {
  email: 'Почта',
  phone: 'Телефон',
  telegram: 'Telegram',
  other: 'Другое',
}

export const FIELD_LABELS: Record<DiscloseField, string> = {
  email: 'почта',
  phone: 'телефон',
  telegram: 'Telegram',
  link: 'ссылка на профиль',
  fsp_details: 'подробности ФСП',
}

/** Дата освобождения слота для текстов работодателя. */
export function formatSlotRelease(releaseAt: string | null | undefined): string {
  return releaseAt ? formatDate(releaseAt) : 'позже'
}

/** Убирает двойную точку, когда сокращённая дата («13 окт.») стоит в конце предложения. */
export function tidy(text: string): string {
  return text.replace(/\.\.(?!\.)/g, '.')
}
