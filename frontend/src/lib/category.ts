/**
 * Основание категории кандидата: подтверждена тестом или грейд заявлен самим кандидатом (теста по специализации
 * пока нет). В справочнике `available === false` у специализации значит «тест готовится, грейд заявленный».
 */
import type { Catalog, CategoryRef } from '@/client'

type CatalogSpecs = Pick<Catalog, 'specializations'> | null | undefined
type CategoryForBasis = Pick<CategoryRef, 'basis'> & { specialization: { code: string } }

/** Есть ли тест по специализации. Неизвестный код или незагруженный справочник — считаем, что тест есть. */
export function hasTest(catalog: CatalogSpecs, specializationCode: string | null | undefined): boolean {
  if (!specializationCode) return true
  return catalog?.specializations.find((s) => s.code === specializationCode)?.available !== false
}

/**
 * Грейд заявлен, а не подтверждён тестом. Источник — `basis` категории; ответы без него (приглашения, выпавшие
 * строки подборки) определяются по справочнику. Для цели потребности не применяется: это не категория кандидата.
 */
export function isDeclared(category: CategoryForBasis | null | undefined, catalog: CatalogSpecs): boolean {
  if (!category) return false
  if (category.basis != null) return category.basis === 'declared'
  return !hasTest(catalog, category.specialization.code)
}
