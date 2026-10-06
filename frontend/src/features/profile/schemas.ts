/** Проверки и нормализация полей профиля (zod; правила — приложение E, C1, и Арх. 9). */
import { z } from 'zod'
import type {
  CandidateProfileUpdate,
  CandidateProfileView,
  ConditionsUpdate,
  ConditionsView,
  WorkFormat,
} from '@/client'
import type { TagValue } from '@/components/app'
import { PROFILE } from './content'

const V = PROFILE.validation

export const LIMITS = { roles: 5, stack: 30, soft: 10, about: 1000, customTag: 40 } as const
export const WORK_FORMATS: readonly WorkFormat[] = ['office', 'hybrid', 'remote']

const NAME_RE = /^[\p{L}\p{M}\s'’-]+$/u

/** Телефон: пробелы, скобки и дефисы убираются, `8XXXXXXXXXX` → `+7XXXXXXXXXX`. Пустая строка — `null`. */
export function normalizePhone(raw: string): string | null {
  const compact = raw.replace(/[\s()-]/g, '')
  if (!compact) return null
  if (/^8\d{10}$/.test(compact)) return `+7${compact.slice(1)}`
  return compact
}

export function isPhone(value: string): boolean {
  return /^\+?\d{8,15}$/.test(value)
}

/** Telegram: `https://t.me/` и `@` отбрасываются, затем добавляется `@`. */
export function normalizeTelegram(raw: string): string | null {
  const bare = raw
    .trim()
    .replace(/^(https?:\/\/)?(t\.me\/)/i, '')
    .replace(/^@+/, '')
  return bare ? `@${bare}` : null
}

export function isTelegram(value: string): boolean {
  return /^@[A-Za-z0-9_]{5,32}$/.test(value)
}

/** Ссылка без схемы получает `https://`. */
export function normalizeLink(raw: string): string | null {
  const text = raw.trim()
  if (!text) return null
  return /^[a-z][a-z0-9+.-]*:\/\//i.test(text) ? text : `https://${text}`
}

export function isLink(value: string): boolean {
  if (value.length > 200) return false
  try {
    const url = new URL(value)
    return (url.protocol === 'https:' || url.protocol === 'http:') && url.hostname.includes('.')
  } catch {
    return false
  }
}

const tagSchema = z.object({ code: z.string().nullable(), title: z.string() })

const optionalText = (max: number, message: string) => z.string().trim().max(max, message)

const nameSchema = z.string().trim().min(1, V.required).max(60, V.name).regex(NAME_RE, V.name)
const optionalNameSchema = z
  .string()
  .trim()
  .max(60, V.name)
  .refine((value) => value === '' || NAME_RE.test(value), V.name)

export const profileFormSchema = z.object({
  last_name: nameSchema,
  first_name: nameSchema,
  middle_name: optionalNameSchema,
  city: optionalText(80, V.city),
  phone: z
    .string()
    .trim()
    .refine((value) => value === '' || isPhone(normalizePhone(value) ?? ''), V.phone),
  telegram: z
    .string()
    .trim()
    .refine((value) => value === '' || isTelegram(normalizeTelegram(value) ?? ''), V.telegram),
  link: z
    .string()
    .trim()
    .refine((value) => value === '' || isLink(normalizeLink(value) ?? ''), V.link),
  experience_years: z
    .string()
    .trim()
    .refine((value) => {
      if (value === '') return true
      const number = Number(value.replace(',', '.'))
      return Number.isFinite(number) && number >= 0 && number <= 40
    }, V.experience),
  roles: z.array(tagSchema).max(LIMITS.roles),
  stack: z.array(tagSchema).max(LIMITS.stack),
  soft: z.array(tagSchema).max(LIMITS.soft),
  about: z.string().max(LIMITS.about, V.about),
  work_formats: z.array(z.enum(['office', 'hybrid', 'remote'])).min(1, V.formats),
  relocation_ready: z.boolean(),
  min_salary: z.number().nullable(),
})

export type ProfileFormValues = z.infer<typeof profileFormSchema>

/** Имена полей формы → ключи `ResumeParseResult.fields`. */
export const RESUME_KEYS: Record<string, keyof ProfileFormValues> = {
  last_name: 'last_name',
  first_name: 'first_name',
  middle_name: 'middle_name',
  city: 'city',
  phone: 'phone',
  telegram: 'telegram',
  link: 'link',
  experience_years: 'experience_years',
  roles: 'roles',
  declared_skills: 'stack',
  soft_skills: 'soft',
  about: 'about',
}

/** Обратное соответствие: поле формы → ключ резюме (для `resume_accepted_fields`). */
export const RESUME_KEY_BY_FIELD: Partial<Record<keyof ProfileFormValues, string>> = Object.fromEntries(
  Object.entries(RESUME_KEYS).map(([key, field]) => [field, key]),
)

export function defaultValues(profile: CandidateProfileView, conditions: ConditionsView): ProfileFormValues {
  const tag = (code: string | null, title: string): TagValue => ({ code, title })
  return {
    last_name: profile.last_name ?? '',
    first_name: profile.first_name ?? '',
    middle_name: profile.middle_name ?? '',
    city: profile.city ?? '',
    phone: profile.phone ?? '',
    telegram: profile.telegram ?? '',
    link: profile.link ?? '',
    experience_years: profile.experience_years == null ? '' : String(profile.experience_years),
    roles: profile.roles.map((role) => tag(role.code, role.title)),
    stack: profile.declared_skills.filter((skill) => skill.kind !== 'soft').map((s) => tag(s.code, s.title)),
    soft: profile.declared_skills.filter((skill) => skill.kind === 'soft').map((s) => tag(s.code, s.title)),
    about: profile.about ?? '',
    work_formats: conditions.work_formats.length ? [...conditions.work_formats] : [...WORK_FORMATS],
    relocation_ready: conditions.relocation_ready,
    min_salary: conditions.min_salary,
  }
}

const orNull = (value: string): string | null => (value.trim() === '' ? null : value.trim())

export function toProfileUpdate(
  values: ProfileFormValues,
  resume: { uploadId: string; acceptedFields: string[] } | null,
): CandidateProfileUpdate {
  const skill = (tag: TagValue) => (tag.code ? { code: tag.code } : { custom_label: tag.title })
  const years = values.experience_years.trim()
  return {
    last_name: values.last_name.trim(),
    first_name: values.first_name.trim(),
    middle_name: orNull(values.middle_name),
    city: orNull(values.city),
    phone: normalizePhone(values.phone),
    telegram: normalizeTelegram(values.telegram),
    link: normalizeLink(values.link),
    experience_years: years === '' ? null : Number(years.replace(',', '.')),
    roles: values.roles.flatMap((role) => (role.code ? [role.code] : [])),
    declared_skills: [...values.stack, ...values.soft].map(skill),
    about: orNull(values.about),
    ...(resume ? { resume_upload_id: resume.uploadId, resume_accepted_fields: resume.acceptedFields } : {}),
  }
}

export function toConditionsUpdate(values: ProfileFormValues): ConditionsUpdate {
  return {
    work_formats: values.work_formats,
    relocation_ready: values.relocation_ready,
    min_salary: values.min_salary,
  }
}
