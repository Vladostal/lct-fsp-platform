import { Lock, Search, Send, Users } from 'lucide-react'
import { CategoryChip, EvidenceChip, SalaryRange, StatusBadge } from '@/components/app'

/*
 * Живой герой: потребность → категория и кандидаты → приглашение с вилкой. Цикл 9 с на CSS.
 * Стартовое состояние слоёв — только в кейфреймах; без анимации (reduce) слои 1–2 скрыты, виден слой приглашения.
 * Высоту задаёт слой 3, слои 1–2 лежат поверх него и короче.
 */
const CSS = `
.hf-l1,.hf-l2{display:none}
@media (prefers-reduced-motion: no-preference){
  .hf-l1,.hf-l2{display:flex}
  .hf-l1{animation:hf-a 9s var(--ease-enter,ease) infinite both}
  .hf-l2{animation:hf-b 9s var(--ease-enter,ease) infinite both}
  .hf-l3{animation:hf-c 9s var(--ease-enter,ease) infinite both}
  .hf-d1{animation:hf-d1 9s linear infinite both}
  .hf-d2{animation:hf-d2 9s linear infinite both}
  .hf-d3{animation:hf-d3 9s linear infinite both}
}
/* Цветное свечение под карточкой и шапка шага: фон шапки задан и цветом, и градиентом — контраст считается по цвету. */
.hf-glow{position:absolute;inset:0;filter:blur(36px);pointer-events:none;background:
  radial-gradient(55% 60% at 85% 8%,color-mix(in srgb,var(--color-brand-600) 30%,transparent),transparent 70%),
  radial-gradient(50% 55% at 8% 95%,color-mix(in srgb,var(--color-fsp-red) 18%,transparent),transparent 70%)}
.hf-band{background-color:var(--color-brand-600);background-image:linear-gradient(115deg,var(--color-brand-600),var(--color-brand-900))}
.hf-bar{background-image:linear-gradient(90deg,var(--color-brand-600),var(--color-brand-200))}
@keyframes hf-a{0%{opacity:0;transform:translateY(8px)}6%,28%{opacity:1;transform:none}34%,100%{opacity:0;transform:translateY(-8px)}}
@keyframes hf-b{0%,30%{opacity:0;transform:translateY(8px)}38%,61%{opacity:1;transform:none}67%,100%{opacity:0;transform:translateY(-8px)}}
@keyframes hf-c{0%,63%{opacity:0;transform:translateY(8px)}72%,94%{opacity:1;transform:none}100%{opacity:0;transform:none}}
@keyframes hf-d1{0%,33%{background:var(--color-brand-600)}34%,100%{background:var(--color-line-strong)}}
@keyframes hf-d2{0%,33%{background:var(--color-line-strong)}34%,66%{background:var(--color-brand-600)}67%,100%{background:var(--color-line-strong)}}
@keyframes hf-d3{0%,66%{background:var(--color-line-strong)}67%,100%{background:var(--color-brand-600)}}
`

const CANDIDATES = [
  { code: 'K-4821', strength: 92, tone: 'bg-brand-600' },
  { code: 'K-1307', strength: 74, tone: 'bg-brand-900' },
  { code: 'K-9054', strength: 58, tone: 'bg-fsp-red dark:bg-brand-900' },
] as const

const NEED_TAGS = ['Python', 'PostgreSQL', 'Удалённо'] as const

const BAND = 'absolute inset-0 items-center gap-2 px-5 md:px-6'

export function HeroFlow() {
  return (
    <figure className="relative flex min-w-0 flex-col gap-4">
      <style>{CSS}</style>
      <div aria-hidden="true" className="hf-glow" />
      <div className="relative min-w-0 overflow-hidden rounded-lg bg-surface shadow-pop md:rounded-xl">
        {/* Шапка шага: подписи сменяются вместе со слоями */}
        <div className="hf-band relative h-11 text-on-brand">
          <p aria-hidden="true" className={`hf-l1 type-sm font-medium ${BAND}`}>
            <Search className="size-4 shrink-0" />
            Работодатель описывает потребность
          </p>
          <p aria-hidden="true" className={`hf-l2 type-sm font-medium ${BAND}`}>
            <Users className="size-4 shrink-0" />
            Платформа подбирает категорию
          </p>
          <p className={`hf-l3 type-sm flex font-medium ${BAND}`}>
            <Send aria-hidden="true" className="size-4 shrink-0" />
            Вам приходит приглашение
          </p>
        </div>
        <div className="relative min-w-0 p-5 md:p-6">
          {/* Слой 1: потребность */}
          <div aria-hidden="true" className="hf-l1 absolute inset-0 flex-col justify-center gap-3 p-5 md:p-6">
            <p className="type-sm flex min-w-0 items-start gap-2 rounded-md bg-fill px-3 py-2.5 text-ink">
              <Search className="mt-0.5 size-4 shrink-0 text-ink-muted" />
              <span className="min-w-0">
                Нужен backend-разработчик в платёжный сервис: Python, PostgreSQL, удалённо
              </span>
            </p>
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <CategoryChip title="Backend · Middle" />
              {NEED_TAGS.map((tag) => (
                <span
                  key={tag}
                  className="type-caption rounded-full bg-brand-50 px-2.5 py-1 font-medium text-brand-700"
                >
                  {tag}
                </span>
              ))}
            </div>
            <p className="num type-sm self-start rounded-full bg-success-bg px-3 py-1 font-medium text-success">
              180 000 – 240 000 ₽
            </p>
          </div>
          {/* Слой 2: категория и кандидаты */}
          <div aria-hidden="true" className="hf-l2 absolute inset-0 flex-col justify-center gap-3 p-5 md:p-6">
            <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
              <CategoryChip title="Backend · Middle" />
              <span className="type-caption text-ink-muted">по силе профиля</span>
            </div>
            <ol className="flex min-w-0 flex-col gap-1.5">
              {CANDIDATES.map((c, i) => (
                <li
                  key={c.code}
                  className={
                    i === 0
                      ? 'flex min-w-0 items-center gap-3 rounded-md border border-brand-600 bg-brand-50 px-3 py-1.5'
                      : 'flex min-w-0 items-center gap-3 rounded-md border border-transparent px-3 py-1.5'
                  }
                >
                  <span
                    className={`type-caption flex size-7 shrink-0 items-center justify-center rounded-full font-medium text-on-brand ${c.tone}`}
                  >
                    {i + 1}
                  </span>
                  <span className={i === 0 ? 'num type-sm font-medium text-ink' : 'num type-sm text-ink-muted'}>
                    {c.code}
                  </span>
                  <span className="ml-auto h-1.5 w-20 shrink-0 overflow-hidden rounded-full bg-fill">
                    <span className="hf-bar block h-full rounded-full" style={{ width: `${c.strength}%` }} />
                  </span>
                </li>
              ))}
            </ol>
          </div>
          {/* Слой 3: приглашение, задаёт высоту */}
          <div className="hf-l3 flex min-w-0 flex-col gap-4">
            <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
              <CategoryChip title="Backend · Middle" />
              <StatusBadge status="sent" label="Новое" size="sm" />
            </div>
            <div className="flex min-w-0 flex-col gap-1">
              <p className="type-sm text-ink-muted">Backend-разработчик в платёжный сервис</p>
              <SalaryRange from={180000} to={240000} size="lg" />
            </div>
            <ul className="flex min-w-0 flex-wrap gap-2" aria-label="Чем вы подходите">
              <li>
                <EvidenceChip kind="test" skill="Python" size="sm" />
              </li>
              <li>
                <EvidenceChip kind="fsp" skill="Алгоритмы" size="sm" />
              </li>
              <li>
                <EvidenceChip kind="declared" skill="Kafka" size="sm" />
              </li>
            </ul>
            <p className="type-sm flex min-w-0 items-start gap-2 text-ink-muted">
              <Lock aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
              <span className="min-w-0">Имя и контакты откроются после вашего согласия</span>
            </p>
          </div>
        </div>
      </div>
      <div aria-hidden="true" className="relative flex items-center justify-center gap-2">
        <span className="hf-d1 size-2 rounded-full bg-brand-600" />
        <span className="h-px w-8 bg-line-strong" />
        <span className="hf-d2 size-2 rounded-full bg-line-strong" />
        <span className="h-px w-8 bg-line-strong" />
        <span className="hf-d3 size-2 rounded-full bg-line-strong" />
      </div>
    </figure>
  )
}
