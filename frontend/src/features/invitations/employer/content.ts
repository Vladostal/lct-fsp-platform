/** Подписи экрана «Приглашения» работодателя: одно-два слова, смысл несут форма, цвет и число. */
export const DASHBOARD = {
  title: 'Итоги приглашений',
  funnel: 'Воронка',
  delivered: 'Доставлено',
  viewed: 'Просмотрено',
  accepted: 'Принято',
  conversion: 'конверсия',
  outcomes: 'Исходы',
  of: 'из',
  waiting: 'Ждут',
  declined: 'Отклонено',
  expired: 'Истекло',
  withdrawn: 'Отозвано',
  notDelivered: 'Не доставлено',
  median: 'медиана ответа',
  hours: 'ч',
  reasons: 'Отказы',
  none: '—',
} as const

export const LIST = {
  filters: {
    all: 'Все',
    awaiting: 'Ждут ответа',
    accepted: 'Приняты',
    declined: 'Отклонены',
    expired: 'Истекли',
    withdrawn: 'Отозваны',
    bounced: 'Не доставлены',
  },
  columns: { candidate: 'Кандидат', offer: 'Предложение', status: 'Статус и срок', updated: 'Обновлено' },
  answerBy: 'Ответ',
  until: 'до',
  bounced: 'Условия не совпали',
} as const
