import { z } from 'zod'

const flag = z.preprocess(
  (v) => (v === true || v === 'true' || v === 1 || v === '1' ? true : undefined),
  z.boolean().optional(),
)

/** E4: состояние экрана — в адресе (Арх. 11.4). */
export const needSearchSchema = z.object({
  tab: z.enum(['shortlist', 'invitations', 'description']).optional().catch(undefined),
  snapshot: z.string().optional().catch(undefined),
  view: z.enum(['all', 'not_invited', 'pinned', 'fsp']).optional().catch(undefined),
  category: z.string().optional().catch(undefined),
  candidate: z.string().optional().catch(undefined),
  invite: flag.catch(undefined),
  revises: z.string().optional().catch(undefined),
})
export type NeedSearch = z.infer<typeof needSearchSchema>

/** E8: фильтры банка в адресе. */
export const bankSearchSchema = z.object({
  category: z.string().optional().catch(undefined),
  specialization: z.string().optional().catch(undefined),
  grade: z.string().optional().catch(undefined),
  skills: z.string().optional().catch(undefined),
  confirmed: flag.catch(undefined),
  fsp: flag.catch(undefined),
  code: z.string().optional().catch(undefined),
  candidate: z.string().optional().catch(undefined),
  invite: flag.catch(undefined),
})
export type BankSearch = z.infer<typeof bankSearchSchema>

/** Карточка кандидата по прямой ссылке. */
export const cardSearchSchema = z.object({
  need: z.string().optional().catch(undefined),
  snapshot: z.string().optional().catch(undefined),
  invite: flag.catch(undefined),
  revises: z.string().optional().catch(undefined),
})
