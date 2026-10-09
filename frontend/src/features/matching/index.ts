/**
 * Публичный экспорт домена `matching` (Арх. 11.1, план F50): карточки для соседних пакетов.
 * `MatchCardDetailed` используют F10 (обзор кандидата) и P6 (контрольный пример).
 */
export { BankScreen } from './components/bank-screen'
export { CandidateSheet } from './components/candidate-sheet'
export { CandidateView, type CandidateViewProps, type InviteRenderProps } from './components/candidate-view'
export { MatchCardCompact, type MatchCardCompactProps } from './components/match-card-compact'
export { MatchCardDetailed, type MatchCardDetailedProps } from './components/match-card-detailed'
export { CoverageTable } from './components/need-blueprint'
export { NeedFormScreen } from './components/need-form'
export { NeedListScreen } from './components/need-list'
export { NeedScreen } from './components/need-screen'
export { MATCHING } from './content'
export { usePairStates } from './hooks'
export { bankSearchSchema, cardSearchSchema, needSearchSchema } from './schemas'
