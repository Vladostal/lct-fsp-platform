import { createFileRoute } from '@tanstack/react-router'
import { NeedListScreen } from '@/features/matching'

/** E2. Потребности. */
export const Route = createFileRoute('/employer/_cabinet/needs/')({
  component: NeedListScreen,
})
