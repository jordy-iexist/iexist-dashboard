// Gedeelde formulierbouwstenen voor de concurrentieanalyse (wizard en resultaat): native
// select, checkbox en een schakelaar. Zonder "use client", zodat ook server-componenten de
// klasse-strings kunnen gebruiken; `Switch` heeft een klikhandler en hoort in client-componenten.

import { cn } from "@/lib/utils"

/** Native `<select>`, zelfde stijl als de filters in Analytics. */
export const selectClass =
  "h-9 w-full min-w-0 rounded-md border border-input bg-card px-3 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-input/30"

/** Native `<input type="checkbox">`, zoals in de Quick wins-tabel. */
export const checkboxClass =
  "block size-4 shrink-0 cursor-pointer rounded-[4px] accent-primary disabled:cursor-not-allowed disabled:opacity-50"

/**
 * Schakelaar (`role="switch"`), zelfde vorm als de dagelijkse controle in de monitor.
 * Met `label` staat de tekst ernaast en is die ook klikbaar; anders is `aria-label` nodig.
 */
export function Switch({
  checked,
  onCheckedChange,
  disabled = false,
  label,
  id,
  className,
  "aria-label": ariaLabel,
}: {
  checked: boolean
  onCheckedChange: (checked: boolean) => void
  disabled?: boolean
  label?: React.ReactNode
  id?: string
  className?: string
  "aria-label"?: string
}) {
  const button = (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      disabled={disabled}
      onClick={() => onCheckedChange(!checked)}
      className={cn(
        "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50",
        checked ? "bg-primary" : "bg-muted-foreground/30",
        !label && className
      )}
    >
      <span
        className={cn(
          "inline-block size-4 rounded-full bg-background shadow-xs transition-transform",
          checked ? "translate-x-4.5" : "translate-x-0.5"
        )}
      />
    </button>
  )

  if (!label) return button
  return (
    <label className={cn("flex items-center gap-2 text-sm", disabled && "opacity-70", className)}>
      {button}
      <span className="font-medium">{label}</span>
    </label>
  )
}
