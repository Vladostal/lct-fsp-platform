import { createFileRoute, notFound } from '@tanstack/react-router'
import { PageHeader } from '@/components/app'
import { Card } from '@/components/ui/card'
import { LEGAL_DOCS } from '@/content/common'
import { hasStatus } from '@/lib/api'
import { legalDocQuery } from '@/lib/query'

const KNOWN_DOCS: readonly string[] = LEGAL_DOCS.map((item) => item.doc)

/**
 * P8. Тексты согласий и политики `/legal/$doc` (`processing`, `publication`, `privacy`) — с сервера
 * (`GET /legal/{doc}`, Арх. 11.8): версия текста в шапке, колонка не шире 72ch. Неизвестный документ — 404.
 */
export const Route = createFileRoute('/_public/legal/$doc')({
  loader: async ({ context, params }) => {
    if (!KNOWN_DOCS.includes(params.doc)) throw notFound()
    try {
      return await context.queryClient.ensureQueryData(legalDocQuery(params.doc))
    } catch (error) {
      if (hasStatus(error, 404)) throw notFound()
      throw error
    }
  },
  component: LegalDocument,
})

/** Текст документа приходит строкой: абзацы разделены пустой строкой, строка с «#» — заголовок раздела. */
function renderBlocks(text: string) {
  return text
    .split(/\n{2,}/)
    .map((block) => block.trim())
    .filter(Boolean)
    .map((block, index) => {
      const heading = /^#{1,3}\s+(.*)$/.exec(block)
      const key = `${index}-${block.slice(0, 24)}`
      if (heading && !block.includes('\n')) {
        return (
          <h2 key={key} className="type-h3 pt-2 text-ink">
            {heading[1]}
          </h2>
        )
      }
      return (
        <p key={key} className="type-body whitespace-pre-line text-ink [overflow-wrap:anywhere]">
          {block}
        </p>
      )
    })
}

function LegalDocument() {
  const doc = Route.useLoaderData()
  return (
    <div className="page-container flex flex-col gap-6 py-8 md:py-12">
      <PageHeader title={doc.title} eyebrow={`версия ${doc.version}`} />
      <Card className="max-w-[calc(72ch+48px)]">
        <article className="flex max-w-[72ch] min-w-0 flex-col gap-4">{renderBlocks(doc.text)}</article>
      </Card>
    </div>
  )
}
