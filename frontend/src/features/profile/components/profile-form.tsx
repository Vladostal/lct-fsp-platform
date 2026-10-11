import { zodResolver } from '@hookform/resolvers/zod'
import { useQueryClient } from '@tanstack/react-query'
import { useBlocker, useNavigate } from '@tanstack/react-router'
import { Lock } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { type FieldPath, useForm } from 'react-hook-form'
import { toast } from 'sonner'
import type { CandidateProfileView, Catalog, ConditionsView, ResumeParseResult } from '@/client'
import { Section, StickyActionBar, TagInput, type TagOption, type TagValue } from '@/components/app'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { WORK_FORMAT_LABELS } from '@/content/common'
import { applyFieldErrors, errorMessage } from '@/lib/api'
import { formatTime } from '@/lib/format'
import { invalidateGuardData } from '@/lib/guards'
import { conditionsQuery, saveConditions, saveProfile, uploadResume } from '../api'
import { PROFILE } from '../content'
import {
  defaultValues,
  LIMITS,
  type ProfileFormValues,
  profileFormSchema,
  RESUME_KEY_BY_FIELD,
  RESUME_KEYS,
  toConditionsUpdate,
  toProfileUpdate,
  WORK_FORMATS,
} from '../schemas'
import { MinSalarySelect } from './min-salary-select'
import { ResumeDropzone, type ResumeStatus } from './resume-dropzone'

type Confidence = 'high' | 'medium' | 'low'
type FieldName = keyof ProfileFormValues

export type ProfileFormProps = {
  mode: 'wizard' | 'cabinet'
  profile: CandidateProfileView
  conditions: ConditionsView
  catalog: Catalog | null
  userId: string
  /** Код категории — для ориентира рынка рядом с минимумом. */
  category?: string | null
  /** Вызывается после успешного сохранения обоих запросов. */
  onSaved?: () => void | Promise<void>
}

const draftKey = (userId: string) => `onboarding:profile:${userId}`

function readDraft(userId: string): Partial<ProfileFormValues> | null {
  try {
    const raw = sessionStorage.getItem(draftKey(userId))
    return raw ? (JSON.parse(raw) as Partial<ProfileFormValues>) : null
  } catch {
    return null
  }
}

function writeDraft(userId: string, values: unknown | null) {
  try {
    if (values) sessionStorage.setItem(draftKey(userId), JSON.stringify(values))
    else sessionStorage.removeItem(draftKey(userId))
  } catch {
    // хранилище недоступно — черновик не сохраняется
  }
}

const toTags = (value: unknown, max: number): TagValue[] | null =>
  Array.isArray(value)
    ? value.slice(0, max).map((item: { code: string; title: string }) => ({ code: item.code, title: item.title }))
    : null

function FromResumeMark({ confidence }: { confidence?: Confidence }) {
  if (!confidence) return null
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <span className="type-caption text-brand-600">{PROFILE.resume.chip}</span>
      {confidence === 'low' ? <span className="type-caption text-warning">{PROFILE.resume.check}</span> : null}
    </span>
  )
}

/**
 * Форма профиля кандидата (C1 и C11): основное, контакты, заявленный опыт, условия, загрузка резюме.
 * Сохранение — два запроса: профиль, затем условия; их сбои обрабатываются раздельно.
 */
export function ProfileForm({ mode, profile, conditions, catalog, userId, category, onSaved }: ProfileFormProps) {
  const T = PROFILE
  const wizard = mode === 'wizard'
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const base = useMemo(() => defaultValues(profile, conditions), [profile, conditions])
  const form = useForm<ProfileFormValues>({
    resolver: zodResolver(profileFormSchema),
    defaultValues: wizard ? { ...base, ...readDraft(userId) } : base,
  })
  const { isDirty } = form.formState

  // Поля, которых пользователь коснулся сам (по событию change; setValue его не вызывает).
  const touched = useRef(new Set<FieldName>())
  const [fromResume, setFromResume] = useState<Partial<Record<FieldName, Confidence>>>({})
  const [resume, setResume] = useState<{ uploadId: string; fileName: string | null } | null>(null)
  const [resumeStatus, setResumeStatus] = useState<ResumeStatus>('idle')
  const [resumeError, setResumeError] = useState<unknown>(null)
  const [resumeResult, setResumeResult] = useState<ResumeParseResult | null>(null)
  const [skipped, setSkipped] = useState(0)
  const [saving, setSaving] = useState(false)
  const [conditionsError, setConditionsError] = useState<unknown>(null)
  const [retrying, setRetrying] = useState(false)
  const [savedAt, setSavedAt] = useState<Date | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)

  useEffect(() => {
    const subscription = form.watch((values, { name, type }) => {
      if (type === 'change' && name) {
        const field = name.split('.')[0] as FieldName
        touched.current.add(field)
        setFromResume((current) => {
          if (!current[field]) return current
          const { [field]: _removed, ...rest } = current
          return rest
        })
      }
      if (wizard) writeDraft(userId, values)
    })
    return () => subscription.unsubscribe()
  }, [form, wizard, userId])

  useBlocker({
    shouldBlockFn: () => isDirty && !saving && !window.confirm(T.cabinet.leave),
    enableBeforeUnload: () => !wizard && isDirty,
    disabled: wizard,
  })

  const roleOptions: TagOption[] = useMemo(
    () => (catalog?.roles ?? []).map((r) => ({ code: r.code, title: r.title })),
    [catalog],
  )
  const skillOptions = useMemo(() => {
    const all = catalog?.skills ?? []
    const make = (list: typeof all): TagOption[] =>
      list.map((s) => ({ code: s.code, title: s.title, aliases: s.aliases }))
    return { stack: make(all.filter((s) => s.kind !== 'soft')), soft: make(all.filter((s) => s.kind === 'soft')) }
  }, [catalog])

  const applyResume = useCallback(
    (result: ResumeParseResult) => {
      let notReplaced = 0
      const marks: Partial<Record<FieldName, Confidence>> = {}
      for (const [key, field] of Object.entries(result.fields)) {
        const target = RESUME_KEYS[key]
        if (!target) continue // email, grade_hint, specialization_hint в форму не попадают
        if (touched.current.has(target)) {
          notReplaced += 1
          continue
        }
        let next: unknown
        if (target === 'roles') next = toTags(field.value, LIMITS.roles)
        else if (target === 'stack') next = toTags(field.value, LIMITS.stack)
        else if (target === 'soft') next = toTags(field.value, LIMITS.soft)
        else next = typeof field.value === 'string' || typeof field.value === 'number' ? String(field.value) : null
        if (next == null) continue
        form.setValue(target as FieldPath<ProfileFormValues>, next as never, {
          shouldDirty: true,
          shouldValidate: true,
        })
        marks[target] = field.confidence
      }
      setFromResume(marks)
      setSkipped(notReplaced)
    },
    [form],
  )

  const onFile = async (file: File) => {
    setResumeError(null)
    setResumeStatus('uploading')
    const timer = window.setTimeout(() => setResumeStatus('parsing'), 700)
    try {
      const result = await uploadResume(file)
      setResumeStatus('parsing')
      setResumeResult(result)
      setResume({ uploadId: result.upload_id, fileName: file.name })
      applyResume(result)
      setResumeStatus('parsed')
    } catch (error) {
      setResumeError(error)
      setResumeStatus(resume ? 'parsed' : 'idle')
    } finally {
      window.clearTimeout(timer)
    }
  }

  const finish = async (values: ProfileFormValues) => {
    writeDraft(userId, null)
    setSavedAt(new Date())
    form.reset(values)
    touched.current.clear()
    await invalidateGuardData(queryClient)
    if (wizard) await navigate({ to: '/candidate/onboarding/survey' })
    else toast.success(T.cabinet.saved)
    await onSaved?.()
  }

  const onSubmit = form.handleSubmit(async (values) => {
    setSaveError(null)
    setConditionsError(null)
    setSaving(true)
    const accepted = Object.keys(fromResume)
      .map((field) => RESUME_KEY_BY_FIELD[field as FieldName])
      .filter((key): key is string => Boolean(key))
    try {
      try {
        const saved = await saveProfile(
          toProfileUpdate(values, resume ? { uploadId: resume.uploadId, acceptedFields: accepted } : null),
        )
        queryClient.setQueryData(['candidate', 'profile'], saved)
      } catch (error) {
        applyFieldErrors(error, form.setError, [
          'last_name',
          'first_name',
          'middle_name',
          'city',
          'phone',
          'telegram',
          'link',
          'experience_years',
          'about',
        ])
        setSaveError(errorMessage(error))
        return
      }
      try {
        // Кэш условий обновляется сразу: иначе при возврате на экран форма открылась бы с прежними значениями
        // и следующее сохранение вернуло бы их на сервер.
        queryClient.setQueryData(conditionsQuery().queryKey, await saveConditions(toConditionsUpdate(values)))
      } catch (error) {
        setConditionsError(error)
        return
      }
      await finish(values)
    } finally {
      setSaving(false)
    }
  })

  const retryConditions = async () => {
    setRetrying(true)
    try {
      const values = form.getValues()
      queryClient.setQueryData(conditionsQuery().queryKey, await saveConditions(toConditionsUpdate(values)))
      setConditionsError(null)
      await finish(values)
    } catch (error) {
      setConditionsError(error)
    } finally {
      setRetrying(false)
    }
  }

  const textField = (
    name: FieldName & ('last_name' | 'first_name' | 'middle_name' | 'city' | 'phone' | 'telegram' | 'link'),
    opts: {
      required?: boolean
      autoComplete?: string
      type?: string
      inputMode?: 'tel' | 'url' | 'text'
      maxLength?: number
    } = {},
  ) => (
    <FormField
      control={form.control}
      name={name}
      render={({ field }) => (
        <FormItem className="min-w-0">
          <FormLabel className="flex flex-wrap items-center gap-x-2">
            {T.fields[name]}
            {opts.required ? <span aria-hidden="true">*</span> : null}
            <FromResumeMark confidence={fromResume[name]} />
          </FormLabel>
          <FormControl>
            <Input
              {...field}
              type={opts.type}
              inputMode={opts.inputMode}
              autoComplete={opts.autoComplete}
              maxLength={opts.maxLength}
            />
          </FormControl>
          <FormMessage />
        </FormItem>
      )}
    />
  )

  const tagField = (name: 'roles' | 'stack' | 'soft', options: TagOption[], max: number, allowCustom: boolean) => (
    <FormField
      control={form.control}
      name={name}
      render={({ field }) => (
        <FormItem className="min-w-0">
          <TagInput
            label={T.fields[name]}
            value={field.value}
            onChange={field.onChange}
            options={options}
            max={max}
            allowCustom={allowCustom}
            customMaxLength={LIMITS.customTag}
            customHint={allowCustom ? T.customHint : undefined}
          />
          <FromResumeMark confidence={fromResume[name]} />
          <FormMessage />
        </FormItem>
      )}
    />
  )

  const aboutLength = form.watch('about').length

  return (
    <div className="flex min-w-0 flex-col gap-6">
      {wizard || mode === 'cabinet' ? (
        <Card>
          <CardHeader>
            <CardTitle>{T.resume.title}</CardTitle>
          </CardHeader>
          <ResumeDropzone status={resumeStatus} error={resumeError} fileName={resume?.fileName} onFile={onFile} />
          {resumeResult && resumeStatus === 'parsed' ? (
            <div className="mt-3 flex min-w-0 flex-col gap-2">
              <Alert variant="success">
                <AlertDescription>{T.resume.parsed(resumeResult.recognized, resumeResult.total)}</AlertDescription>
              </Alert>
              {resumeResult.unknown_terms.length ? (
                <p className="type-caption min-w-0 text-ink-muted [overflow-wrap:anywhere]">
                  {T.resume.unknown}: <span className="num">{resumeResult.unknown_terms.join(', ')}</span>
                </p>
              ) : null}
              {skipped ? <p className="type-caption text-ink-muted">{T.resume.skipped(skipped)}</p> : null}
            </div>
          ) : null}
        </Card>
      ) : null}

      <Form {...form}>
        <form id="profile-form" onSubmit={onSubmit} noValidate className="flex min-w-0 flex-col gap-6">
          <Card className="gap-8">
            <Section title={T.sections.main}>
              <div className="grid min-w-0 gap-4 sm:grid-cols-2">
                {textField('last_name', { required: true, autoComplete: 'family-name', maxLength: 60 })}
                {textField('first_name', { required: true, autoComplete: 'given-name', maxLength: 60 })}
                {textField('middle_name', { autoComplete: 'additional-name', maxLength: 60 })}
                {textField('city', { autoComplete: 'address-level2', maxLength: 80 })}
              </div>
            </Section>

            <Section title={`${T.sections.contacts} · ${T.sections.contactsNote}`}>
              <div className="grid min-w-0 gap-4 sm:grid-cols-2">
                <div className="flex min-w-0 flex-col gap-1.5">
                  <span className="type-sm font-medium text-ink">{T.fields.email}</span>
                  <Input value={profile.email} readOnly aria-readonly="true" className="bg-fill" />
                  <span className="type-caption text-ink-muted">{T.fields.emailNote}</span>
                </div>
                {textField('phone', { type: 'tel', inputMode: 'tel', autoComplete: 'tel' })}
                {textField('telegram', { autoComplete: 'off' })}
                {textField('link', { inputMode: 'url', autoComplete: 'url' })}
              </div>
            </Section>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex flex-wrap items-baseline gap-2">
                {T.sections.experience}
                <span className="type-sm font-normal text-ink-muted">· {T.sections.declared}</span>
              </CardTitle>
            </CardHeader>
            <div className="flex min-w-0 flex-col gap-4">
              <FormField
                control={form.control}
                name="experience_years"
                render={({ field }) => (
                  <FormItem className="min-w-0 max-w-[200px]">
                    <FormLabel className="flex flex-wrap items-center gap-x-2">
                      {T.fields.experience_years}
                      <FromResumeMark confidence={fromResume.experience_years} />
                    </FormLabel>
                    <FormControl>
                      <Input {...field} type="number" inputMode="decimal" min={0} max={40} step={0.5} className="num" />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              {tagField('roles', roleOptions, LIMITS.roles, false)}
              {tagField('stack', skillOptions.stack, LIMITS.stack, true)}
              {tagField('soft', skillOptions.soft, LIMITS.soft, false)}
              <FormField
                control={form.control}
                name="about"
                render={({ field }) => (
                  <FormItem className="min-w-0">
                    <FormLabel className="flex flex-wrap items-center gap-x-2">
                      {T.fields.about}
                      <FromResumeMark confidence={fromResume.about} />
                    </FormLabel>
                    <FormControl>
                      <Textarea {...field} rows={5} className="min-h-28" />
                    </FormControl>
                    <div className="flex min-w-0 flex-wrap justify-between gap-x-3 gap-y-1">
                      <span className="type-caption min-w-0 text-ink-muted">{T.aboutNote}</span>
                      <span className="type-caption num text-ink-muted">
                        {aboutLength} / {LIMITS.about}
                      </span>
                    </div>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>
          </Card>

          <Card id="conditions">
            <CardHeader>
              <CardTitle>{T.sections.conditions}</CardTitle>
            </CardHeader>
            <div className="flex min-w-0 flex-col gap-6">
              <section className="flex min-w-0 flex-col gap-4" aria-labelledby="cond-visible">
                <h3 id="cond-visible" className="type-h3">
                  {T.sections.visibleToEmployers}
                </h3>
                <FormField
                  control={form.control}
                  name="work_formats"
                  render={({ field }) => (
                    <FormItem className="min-w-0">
                      <fieldset className="flex min-w-0 flex-col gap-2">
                        <legend className="type-sm mb-1 font-medium text-ink">
                          {T.fields.work_formats} <span aria-hidden="true">*</span>
                        </legend>
                        <div className="flex flex-wrap gap-x-6 gap-y-1">
                          {WORK_FORMATS.map((format) => (
                            <label
                              key={format}
                              htmlFor={`work-format-${format}`}
                              className="type-body flex min-h-11 cursor-pointer items-center gap-2"
                            >
                              <Checkbox
                                id={`work-format-${format}`}
                                checked={field.value.includes(format)}
                                onCheckedChange={(checked) =>
                                  field.onChange(
                                    checked
                                      ? WORK_FORMATS.filter((f) => f === format || field.value.includes(f))
                                      : field.value.filter((f) => f !== format),
                                  )
                                }
                              />
                              {WORK_FORMAT_LABELS[format]}
                            </label>
                          ))}
                        </div>
                      </fieldset>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="relocation_ready"
                  render={({ field }) => (
                    <FormItem className="min-w-0">
                      <label
                        htmlFor="relocation-ready"
                        className="type-body flex min-h-11 min-w-0 cursor-pointer items-center gap-3"
                      >
                        <Switch id="relocation-ready" checked={field.value} onCheckedChange={field.onChange} />
                        {T.fields.relocation_ready}
                      </label>
                    </FormItem>
                  )}
                />
              </section>

              <section className="flex min-w-0 flex-col gap-3 border-t border-line pt-5" aria-labelledby="cond-private">
                <h3 id="cond-private" className="type-h3 flex items-center gap-2">
                  <Lock className="size-4 text-ink-muted" aria-hidden="true" />
                  {T.sections.visibleToNobody}
                </h3>
                <FormField
                  control={form.control}
                  name="min_salary"
                  render={({ field }) => (
                    <MinSalarySelect
                      value={field.value}
                      onChange={field.onChange}
                      category={category}
                      showFutureNote={!wizard}
                    />
                  )}
                />
              </section>
            </div>
          </Card>
        </form>
      </Form>

      {conditionsError ? (
        <Alert variant="warning" data-testid="conditions-failed">
          <AlertTitle>{T.conditionsFailed.title}</AlertTitle>
          <AlertDescription>
            <span className="block">{errorMessage(conditionsError)}</span>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              className="mt-2"
              loading={retrying}
              onClick={retryConditions}
            >
              {T.conditionsFailed.retry}
            </Button>
          </AlertDescription>
        </Alert>
      ) : null}
      {saveError ? (
        <Alert variant="destructive">
          <AlertDescription>{saveError}</AlertDescription>
        </Alert>
      ) : null}

      <StickyActionBar
        width={wizard ? 'wizard' : 'page'}
        note={savedAt ? <span className="num">{T.savedAt(formatTime(savedAt))}</span> : undefined}
      >
        <Button type="submit" form="profile-form" variant="primary" loading={saving} disabled={!wizard && !isDirty}>
          {wizard ? T.wizard.next : T.cabinet.save}
        </Button>
      </StickyActionBar>
    </div>
  )
}
