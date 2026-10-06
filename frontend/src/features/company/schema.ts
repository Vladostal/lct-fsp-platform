import type { CompanyUpdate, ContactKind } from '@/client'
import { COMPANY } from './content'

export type CompanyDraft = {
  name: string
  sphere: string
  description: string
  site: string
  city: string
  contactKind: ContactKind
  contactValue: string
}

export type CompanyErrors = Partial<Record<keyof CompanyDraft, string>>

export const EMPTY_DRAFT: CompanyDraft = {
  name: '',
  sphere: '',
  description: '',
  site: '',
  city: '',
  contactKind: 'email',
  contactValue: '',
}

const E = COMPANY.errors

/** Адрес без схемы дополняется `https://`. */
export function normalizeSite(site: string): string {
  const value = site.trim()
  if (!value) return ''
  return /^https?:\/\//i.test(value) ? value : `https://${value}`
}

function contactError(kind: ContactKind, raw: string): string | null {
  const value = raw.trim()
  if (kind === 'email') return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(value) ? null : E.email
  if (kind === 'phone') {
    const digits = value.replace(/\D/g, '')
    return /^[+\d\s()-]+$/.test(value) && digits.length >= 8 && digits.length <= 15 ? null : E.phone
  }
  if (kind === 'telegram') return /^@[A-Za-z0-9_]{5,32}$/.test(value) ? null : E.telegram
  return value.length >= 3 && value.length <= 200 ? null : E.other
}

export function validateCompany(d: CompanyDraft): CompanyErrors {
  const errors: CompanyErrors = {}
  const inRange = (s: string, min: number, max: number) => s.trim().length >= min && s.trim().length <= max
  if (!inRange(d.name, 2, 100)) errors.name = E.nameLen
  if (!inRange(d.sphere, 2, 100)) errors.sphere = E.sphereLen
  if (!inRange(d.description, 50, 2000)) errors.description = E.descriptionLen
  const site = normalizeSite(d.site)
  if (site) {
    if (site.length > 200) errors.site = E.siteLen
    else if (!/^https?:\/\/[^\s/]+\.[^\s/]{2,}/i.test(site)) errors.site = E.siteFormat
  }
  if (d.city.trim().length > 80) errors.city = E.cityLen
  const c = contactError(d.contactKind, d.contactValue)
  if (c) errors.contactValue = c
  return errors
}

export function toUpdate(d: CompanyDraft): CompanyUpdate {
  return {
    name: d.name.trim(),
    sphere: d.sphere.trim(),
    description: d.description.trim(),
    site: normalizeSite(d.site) || null,
    city: d.city.trim() || null,
    contact_method: { kind: d.contactKind, value: d.contactValue.trim() },
  }
}
