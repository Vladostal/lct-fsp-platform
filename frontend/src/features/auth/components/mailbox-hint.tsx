import { ExternalLink } from '@/components/app'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { MAILPIT_PUBLIC_URL } from '@/lib/config'
import { AUTH } from '../content'

/**
 * Подсказка о почтовом ящике стенда (Арх. 10.2, 11.8): показывается, только когда задан `MAILPIT_PUBLIC_URL`.
 * С настоящим SMTP значение пусто — блока нет вовсе.
 */
export function MailboxHint() {
  if (!MAILPIT_PUBLIC_URL) return null
  return (
    <Alert variant="info">
      <AlertTitle>{AUTH.checkEmail.mailboxTitle}</AlertTitle>
      <AlertDescription>
        <ExternalLink href={MAILPIT_PUBLIC_URL} className="tap-target">
          {AUTH.checkEmail.mailboxLink}
        </ExternalLink>
      </AlertDescription>
    </Alert>
  )
}
