import type { InvitationEmployerBrief, InvitationEmployerView } from '@/client'
import { formatDate, formatDateTime } from '@/lib/format'
import { formatSlotRelease } from '../shared'

/** Строка «слот · срок · исход» для семи статусов (E §2.3, E7). */
export function slotLine(inv: InvitationEmployerBrief | InvitationEmployerView): string {
  const timeline = 'timeline' in inv ? inv.timeline : []
  switch (inv.status) {
    case 'sent':
      return `Слот занят · ответ до ${formatDateTime(inv.expires_at)} · ещё не просмотрено`
    case 'viewed': {
      const at = timeline.find((e) => e.code === 'viewed')?.at
      return `Слот занят · ответ до ${formatDateTime(inv.expires_at)} · просмотрено${at ? ` ${formatDateTime(at)}` : ''}`
    }
    case 'accepted':
      return `Слот свободен · принято ${formatDate(inv.updated_at)}`
    case 'declined':
      return `Слот свободен · отклонено ${formatDate(inv.updated_at)}`
    case 'expired':
      return `Слот возвращён · срок истёк ${formatDate(inv.expires_at)}`
    case 'withdrawn':
      return `Слот занят до ${formatSlotRelease(inv.slot.release_at)} · отозвано ${formatDate(inv.updated_at)}`
    case 'bounced':
      return `Слот занят до ${formatSlotRelease(inv.slot.release_at)} · не доставлено`
  }
}
