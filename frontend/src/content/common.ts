/**
 * Общие строки интерфейса: подписи навигации, запасные подписи статусов (E §6.2), подписи доказательств.
 * Строки доменов лежат в `features/<домен>/content.ts`; тексты ошибок — в `content/errors.ts`.
 * Подписи, которые сервер отдаёт готовыми (`*_label`, `text`, `headline`), выводятся как пришли —
 * словари ниже нужны только как запасной вариант.
 */
import type { EvidenceKind, FitBand, InvitationStatus, Role, TestOutcome, VisibilityState, WorkFormat } from '@/client'

export const COMMON = {
  skipToContent: 'К содержимому',
  retry: 'Повторить',
  back: 'Назад',
  close: 'Закрыть',
  cancel: 'Отмена',
  menu: 'Меню',
  login: 'Войти',
  logout: 'Выйти',
  signup: 'Зарегистрироваться',
  toCabinet: 'В кабинет',
  loading: 'Загрузка…',
  slow: 'Занимает больше обычного…',
  copied: 'Скопировано',
  copy: 'Скопировать',
  newTab: 'откроется в новой вкладке',
  demoChip: 'демо',
  showMore: 'Показать полностью',
  showLess: 'Свернуть',
  mainNav: 'Основная навигация',
  settingsNav: 'Настройки',
  userMenu: 'Меню пользователя',
  sessionExpired: 'Сессия истекла. Войдите снова',
  demoRestarted: 'Сценарий перезапущен — войдите снова',
  wrongRole: {
    candidate: 'Этот раздел доступен только кандидатам',
    employer: 'Этот раздел доступен только работодателям',
  } satisfies Record<Role, string>,
  notFound: {
    title: 'Здесь ничего нет',
    text: 'Ссылка устарела или объект удалён.',
    action: 'На первый экран',
  },
  loadError: {
    title: 'Не удалось загрузить данные',
    text: 'Проверьте соединение и повторите.',
  },
  forbidden: {
    title: 'Нет доступа к этому разделу',
    action: 'На первый экран',
  },
  stub: {
    eyebrow: 'экран в работе',
    text: 'Экран появится в одной из ближайших сборок. Каркас, навигация и общие компоненты уже работают.',
  },
} as const

export const ROLE_LABELS: Record<Role, string> = {
  candidate: 'ИТ-специалист',
  employer: 'Работодатель',
}

/** Навигация кабинетов (E §1.5). `feature` — пункт виден только при включённом флаге каталога. */
export const NAV = {
  candidate: [
    { to: '/candidate', label: 'Обзор', exact: true },
    { to: '/candidate/invitations', label: 'Приглашения', counter: 'awaiting' },
    { to: '/candidate/category', label: 'Категория и тесты' },
    { to: '/candidate/profile', label: 'Профиль' },
    { to: '/candidate/vacancies', label: 'Вакансии', feature: 'vacancies' },
  ],
  employer: [
    { to: '/employer/needs', label: 'Потребности' },
    { to: '/employer/search', label: 'Банк кандидатов' },
    { to: '/employer/invitations', label: 'Приглашения' },
    { to: '/employer/vacancies', label: 'Вакансии', feature: 'vacancies' },
  ],
} as const

export const USER_MENU = {
  candidate: [
    { to: '/candidate/settings/privacy', label: 'Приватность' },
    { to: '/candidate/settings/fsp', label: 'ФСП ID' },
    { to: '/candidate/settings/account', label: 'Аккаунт' },
  ],
  employer: [
    { to: '/employer/company', label: 'Компания' },
    { to: '/employer/settings/account', label: 'Аккаунт' },
  ],
} as const

/** Шаги мастера кандидата и первого запуска работодателя. */
export const WIZARD_STEPS = {
  candidate: [
    { id: 'profile', label: 'Профиль', href: '/candidate/onboarding/profile' },
    { id: 'survey', label: 'Опрос', href: '/candidate/onboarding/survey' },
    { id: 'grade', label: 'Грейд', href: '/candidate/onboarding/grade' },
    { id: 'test', label: 'Тест', href: '/candidate/test/new' },
    { id: 'done', label: 'Категория' },
  ],
  employer: [
    { id: 'company', label: 'Компания', href: '/employer/onboarding/company' },
    { id: 'need', label: 'Потребность', href: '/employer/needs/new' },
    { id: 'shortlist', label: 'Подборка' },
  ],
} as const

export const WORK_FORMAT_LABELS: Record<WorkFormat, string> = {
  office: 'офис',
  hybrid: 'гибрид',
  remote: 'удалённо',
}

export const VISIBILITY_LABELS: Record<VisibilityState, string> = {
  visible: 'Профиль виден',
  paused: 'Профиль скрыт',
  unpublished: 'Не опубликован',
  not_ready: 'Нет категории',
}

export const INVITATION_STATUS_LABELS: Record<Role, Partial<Record<InvitationStatus, string>>> = {
  employer: {
    sent: 'Отправлено',
    viewed: 'Просмотрено',
    accepted: 'Принято',
    declined: 'Отклонено',
    expired: 'Срок истёк',
    withdrawn: 'Отозвано',
    bounced: 'Не доставлено',
  },
  candidate: {
    sent: 'Новое',
    viewed: 'Ждёт ответа',
    accepted: 'Принято',
    declined: 'Отклонено вами',
    expired: 'Срок истёк',
    withdrawn: 'Отозвано работодателем',
  },
}

export const TEST_OUTCOME_LABELS: Record<TestOutcome, string> = {
  confirmed: 'Грейд подтверждён',
  confirmed_with_margin: 'Подтверждён с запасом',
  borderline: 'Результат на границе',
  not_confirmed: 'Грейд не подтверждён',
}

/** Подписи вида доказательства: работодателю и кандидату (о своём). */
export const EVIDENCE_LABELS: Record<EvidenceKind, { employer: string; self: string }> = {
  test: { employer: 'подтверждено тестом', self: 'подтверждено тестом' },
  pulse: { employer: 'короткое задание', self: 'короткое задание' },
  fsp: { employer: 'достижение ФСП', self: 'достижение ФСП' },
  declared: { employer: 'заявлено кандидатом', self: 'указано вами' },
  none: { employer: 'нет данных', self: 'нет данных' },
}

export const FIT_BAND_LABELS: Record<FitBand, string> = {
  strong: 'Сильное совпадение',
  good: 'Хорошее совпадение',
  partial: 'Частичное совпадение',
}

/** Сила подтверждённого профиля (`strength_label`, Арх. 9.11): в схеме API это перечисление без собственного имени. */
export type StrengthLabel = 'high' | 'medium' | 'base'

export const STRENGTH_LABELS: Record<StrengthLabel, string> = {
  high: 'высокая',
  medium: 'средняя',
  base: 'базовая',
}

export const SALARY = {
  perMonth: '₽ в месяц',
  from: 'От',
  to: 'До',
  fieldLabel: 'Зарплата, ₽ в месяц',
} as const

/** Документы P8. */
export const LEGAL_DOCS = [
  { doc: 'processing', label: 'Согласие на обработку персональных данных' },
  { doc: 'publication', label: 'Согласие на публикацию профиля' },
  { doc: 'privacy', label: 'Политика обработки данных' },
] as const
