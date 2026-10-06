import { toast } from 'sonner'
import {
  AlertDialog,
  AlertDialogBody,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { errorMessage } from '@/lib/api'
import { MATCHING } from '../content'
import { useArchiveNeed } from '../hooks'

type Props = { needId: string | null; onClose: () => void; onDone?: () => void }

/** Подтверждение переноса потребности в архив: последствия названы до нажатия. */
export function ArchiveDialog({ needId, onClose, onDone }: Props) {
  const archive = useArchiveNeed()
  const N = MATCHING.needs
  return (
    <AlertDialog open={needId !== null} onOpenChange={(open) => (open ? undefined : onClose())}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{N.archiveTitle}</AlertDialogTitle>
        </AlertDialogHeader>
        <AlertDialogBody>
          <AlertDialogDescription>{N.archiveText}</AlertDialogDescription>
        </AlertDialogBody>
        <AlertDialogFooter>
          <AlertDialogCancel>{N.cancel}</AlertDialogCancel>
          <Button
            type="button"
            variant="primary"
            loading={archive.isPending}
            onClick={() =>
              needId &&
              archive.mutate(needId, {
                onSuccess: () => {
                  onClose()
                  onDone?.()
                },
                onError: (e) => toast.error(errorMessage(e)),
              })
            }
          >
            {N.archiveConfirm}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
