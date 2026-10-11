/**
 * Общие компоненты приложения (Арх. 11.6). Пакеты экранов импортируют их только отсюда: `@/components/app`.
 * Недостающий общий компонент — запросом владельцу (план, раздел 4).
 */
export { AppLogo, type AppLogoProps } from './app-logo'
export {
  CandidateCategoryChip,
  type CandidateCategoryChipProps,
  CategoryChip,
  type CategoryChipProps,
} from './category-chip'
export { ClampText, type ClampTextProps } from './clamp-text'
export { ConsentCheckbox, type ConsentCheckboxProps } from './consent-checkbox'
export { ContributionBars, type ContributionBarsProps } from './contribution-bars'
export { CopyButton, type CopyButtonProps } from './copy-button'
export { DeadlinePill, type DeadlinePillProps } from './deadline-pill'
export { DemoChip } from './demo-chip'
export { EmptyState, type EmptyStateProps } from './empty-state'
export { ErrorState, type ErrorStateProps } from './error-state'
export { EvidenceChip, type EvidenceChipProps, EvidenceLegend, type EvidenceLegendProps } from './evidence-chip'
export { ExternalLink } from './external-link'
export { FitBadge, type FitBadgeProps } from './fit-badge'
export { FunnelStrip, type FunnelStripProps } from './funnel-strip'
export { IconTile, type IconTileProps } from './icon-tile'
export { AuthLayout } from './layout/auth-layout'
export { CabinetLayout, type CabinetLayoutProps } from './layout/cabinet-layout'
export { FocusHeaderSlot, FocusLayout } from './layout/focus-layout'
export { PublicLayout, type PublicLayoutProps } from './layout/public-layout'
export { SiteFooter } from './layout/site-footer'
export { SkipLink } from './layout/skip-link'
export { WizardLayout, type WizardLayoutProps, WizardStep, type WizardStepProps } from './layout/wizard-layout'
export { LevelScale, type LevelScaleProps } from './level-scale'
export {
  FunnelBars,
  type FunnelBarsProps,
  type FunnelBarsStep,
  type LegendItem,
  LegendList,
  type LegendListProps,
  MiniBar,
  type MiniBarProps,
} from './mini-bar'
export { NotFound, type NotFoundProps } from './not-found'
export { type Crumb, PageHeader, type PageHeaderProps } from './page-header'
export { PageSkeleton, type PageSkeletonProps } from './page-skeleton'
export { PasswordInput } from './password-input'
export {
  DashedNote,
  type DashedNoteProps,
  Pipeline,
  type PipelineProps,
  StageCell,
  type StageCellProps,
} from './pipeline'
export { PipelineLine, type PipelineLineProps } from './pipeline-line'
export { ProgressRing, type ProgressRingProps, type RingSegment } from './progress-ring'
export { QuotaIndicator, type QuotaIndicatorProps } from './quota-indicator'
export { RevealOnce, type RevealOnceProps } from './reveal-once'
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
export { Section, type SectionProps } from './section'
export { CountChip, type CountChipProps, GoChevron, SoftPill, type SoftPillProps } from './soft-pill'
export { Stat, type StatProps } from './stat'
export { StatTile, type StatTileProps, SummaryStrip, type SummaryStripProps } from './stat-tile'
export { StatusBadge, type StatusBadgeProps, type StatusTone } from './status-badge'
export { Stepper, type StepperProps, type StepperStep } from './stepper'
export { StickyActionBar, type StickyActionBarProps } from './sticky-action-bar'
export { StrengthPill, type StrengthPillProps } from './strength-pill'
export { TagInput, type TagInputProps, type TagOption, type TagValue } from './tag-input'
export { ThemeMenuItems, ThemeSwitch } from './theme-switch'
export { CHART, type ChartColor, type TileTone, type Tone } from './tone'
export { usePageTitle } from './use-page-title'
export {
  FORMAT_ICON,
  FormatChoice,
  type FormatChoiceProps,
  FormatLabel,
  FormatPill,
  type FormatPillProps,
} from './work-format'
