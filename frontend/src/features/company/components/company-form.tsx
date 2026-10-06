import { useQuery } from '@tanstack/react-query'
import { useBlocker, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import { toast } from 'sonner'
import type { CompanyView, ContactKind } from '@/client'
import { ErrorState, PageHeader, StickyActionBar } from '@/components/app'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Textarea } from '@/components/ui/textarea'
import { applyFieldErrors, errorMessage, isApiError } from '@/lib/api'
import { companyQuery } from '@/lib/query'
import { COMPANY } from '../content'
import { useSaveCompany } from '../hooks'
import { type CompanyDraft, type CompanyErrors, EMPTY_DRAFT, toUpdate, validateCompany } from '../schema'
import { CompanyPreview } from './company-preview'
import { Field } from './field'

function toDraft(c: CompanyView | undefined): CompanyDraft {
  if (!c) return EMPTY_DRAFT
  return {
    name: c.name ?? '',
    sphere: c.sphere ?? '',
    description: c.description ?? '',
    site: c.site ?? '',
    city: c.city ?? '',
    contactKind: c.contact_method?.kind ?? 'email',
    contactValue: c.contact_method?.value ?? '',
  }
}

type Props = { mode: 'wizard' | 'cabinet'; demo: boolean }

export function CompanyScreen({ mode, demo }: Props) {
  const query = useQuery(companyQuery)
  if (query.isPending)
    return (
      <p role="status" className="type-sm text-ink-muted">
        Загружаем профиль компании…
      </p>
    )
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />
  return <CompanyForm company={query.data} mode={mode} demo={demo} />
}

function CompanyForm({ company, mode, demo }: { company: CompanyView; mode: 'wizard' | 'cabinet'; demo: boolean }) {
  const navigate = useNavigate()
  const save = useSaveCompany()
  const [initial, setInitial] = useState(() => toDraft(company))
  const [draft, setDraft] = useState(initial)
  const [errors, setErrors] = useState<CompanyErrors>({})
  const [formError, setFormError] = useState<string | null>(null)
  const dirty = JSON.stringify(draft) !== JSON.stringify(initial)

  useBlocker({
    shouldBlockFn: () => dirty && !save.isPending && !window.confirm(COMPANY.leave),
    enableBeforeUnload: dirty,
  })

  const set = <K extends keyof CompanyDraft>(key: K, value: CompanyDraft[K]) => {
    setDraft((d) => ({ ...d, [key]: value }))
    setErrors((e) => ({ ...e, [key]: undefined }))
  }

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    setFormError(null)
    const found = validateCompany(draft)
    setErrors(found)
    if (Object.keys(found).length > 0) return
    save.mutate(toUpdate(draft), {
      onSuccess: () => {
        setInitial(draft)
        if (mode === 'wizard') {
          // Состояние «сохранено» должно примениться до перехода, иначе защита от ухода сработает.
          setTimeout(() => navigate({ to: '/employer/needs/new' }), 0)
        } else toast.success(COMPANY.saved)
      },
      onError: (error) => {
        const fieldMap: Record<string, string> = {
          contact_method: 'contactValue',
          'contact_method.value': 'contactValue',
        }
        if (isApiError(error) && error.fields?.length) {
          const mapped = error.fields.map((f) => ({ ...f, name: fieldMap[f.name] ?? f.name }))
          applyFieldErrors(
            { ...error, fields: mapped } as typeof error,
            (name, e) => setErrors((prev) => ({ ...prev, [name]: e.message })),
            ['name', 'sphere', 'description', 'site', 'city', 'contactValue'] as never,
          )
        } else setFormError(errorMessage(error))
      },
    })
  }

  const fillExample = () => {
    const ex = COMPANY.example
    setDraft({ ...ex })
    setErrors({})
  }

  const header =
    mode === 'wizard' ? (
      <PageHeader title={COMPANY.wizardTitle} description={COMPANY.wizardDescription} />
    ) : (
      <PageHeader title={COMPANY.cabinetTitle} description={COMPANY.cabinetDescription} />
    )

  return (
    <div className="flex min-w-0 flex-col gap-6">
      {header}
      <form
        onSubmit={submit}
        noValidate
        className={
          mode === 'cabinet' ? 'grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1fr)_360px]' : 'flex min-w-0 flex-col gap-6'
        }
      >
        <div className="flex min-w-0 flex-col gap-6">
          {formError ? (
            <Alert variant="destructive">
              <AlertDescription>{formError}</AlertDescription>
            </Alert>
          ) : null}
          <section aria-labelledby="c-about" className="surface-card flex min-w-0 flex-col gap-4 p-5">
            <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
              <h2 id="c-about" className="type-h3">
                {COMPANY.sections.about}
              </h2>
              {demo ? (
                <Button type="button" variant="secondary" size="sm" onClick={fillExample}>
                  {COMPANY.fillExample}
                </Button>
              ) : null}
            </div>
            <Field label={COMPANY.fields.name} required error={errors.name}>
              {(p) => <Input {...p} value={draft.name} maxLength={100} onChange={(e) => set('name', e.target.value)} />}
            </Field>
            <Field label={COMPANY.fields.sphere} required error={errors.sphere}>
              {(p) => (
                <>
                  <Input
                    {...p}
                    list="company-spheres"
                    value={draft.sphere}
                    maxLength={100}
                    onChange={(e) => set('sphere', e.target.value)}
                  />
                  <datalist id="company-spheres">
                    {COMPANY.spheres.map((s) => (
                      <option key={s} value={s} />
                    ))}
                  </datalist>
                </>
              )}
            </Field>
            <Field
              label={COMPANY.fields.description}
              required
              error={errors.description}
              counter={`${draft.description.trim().length} / 2000`}
            >
              {(p) => (
                <Textarea
                  {...p}
                  rows={6}
                  value={draft.description}
                  maxLength={2000}
                  onChange={(e) => set('description', e.target.value)}
                />
              )}
            </Field>
            <div className="grid min-w-0 gap-4 sm:grid-cols-2">
              <Field label={COMPANY.fields.site} hint={COMPANY.hints.site} error={errors.site}>
                {(p) => (
                  <Input {...p} inputMode="url" value={draft.site} onChange={(e) => set('site', e.target.value)} />
                )}
              </Field>
              <Field label={COMPANY.fields.city} error={errors.city}>
                {(p) => (
                  <Input {...p} value={draft.city} maxLength={80} onChange={(e) => set('city', e.target.value)} />
                )}
              </Field>
            </div>
          </section>

          <section aria-labelledby="c-contact" className="surface-card flex min-w-0 flex-col gap-4 p-5">
            <h2 id="c-contact" className="type-h3">
              {COMPANY.sections.contact}
            </h2>
            <fieldset className="flex min-w-0 flex-col gap-2">
              <legend className="type-sm mb-1 font-medium">{COMPANY.fields.contactKind} *</legend>
              <RadioGroup
                value={draft.contactKind}
                onValueChange={(v) => set('contactKind', v as ContactKind)}
                className="grid grid-cols-2 gap-2 md:grid-cols-4"
              >
                {COMPANY.contactKinds.map((k) => (
                  <Label
                    key={k.value}
                    className="tap-target flex min-w-0 cursor-pointer items-center gap-2 rounded-md border border-line px-3 font-normal"
                  >
                    <RadioGroupItem value={k.value} />
                    <span className="min-w-0 break-words">{k.label}</span>
                  </Label>
                ))}
              </RadioGroup>
            </fieldset>
            <Field
              label={COMPANY.fields.contactValue}
              required
              hint={COMPANY.hints.contact}
              error={errors.contactValue}
            >
              {(p) => (
                <Input
                  {...p}
                  value={draft.contactValue}
                  placeholder={COMPANY.contactPlaceholders[draft.contactKind]}
                  onChange={(e) => set('contactValue', e.target.value)}
                />
              )}
            </Field>
          </section>
          {mode === 'cabinet' ? <p className="type-sm text-ink-muted">{COMPANY.hints.snapshot}</p> : null}
        </div>
        <aside className={mode === 'cabinet' ? 'min-w-0 lg:sticky lg:top-24 lg:self-start' : 'min-w-0'}>
          <CompanyPreview draft={draft} since={company.on_platform_since} trustLabel={company.trust_label} />
        </aside>
        <StickyActionBar width="page">
          <Button type="submit" variant="primary" loading={save.isPending} disabled={mode === 'cabinet' && !dirty}>
            {mode === 'wizard' ? COMPANY.saveContinue : COMPANY.save}
          </Button>
        </StickyActionBar>
      </form>
    </div>
  )
}
