import { createFileRoute, Outlet } from '@tanstack/react-router'
import { AuthLayout } from '@/components/app'

/** Каркас Auth: одна карточка 480 px по центру (регистрация, вход, подтверждение адреса, сброс пароля). */
export const Route = createFileRoute('/_auth')({
  component: AuthFrame,
})

function AuthFrame() {
  return (
    <AuthLayout>
      <Outlet />
    </AuthLayout>
  )
}
