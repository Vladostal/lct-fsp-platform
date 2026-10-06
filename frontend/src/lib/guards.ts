/**
 * Охрана маршрутов на клиенте (Арх. 11.3; приложение E, §1.3). Это удобство, а не защита: роль и владение
 * проверяет каждый эндпоинт. Шаг мастера кандидата вычисляется из профиля и состояния теста — отдельного поля
 * сервера нет.
 *
 * Чистые функции (`onboardingStep`, `home`, `safeNext`, `candidateGuard`, `employerGuard`) не делают запросов;
 * данные для них загружают `loadHomeData` и `resolveHome`.
 */
import type { QueryClient } from '@tanstack/react-query'
import { redirect } from '@tanstack/react-router'
import { toast } from 'sonner'
import type { AssessmentStateView, CandidateProfileView, CompanyView, MeView, NeedView, Role } from '@/client'
import { COMMON } from '@/content/common'
import { ApiError, hasStatus, isApiError } from '@/lib/api'
import { assessmentStateQuery, candidateProfileQuery, companyQuery, needsQuery } from '@/lib/query'

export type OnboardingStep = 'profile' | 'survey' | 'grade' | 'test' | 'done'

/** Порядок шагов мастера кандидата. */
export const ONBOARDING_ORDER: readonly OnboardingStep[] = ['profile', 'survey', 'grade', 'test', 'done']

type ProfileForGuard = Pick<CandidateProfileView, 'first_name' | 'last_name'>
type StateForGuard = Pick<
  AssessmentStateView,
  'category' | 'last_session' | 'survey_completed' | 'claimed_grade' | 'active_session'
>

/**
 * Шаг мастера кандидата:
 *   категория или завершённая сессия есть → done (тест уже проходил; кандидат без подтверждённого грейда
 *   попадает в кабинет, но не в выдачу); нет имени или фамилии → profile; опрос не пройден → survey;
 *   грейд не заявлен → grade; иначе → test.
 */
export function onboardingStep(profile: ProfileForGuard, state: StateForGuard): OnboardingStep {
  if (state.category != null || state.last_session != null) return 'done'
  if (!profile.last_name || !profile.first_name) return 'profile'
  if (!state.survey_completed) return 'survey'
  if (state.claimed_grade == null) return 'grade'
  return 'test'
}

/** Маршрут шага мастера. Для `done` — обзор кабинета. */
export function stepRoute(step: OnboardingStep): string {
  if (step === 'done') return '/candidate'
  return step === 'test' ? '/candidate/test/new' : `/candidate/onboarding/${step}`
}

/** Данные для выбора первого экрана; отсутствующая часть означает «ещё не загружено или недоступно». */
export type HomeData = {
  profile?: ProfileForGuard | null
  state?: StateForGuard | null
  company?: Pick<CompanyView, 'is_complete'> | null
  needs?: readonly Pick<NeedView, 'id'>[] | null
}

/**
 * Первый экран после входа (E §1.4):
 *   кандидат: активная сессия → тест; шаг мастера не done → маршрут шага; иначе → обзор;
 *   работодатель: компания не заполнена → профиль компании; потребностей нет → новая потребность; иначе → список.
 * Если данных нет (эндпоинт недоступен), выбирается корень кабинета роли — охрана внутри него повторит проверку.
 */
export function home(me: Pick<MeView, 'role'>, data: HomeData = {}): string {
  if (me.role === 'candidate') {
    if (data.state?.active_session) return `/candidate/test/${data.state.active_session.id}`
    if (data.profile && data.state) {
      const step = onboardingStep(data.profile, data.state)
      if (step !== 'done') return stepRoute(step)
    }
    return '/candidate'
  }
  if (data.company && !data.company.is_complete) return '/employer/onboarding/company'
  if (data.needs && data.needs.length === 0) return '/employer/needs/new'
  return '/employer/needs'
}

/**
 * Параметр возврата `next` принимается, только если это путь внутри сайта: начинается с одного «/»
 * и не содержит «//» и «\» (иначе через ссылку на вход можно было бы увести пользователя на чужой сайт).
 */
export function safeNext(next: unknown): string | null {
  if (typeof next !== 'string' || next.length === 0 || next.length > 2000) return null
  if (!next.startsWith('/') || next.startsWith('//')) return null
  if (next.includes('\\') || next.includes('//')) return null
  // Управляющие символы (перевод строки, табуляция) в адресе возврата недопустимы.
  for (let i = 0; i < next.length; i += 1) {
    if (next.charCodeAt(i) < 0x20) return null
  }
  return next
}

/** Адрес входа с возвратом на текущую страницу. */
export function loginHref(next?: string | null): string {
  const safe = safeNext(next)
  return safe && safe !== '/' ? `/login?next=${encodeURIComponent(safe)}` : '/login'
}

/** Корень кабинета роли. */
export function roleRoot(role: Role): string {
  return role === 'candidate' ? '/candidate' : '/employer'
}

/**
 * Запросить, не роняя охрану: 401 пробрасывается (его обработает общий перехватчик), любой другой сбой
 * (эндпоинт ещё не реализован, сеть) даёт null — тогда проверка шага пропускается, а экран сам покажет ошибку.
 */
async function tolerant<T>(load: () => Promise<T>): Promise<T | null> {
  try {
    return await load()
  } catch (error) {
    if (hasStatus(error, 401)) throw error
    return null
  }
}

/**
 * Загрузить данные, по которым выбирается первый экран и проверяется шаг мастера.
 *
 * `fresh: true` — запросить заново (после входа и на шагах мастера). Иначе берётся кэш каркаса, но только
 * если он уже говорит «мастер пройден» / «компания заполнена»: эти состояния не откатываются, а незавершённое
 * экраны меняют своими мутациями (ключи сгенерированного клиента каркасу не видны), поэтому перепроверяется
 * запросом. Так охрана не зацикливает пользователя на шаге, который он только что сохранил.
 */
export async function loadHomeData(
  queryClient: QueryClient,
  me: Pick<MeView, 'role'>,
  options: { fresh?: boolean } = {},
): Promise<HomeData> {
  const staleTime = options.fresh ? 0 : 60_000
  if (me.role === 'candidate') {
    const cachedProfile = queryClient.getQueryData(candidateProfileQuery.queryKey)
    const cachedState = queryClient.getQueryData(assessmentStateQuery.queryKey)
    const settled =
      !options.fresh &&
      cachedProfile !== undefined &&
      cachedState !== undefined &&
      !cachedState.active_session &&
      onboardingStep(cachedProfile, cachedState) === 'done'
    if (settled) return { profile: cachedProfile, state: cachedState }
    const [profile, state] = await Promise.all([
      tolerant(() => queryClient.fetchQuery({ ...candidateProfileQuery, staleTime: options.fresh ? 0 : 5_000 })),
      tolerant(() => queryClient.fetchQuery({ ...assessmentStateQuery, staleTime: options.fresh ? 0 : 5_000 })),
    ])
    return { profile, state }
  }
  const cachedCompany = queryClient.getQueryData(companyQuery.queryKey)
  const company =
    !options.fresh && cachedCompany?.is_complete
      ? cachedCompany
      : await tolerant(() => queryClient.fetchQuery({ ...companyQuery, staleTime: options.fresh ? 0 : 5_000 }))
  const needs = await tolerant(() => queryClient.fetchQuery({ ...needsQuery, staleTime }))
  return { company, needs }
}

/** Первый экран для пользователя — с запросом свежих данных (после входа, подтверждения адреса, смены роли экрана). */
export async function resolveHome(queryClient: QueryClient, me: Pick<MeView, 'role'>): Promise<string> {
  return home(me, await loadHomeData(queryClient, me, { fresh: true }))
}

/**
 * Сбросить данные охраны после мутации, меняющей шаг мастера или первый экран (сохранение профиля, опроса,
 * грейда, старт и завершение теста, профиль компании, первая потребность).
 */
export function invalidateGuardData(queryClient: QueryClient): Promise<void> {
  return queryClient.invalidateQueries({
    predicate: (query) => query.queryKey[0] === 'candidate' || query.queryKey[0] === 'employer',
  })
}

const WIZARD_STEP_BY_PATH: Record<string, OnboardingStep> = {
  '/candidate/onboarding/profile': 'profile',
  '/candidate/onboarding/survey': 'survey',
  '/candidate/onboarding/grade': 'grade',
  '/candidate/test/new': 'test',
}

function trimSlash(pathname: string): string {
  return pathname.length > 1 && pathname.endsWith('/') ? pathname.slice(0, -1) : pathname
}

/**
 * Охрана маршрутов кандидата (E §1.3, правила 4–6). Возвращает адрес перенаправления либо null.
 *   4. мастер не пройден: разрешены шаги не дальше текущего; брифинг теста — только на шаге test;
 *      экраны своей сессии теста (C5, C6) доступны всегда; остальное → маршрут текущего шага;
 *   5. идёт тест, а открыт шаг мастера или брифинг → экран теста;
 *   6. мастер пройден, а открыт шаг 1–3 → обзор (брифинг остаётся: с него стартует повторная попытка).
 */
export function candidateGuard(pathname: string, data: HomeData): string | null {
  const { profile, state } = data
  if (!profile || !state) return null
  const path = trimSlash(pathname)
  const wizardStep = WIZARD_STEP_BY_PATH[path]
  const isSessionScreen = path.startsWith('/candidate/test/') && wizardStep === undefined
  const step = onboardingStep(profile, state)

  if (state.active_session && wizardStep !== undefined) {
    return `/candidate/test/${state.active_session.id}`
  }
  if (step === 'done') {
    return wizardStep !== undefined && wizardStep !== 'test' ? '/candidate' : null
  }
  if (isSessionScreen) return null
  if (wizardStep === undefined) return stepRoute(step)
  if (wizardStep === 'test') return step === 'test' ? null : stepRoute(step)
  return ONBOARDING_ORDER.indexOf(wizardStep) <= ONBOARDING_ORDER.indexOf(step) ? null : stepRoute(step)
}

/**
 * Охрана маршрутов работодателя (E §1.3, правило 7): пока профиль компании не заполнен, доступны только
 * профиль компании (E1) и аккаунт (E10).
 */
export function employerGuard(pathname: string, data: HomeData): string | null {
  const path = trimSlash(pathname)
  if (!data.company || data.company.is_complete) {
    return null
  }
  const allowed = ['/employer/onboarding/company', '/employer/settings/account']
  return allowed.includes(path) ? null : '/employer/onboarding/company'
}

/** Пути мастера кандидата: на них шаг всегда перепроверяется запросом. */
export function isWizardPath(pathname: string): boolean {
  return WIZARD_STEP_BY_PATH[trimSlash(pathname)] !== undefined
}

type GuardContext = { queryClient: QueryClient; me: MeView | null; meError: unknown }

/**
 * Охрана префиксов /candidate и /employer (E §1.3, правила 2–3) для `beforeLoad`:
 *   состояние сессии неизвестно (сбой запроса) → ошибка маршрута с «Повторить»;
 *   гость → вход с возвратом (`next`); чужая роль → первый экран своей роли и сообщение.
 * Возвращает пользователя нужной роли.
 */
export async function requireRole(context: GuardContext, role: Role, currentHref: string): Promise<MeView> {
  if (context.meError) {
    // Состояние сессии неизвестно, каким бы ни был ответ на /auth/me (сеть, 5xx, 404 от ещё не подключённого
    // модуля): показываем «Не удалось загрузить данные» с «Повторить», а не «нет доступа» или «не найдено».
    const cause = isApiError(context.meError) ? context.meError.code : 'unknown'
    throw new ApiError({ status: 0, code: `session_check_failed:${cause}` })
  }
  if (!context.me) throw redirect({ href: loginHref(currentHref) })
  if (context.me.role !== role) {
    toast.info(COMMON.wrongRole[role])
    throw redirect({ href: await resolveHome(context.queryClient, context.me) })
  }
  return context.me
}

/** Экраны только для гостя (регистрация, «проверьте почту», вход): вошедший уходит на свой первый экран. */
export async function redirectSignedIn(context: GuardContext): Promise<void> {
  if (context.me) throw redirect({ href: await resolveHome(context.queryClient, context.me) })
}
