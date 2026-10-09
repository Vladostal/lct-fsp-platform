/**
 * Тексты ошибок по кодам (Арх. 9.2, 9.12; тексты — приложение E §6.4, C §9.5, D §10.4).
 * Один словарь на весь интерфейс: экраны берут текст через `errorText(code, params)` из lib/api.ts.
 * Новый код добавляется запросом владельцу файла (план, раздел 4).
 *
 * Запись — строка с подстановками `{имя}` из `ApiError.params` либо пара { text, bare }: `bare` показывается,
 * когда сервер не прислал нужных параметров (незаполненных `{…}` в интерфейсе быть не должно, E §9.1 G17).
 * Параметры форматируются по имени: `retry_after` — длительность, даты ISO — «12 окт.», числа — с разрядами.
 */

export type ErrorTemplate = string | { text: string; bare: string }

/** Текст, когда кода нет в словаре и сервер не прислал `message` (E §6.4). */
export const FALLBACK_ERROR_TEXT = 'Не получилось выполнить действие. Повторите попытку'

/** Тексты по HTTP-статусу — для кодов без собственного текста. */
export const STATUS_ERROR_TEXTS = {
  unauthorized: 'Сессия истекла. Войдите снова',
  forbidden: 'Нет доступа к этому разделу',
  notFound: 'Здесь ничего нет: ссылка устарела или объект удалён',
  validation: 'Проверьте поля формы',
  rateLimited: { text: 'Слишком часто. Повторите через {retry_after}', bare: 'Слишком часто. Повторите позже' },
  network: 'Не удалось загрузить данные. Проверьте соединение и повторите',
} as const satisfies Record<string, ErrorTemplate>

/** `cooldown_active` различается по `params.reason` (Арх. 5.7). */
export const COOLDOWN_ERROR_TEXTS: Record<string, ErrorTemplate> = {
  grade_change: {
    text: 'Сменить подтверждённый грейд можно с {available_at}',
    bare: 'Сменить подтверждённый грейд пока нельзя',
  },
  retry_same_grade: {
    text: 'Повторить тест на этот грейд можно с {available_at}',
    bare: 'Повторить тест на этот грейд пока нельзя',
  },
  session_limit: {
    text: 'Лимит тестов за 30 дней исчерпан. Следующий — с {available_at}',
    bare: 'Лимит тестов за 30 дней исчерпан',
  },
}

export const ERROR_TEXTS: Record<string, ErrorTemplate> = {
  // ── Общие (Арх. 9.2)
  not_authenticated: STATUS_ERROR_TEXTS.unauthorized,
  forbidden: STATUS_ERROR_TEXTS.forbidden,
  not_found: STATUS_ERROR_TEXTS.notFound,
  feature_disabled: 'Этот раздел на стенде отключён',
  validation_error: STATUS_ERROR_TEXTS.validation,
  rate_limited: STATUS_ERROR_TEXTS.rateLimited,
  internal_error: 'Что-то сломалось на сервере. Повторите попытку',

  // ── identity
  token_invalid: 'Ссылка недействительна или уже использована',
  token_expired: 'Ссылка устарела. Запросите новое письмо',
  invalid_credentials: 'Неверный e-mail или пароль',
  email_not_verified: 'Адрес не подтверждён. Отправьте письмо ещё раз',
  demo_account_readonly: 'Для демо-аккаунта это действие недоступно',
  password_required: 'Введите пароль, который вы указали при регистрации',
  current_password_invalid: 'Текущий пароль не подошёл',

  // ── assessment
  survey_required: 'Сначала пройдите опрос',
  claim_required: 'Сначала выберите грейд',
  claim_locked: 'Грейд уже заявлен: теперь он меняется только тестом',
  survey_version_mismatch: 'Опрос обновился. Проверьте ответы',
  specialization_change_requires_confirm: 'Смена специализации сбросит заявленный грейд. Подтвердите смену',
  session_active: 'У вас уже идёт тест',
  cooldown_active: 'Тест на этот грейд пока недоступен',
  item_already_answered: 'Ответ на это задание уже принят',
  session_finished: 'Тест уже завершён',
  session_expired: 'Время теста истекло',
  answer_malformed: 'Ответ не отправлен. Обновите страницу и ответьте ещё раз',
  specialization_unavailable: 'Тест для этого выбора готовится',
  grade_unavailable: 'Тест для этого выбора готовится',
  grade_not_allowed: 'Тест на этот грейд сейчас недоступен',
  invalid_transition: 'Такая смена статуса недопустима',
  bank_unavailable: 'Тест временно недоступен. Попробуйте позже',

  // ── pulse (P1)
  assignment_closed: 'Задание уже закрыто',
  pulse_task_limit: 'По этой потребности достигнут лимит коротких заданий',
  assignment_expired: 'Срок короткого задания истёк',
  skill_not_testable: 'Для этого навыка коротких заданий пока нет',

  // ── profile
  resume_too_large: 'Файл больше 5 МБ. Загрузите PDF меньшего размера или заполните форму вручную',
  resume_not_pdf: 'Это не PDF. Загрузите резюме в формате PDF',
  resume_encrypted: 'PDF защищён паролем. Снимите защиту или заполните форму вручную',
  resume_too_many_pages: 'В файле больше 10 страниц',
  resume_no_text: 'В PDF нет текста — похоже, это скан. Заполните форму вручную',
  resume_unreadable: 'Не удалось прочитать файл. Заполните форму вручную',
  resume_timeout: 'Не удалось прочитать файл. Заполните форму вручную',
  resume_rate_limited: 'Слишком много загрузок. Повторите через час',
  min_salary_not_on_ladder: 'Выберите значение из списка',
  no_category: 'Сначала подтвердите грейд тестом',
  profile_incomplete: 'Укажите имя и фамилию в профиле',
  consent_version_outdated: 'Текст согласия обновился. Прочитайте его ещё раз',
  publication_consent_required: 'Сначала дайте согласие на публикацию профиля',
  not_disclosed: 'Контакты откроются, когда кандидат примет приглашение',

  // ── fsp
  fsp_link_exists: 'ФСП ID уже привязан. Чтобы привязать другой, сначала отвяжите текущий',
  fsp_consent_outdated: 'Текст согласия обновился. Прочитайте его ещё раз',
  fsp_consent_required: 'Чтобы привязать ФСП ID, нужно согласие на получение сведений',
  fsp_too_many_attempts: {
    text: 'Слишком много попыток. Повторите через {retry_after}',
    bare: 'Слишком много попыток. Повторите позже',
  },
  fsp_sync_too_frequent: {
    text: 'Данные обновлялись только что. Повторите через {retry_after}',
    bare: 'Данные обновлялись только что. Повторите позже',
  },
  fsp_not_linked: 'ФСП ID не привязан',
  fsp_unavailable: 'Сервис ФСП ID недоступен. Попробуйте позже',

  // ── matching
  company_profile_incomplete: 'Сначала заполните профиль компании',
  need_archived: 'Потребность в архиве: изменить её нельзя',
  parent_mismatch: 'Версия подборки устарела. Обновите страницу и повторите уточнение',
  parent_required: 'Не выбрана версия подборки для уточнения. Обновите страницу и повторите',
  different_need: 'Версии относятся к разным потребностям: сравнить их нельзя',
  pin_limit: 'Закрепить можно не больше 50 кандидатов',
  candidate_not_in_need: 'Кандидата нет в подборках этой потребности',
  text_too_short: 'Нужно не меньше 20 знаков',
  text_too_long: 'Текст длиннее 5000 знаков',
  skill_unknown: 'Навыка нет в справочнике',
  filter_invalid: 'Одно из значений фильтра недопустимо. Измените или сбросьте фильтры',
  cursor_invalid: 'Список обновился. Загрузите его заново',
  shortlist_rate_limited: {
    text: 'Слишком много обновлений подборки. Повторите через {retry_after}',
    bare: 'Слишком много обновлений подборки. Повторите позже',
  },
  card_open_limit: 'На сегодня достигнут лимит просмотра карточек',
  bank_page_limit: 'На сегодня достигнут лимит страниц банка кандидатов',

  // ── общие правила вилки
  salary_order: 'Нижняя граница вилки больше верхней',
  salary_out_of_bounds: {
    text: 'Вилка должна быть в пределах {salary_min} – {salary_max} ₽',
    bare: 'Вилка выходит за допустимые пределы',
  },
  salary_range_too_wide: {
    text: 'Вилка слишком широкая: «до» — не больше {max_to} ₽',
    bare: 'Вилка слишком широкая: уменьшите верхнюю границу',
  },

  // ── contact
  candidate_unavailable: 'Кандидат сейчас не принимает приглашения',
  active_invitation_exists: 'Этому кандидату уже отправлено приглашение, он ещё не ответил',
  pair_cooldown: {
    text: 'Новое приглашение этому кандидату можно отправить с {until}',
    bare: 'Новое приглашение этому кандидату пока отправить нельзя',
  },
  conditions_mismatch: {
    text: 'Условия не совпали с ожиданиями кандидата. Повторить попытку можно с {until}',
    bare: 'Условия не совпали с ожиданиями кандидата',
  },
  quota_exceeded: {
    text: 'Все слоты заняты: {used} из {limit}. Ближайший освободится {next_release_at}',
    bare: 'Все слоты заняты. Дождитесь ответа кандидатов или отзовите приглашение',
  },
  revision_not_allowed: 'Пересмотренное приглашение этому кандидату уже отправлено или срок вышел',
  invitation_not_actionable: {
    text: 'Действие недоступно: приглашение в статусе «{status_label}»',
    bare: 'Действие недоступно: статус приглашения изменился',
  },
  complaint_exists: 'Жалоба на это приглашение уже отправлена',
  demo_sender_restricted: 'Демо-компания не приглашает настоящих кандидатов. Зарегистрируйте свою компанию',
  sending_frozen: 'Отправка приглашений приостановлена до разбора жалоб',
  format_not_accepted: 'Кандидат не рассматривает этот формат работы',
  revision_below_condition: 'Условия должны быть не хуже названных кандидатом',
  disclose_invalid: 'Выберите хотя бы один способ связи, указанный в профиле',
  condition_invalid:
    'Проверьте условие: сумма должна быть выше нижней границы вилки, формат — отличаться от предложенного',
  daily_limit_exceeded: {
    text: 'Достигнут суточный лимит приглашений. Следующее можно отправить через {retry_after}',
    bare: 'Достигнут суточный лимит приглашений',
  },

  // ── vacancies (P1)
  vacancy_closed: 'Вакансия закрыта',
  vacancy_status_invalid: 'Действие недоступно для вакансии в этом статусе',
  application_exists: 'Вы уже откликнулись на эту вакансию',
  application_limit_exceeded: {
    text: 'Активных откликов может быть не больше {limit}',
    bare: 'Достигнут лимит активных откликов',
  },
  application_not_actionable: 'Действие недоступно: отклик уже обработан',
  category_required: 'Сначала подтвердите грейд тестом',
  invitation_pending: 'У вас есть приглашение от этой компании. Ответьте на него',
  interest_limit_exceeded: {
    text: 'Отметить интерес можно не больше чем к {limit} вакансиям',
    bare: 'Достигнут лимит отметок «Мне интересно»',
  },

  // ── integrations (P2), demo
  webhook_url_invalid: 'Укажите адрес, который начинается с https://',
  sessions_in_progress: 'Есть незавершённые тесты: сдвиг времени завершит их. Подтвердите сдвиг',
}
