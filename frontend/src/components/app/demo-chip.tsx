import { FlaskConical } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { COMMON } from '@/content/common'

/** Чип «демо»: синтетические записи и результаты быстрого демо-теста помечены везде (Арх. 13.5). */
export function DemoChip({ className }: { className?: string }) {
  return (
    <Badge variant="outline" size="sm" data-slot="demo-chip" className={className}>
      <FlaskConical aria-hidden="true" />
      {COMMON.demoChip}
    </Badge>
  )
}
