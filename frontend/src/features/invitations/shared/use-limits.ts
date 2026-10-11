import { useQuery } from '@tanstack/react-query'
import { catalogQuery } from '@/lib/query'

const DEFAULTS = {
  salary_min: 10000,
  salary_max: 3000000,
  salary_max_ratio: 1.5,
  invitation_ttl_days: 7,
  pair_retry_days: 30,
  revision_window_days: 7,
  decline_salary_step: 5000,
  silence_strikes: 2,
  auto_pause_max_days: 14,
}

/** Числа механики приглашений из `catalog.limits` с запасными значениями на время загрузки каталога. */
export function useCatalogLimits() {
  const { data } = useQuery(catalogQuery)
  const limits = data?.limits ?? {}
  const pick = <K extends keyof typeof DEFAULTS>(key: K): number => {
    const value = limits[key]
    return typeof value === 'number' ? value : DEFAULTS[key]
  }
  return {
    salary_min: pick('salary_min'),
    salary_max: pick('salary_max'),
    salary_max_ratio: pick('salary_max_ratio'),
    ttlDays: pick('invitation_ttl_days'),
    pairRetryDays: pick('pair_retry_days'),
    reviseDays: pick('revision_window_days'),
    declineStep: pick('decline_salary_step'),
    strikesLimit: pick('silence_strikes'),
    autoPauseDays: pick('auto_pause_max_days'),
  }
}
