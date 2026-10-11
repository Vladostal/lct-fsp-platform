import type { InvitationEmployerBrief, InvitationEmployerView } from '@/client'
import { formatDate, formatDateTime } from '@/lib/format'

/** Строка «срок · исход» для семи статусов (E §2.3, E7). */
export function statusLine(inv: InvitationEmployerBrief | InvitationEmployerView): string {
  const timeline = 'timeline' in inv ? inv.timeline : []
  switch (inv.status) {
    case 'sent':
      return `Ответ до ${formatDateTime(inv.expires_at)} · ещё не просмотрено`
    case 'viewed': {
      const at = timeline.find((e) => e.code === 'viewed')?.at
      return `Ответ до ${formatDateTime(inv.expires_at)} · просмотрено${at ? ` ${formatDateTime(at)}` : ''}`
    }
    case 'accepted':
      return `Принято ${formatDate(inv.updated_at)}`
    case 'declined':
      return `Отклонено ${formatDate(inv.updated_at)}`
    case 'expired':
      return `Срок истёк ${formatDate(inv.expires_at)}`
    case 'withdrawn':
      return `Отозвано ${formatDate(inv.updated_at)}`
    case 'bounced':
      return 'Условия не совпали с ожиданиями кандидата'
  }
}
