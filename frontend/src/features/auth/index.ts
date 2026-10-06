/** Публичный экспорт домена `auth` (Арх. 11.1): экраны P2–P5a, C14, E10 и хуки сеанса. */
export * as authApi from './api'
export { AccountSettings, type AccountSettingsProps } from './components/account-settings'
export { CheckEmailPanel } from './components/check-email-panel'
export { CabinetFrame, WizardFrame } from './components/frames'
export { LoginForm, type LoginFormProps } from './components/login-form'
export { ForgotPasswordForm, ResetPasswordForm } from './components/password-forms'
export { SignupForm } from './components/signup-form'
export { VerifyEmailPanel } from './components/verify-email-panel'
export { AUTH } from './content'
export {
  useChangePassword,
  useDeleteAccount,
  useEnterSession,
  useForgotPassword,
  useLogin,
  useLogout,
  useResendVerification,
  useResetPassword,
  useSignup,
  useVerifyEmail,
} from './hooks'
export {
  checkEmailSearchSchema,
  loginSearchSchema,
  signupSearchSchema,
  tokenSearchSchema,
} from './schemas'
