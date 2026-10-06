import { CircleAlert } from 'lucide-react'
import type { Label as LabelPrimitive } from 'radix-ui'
import { Slot } from 'radix-ui'
import * as React from 'react'
import {
  Controller,
  type ControllerProps,
  type FieldPath,
  type FieldValues,
  FormProvider,
  useFormContext,
  useFormState,
} from 'react-hook-form'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'

/*
 * Поля формы на react-hook-form (E §7): у каждого поля <label>; обязательное — «*» и aria-required;
 * подсказка и ошибка связаны aria-describedby; ошибка — иконка и текст, aria-invalid.
 */

const Form = FormProvider

type FormFieldContextValue<
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
> = {
  name: TName
}

const FormFieldContext = React.createContext<FormFieldContextValue | null>(null)

const FormField = <
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
>(
  props: ControllerProps<TFieldValues, TName>,
) => {
  return (
    <FormFieldContext.Provider value={{ name: props.name }}>
      <Controller {...props} />
    </FormFieldContext.Provider>
  )
}

type FormItemContextValue = {
  id: string
  /** Есть ли подсказка под полем: aria-describedby не должен ссылаться на отсутствующий элемент. */
  hasDescription: boolean
  setHasDescription: (value: boolean) => void
}

const FormItemContext = React.createContext<FormItemContextValue | null>(null)

const useFormField = () => {
  const fieldContext = React.useContext(FormFieldContext)
  const itemContext = React.useContext(FormItemContext)
  const { getFieldState } = useFormContext()
  const formState = useFormState({ name: fieldContext?.name })

  if (!fieldContext) {
    throw new Error('useFormField должен вызываться внутри <FormField>')
  }
  if (!itemContext) {
    throw new Error('useFormField должен вызываться внутри <FormItem>')
  }

  const fieldState = getFieldState(fieldContext.name, formState)
  const { id } = itemContext

  return {
    id,
    name: fieldContext.name,
    formItemId: `${id}-form-item`,
    formDescriptionId: `${id}-form-item-description`,
    formMessageId: `${id}-form-item-message`,
    hasDescription: itemContext.hasDescription,
    setHasDescription: itemContext.setHasDescription,
    ...fieldState,
  }
}

function FormItem({ className, ...props }: React.ComponentProps<'div'>) {
  const id = React.useId()
  const [hasDescription, setHasDescription] = React.useState(false)
  const value = React.useMemo(() => ({ id, hasDescription, setHasDescription }), [id, hasDescription])

  return (
    <FormItemContext.Provider value={value}>
      <div data-slot="form-item" className={cn('grid min-w-0 content-start gap-2', className)} {...props} />
    </FormItemContext.Provider>
  )
}

function FormLabel({
  className,
  required = false,
  children,
  ...props
}: React.ComponentProps<typeof LabelPrimitive.Root> & { required?: boolean }) {
  const { formItemId } = useFormField()

  return (
    <Label data-slot="form-label" className={className} htmlFor={formItemId} {...props}>
      <span className="min-w-0">
        {children}
        {required ? (
          <span className="text-danger" aria-hidden="true">
            {' '}
            *
          </span>
        ) : null}
      </span>
    </Label>
  )
}

function FormControl(props: React.ComponentProps<typeof Slot.Root>) {
  const { error, formItemId, formDescriptionId, formMessageId, hasDescription } = useFormField()
  const describedBy = [hasDescription ? formDescriptionId : null, error ? formMessageId : null]
    .filter(Boolean)
    .join(' ')

  return (
    <Slot.Root
      data-slot="form-control"
      id={formItemId}
      aria-describedby={describedBy || undefined}
      aria-invalid={error ? true : undefined}
      {...props}
    />
  )
}

function FormDescription({ className, ...props }: React.ComponentProps<'p'>) {
  const { formDescriptionId, setHasDescription } = useFormField()

  React.useEffect(() => {
    setHasDescription(true)
    return () => setHasDescription(false)
  }, [setHasDescription])

  return (
    <p
      data-slot="form-description"
      id={formDescriptionId}
      className={cn('type-sm text-ink-muted', className)}
      {...props}
    />
  )
}

function FormMessage({ className, children, ...props }: React.ComponentProps<'p'>) {
  const { error, formMessageId } = useFormField()
  const body = error ? String(error.message ?? '') : children

  if (!body) {
    return null
  }

  return (
    <p
      data-slot="form-message"
      id={formMessageId}
      className={cn('type-sm flex min-w-0 items-start gap-1.5 text-danger', className)}
      {...props}
    >
      <CircleAlert className="mt-0.5 size-4" aria-hidden="true" />
      <span className="min-w-0">{body}</span>
    </p>
  )
}

export { Form, FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage, useFormField }
