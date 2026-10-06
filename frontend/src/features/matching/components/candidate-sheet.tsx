import { Sheet, SheetBody, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { CandidateView, type CandidateViewProps } from './candidate-view'

type Props = Omit<CandidateViewProps, 'layout' | 'onClose'> & { onClose: () => void }

/** E5 в виде панели справа (на E4 и E8); закрытие возвращает прежний адрес. */
export function CandidateSheet(props: Props) {
  return (
    <Sheet open onOpenChange={(open) => (open ? undefined : props.onClose())}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>{props.invite ? 'Приглашение' : 'Карточка кандидата'}</SheetTitle>
          <SheetDescription className="sr-only">Подробности о кандидате и отправка приглашения</SheetDescription>
        </SheetHeader>
        <SheetBody>
          <CandidateView {...props} layout="sheet" />
        </SheetBody>
      </SheetContent>
    </Sheet>
  )
}
