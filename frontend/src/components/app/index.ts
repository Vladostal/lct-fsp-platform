/**
 * Общие компоненты приложения (Арх. 11.6). Пакеты экранов импортируют их только отсюда: `@/components/app`.
 * Недостающий общий компонент — запросом владельцу (план, раздел 4).
 */
export { AppLogo, type AppLogoProps } from './app-logo'
export { CategoryChip, type CategoryChipProps } from './category-chip'
export { ClampText, type ClampTextProps } from './clamp-text'
export { ConsentCheckbox, type ConsentCheckboxProps } from './consent-checkbox'
export { ContributionBars, type ContributionBarsProps } from './contribution-bars'
export { CopyButton, type CopyButtonProps } from './copy-button'
export { DemoChip } from './demo-chip'
export { EmptyState, type EmptyStateProps } from './empty-state'
export { ErrorState, type ErrorStateProps } from './error-state'
export { EvidenceChip, type EvidenceChipProps, EvidenceLegend, type EvidenceLegendProps } from './evidence-chip'
export { ExternalLink } from './external-link'
export { FitBadge, type FitBadgeProps } from './fit-badge'
export { AuthLayout } from './layout/auth-layout'
export { CabinetLayout, type CabinetLayoutProps } from './layout/cabinet-layout'
export { FocusHeaderSlot, FocusLayout } from './layout/focus-layout'
export { PublicLayout, type PublicLayoutProps } from './layout/public-layout'
export { SiteFooter } from './layout/site-footer'
export { SkipLink } from './layout/skip-link'
export { WizardLayout, type WizardLayoutProps, WizardStep, type WizardStepProps } from './layout/wizard-layout'
export { LevelScale, type LevelScaleProps } from './level-scale'
export { NotFound, type NotFoundProps } from './not-found'
export { type Crumb, PageHeader, type PageHeaderProps } from './page-header'
export { PageSkeleton, type PageSkeletonProps } from './page-skeleton'
export { PasswordInput } from './password-input'
export { PipelineLine, type PipelineLineProps } from './pipeline-line'
export { QuotaIndicator, type QuotaIndicatorProps } from './quota-indicator'
export { SalaryRange, type SalaryRangeProps } from './salary-range'
export {
  maxSalaryTo,
  type SalaryLimits,
  SalaryRangeInput,
  type SalaryRangeInputProps,
  type SalaryRangeIssue,
  type SalaryRangeValue,
  validateSalaryRange,
} from './salary-range-input'
export { StatusBadge, type StatusBadgeProps, type StatusTone } from './status-badge'
export { Stepper, type StepperProps, type StepperStep } from './stepper'
export { StickyActionBar, type StickyActionBarProps } from './sticky-action-bar'
export { TagInput, type TagInputProps, type TagOption, type TagValue } from './tag-input'
export { usePageTitle } from './use-page-title'
