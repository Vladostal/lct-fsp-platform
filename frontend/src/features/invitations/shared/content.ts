import type { ContactKind, DiscloseField } from '@/client'

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

/** Убирает двойную точку, когда сокращённая дата («13 окт.») стоит в конце предложения. */
export function tidy(text: string): string {
  return text.replace(/\.\.(?!\.)/g, '.')
}
