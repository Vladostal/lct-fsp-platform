import type { Catalog } from '@/client'

/**
 * Флаги стенда. Тип выводится из `Catalog`, а не импортируется по имени: как генератор назовёт вложенную схему,
 * зависит от имени модели на бэкенде, а поле `Catalog.features` закреплено архитектурой (Арх. 9.11).
 */
export type CatalogFeatures = Catalog['features']

/**
 * Включён ли демо-режим стенда (`catalog.features.demo`). Если каталог недоступен (API не запущен), в сборке
 * для разработки демо-страницы открыты — чтобы витрина компонентов работала без бэкенда; в боевой сборке — закрыты.
 */
export function isDemoEnabled(catalog: Catalog | null | undefined): boolean {
  return catalog?.features.demo ?? import.meta.env.DEV
}

/** Включён ли флаг усиления (вакансии, короткие задания, интеграции). Без каталога — выключен. */
export function isFeatureEnabled(catalog: Catalog | null | undefined, feature: keyof CatalogFeatures): boolean {
  return catalog?.features[feature] ?? false
}
