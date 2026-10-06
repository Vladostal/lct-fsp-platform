/** Публичный экспорт домена `assessment` (Арх. 11.1): экраны C2–C6, C10 и компоненты для соседних пакетов. */
export * as assessmentApi from './api'
export { assessmentKeys, blueprintsQuery, evidenceQuery, historyQuery } from './api'
export { BlueprintPreview, type BlueprintPreviewProps } from './components/blueprint-preview'
export { Briefing } from './components/briefing'
export { CategoryScreen } from './components/category-screen'
export { GradePicker } from './components/grade-picker'
export { NextActionButton, NextActionList } from './components/next-actions'
export { ResultScreen } from './components/result-screen'
export { SurveyForm } from './components/survey-form'
export {
  buildAnswer,
  CodeBlock,
  ItemTable,
  type ItemValue,
  TestItemRenderer,
  type TestItemRendererProps,
} from './components/test-item-renderer'
export { TestScreen } from './components/test-screen'
export { TestTimer, useTestRemaining } from './components/test-timer'
export { ASSESSMENT } from './content'
export { useAssessmentState, useTestSession } from './hooks'
