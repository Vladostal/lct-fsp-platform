import { createFileRoute, Outlet } from '@tanstack/react-router'
import { FocusLayout } from '@/components/app'

/** Каркас Focus: узкая шапка с прогрессом и таймером, без навигации (экран теста и короткое задание). */
export const Route = createFileRoute('/candidate/_focus')({
  component: CandidateFocus,
})

function CandidateFocus() {
  return (
    <FocusLayout>
      <Outlet />
    </FocusLayout>
  )
}
