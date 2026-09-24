import Link from "next/link"
import { ChevronLeft } from "lucide-react"

import { cn } from "@/lib/utils"

// Shared styling for raw <textarea> and <select> elements, matching ui/input.
export const fieldClassName =
  "w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:opacity-50"

export function SettingsPageHeader({
  title,
  description,
}: {
  title: string
  description?: React.ReactNode
}) {
  return (
    <div className="space-y-1">
      <Link
        href="/dashboard/settings"
        className="mb-3 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground md:hidden"
      >
        <ChevronLeft className="size-4" />
        Instellingen
      </Link>
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      {description && (
        <p className="text-sm text-muted-foreground">{description}</p>
      )}
    </div>
  )
}

export function SettingsSection({
  title,
  description,
  children,
  className,
}: {
  title: string
  description?: React.ReactNode
  children: React.ReactNode
  className?: string
}) {
  return (
    <section
      className={cn(
        "grid gap-4 border-t py-8 first:border-t-0 first:pt-0 lg:grid-cols-[14rem_1fr] lg:gap-8",
        className
      )}
    >
      <div className="space-y-1">
        <h2 className="text-sm font-semibold">{title}</h2>
        {description && (
          <p className="text-sm text-muted-foreground">{description}</p>
        )}
      </div>
      <div className="min-w-0 space-y-5">{children}</div>
    </section>
  )
}

export function SettingsField({
  label,
  htmlFor,
  hint,
  children,
}: {
  label: string
  htmlFor?: string
  hint?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <div className="space-y-2">
      <label className="text-sm font-medium" htmlFor={htmlFor}>
        {label}
      </label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

export function SettingsFeedback({
  type,
  children,
}: {
  type: "success" | "error"
  children: React.ReactNode
}) {
  return (
    <div
      className={cn(
        "rounded-md border px-3 py-2 text-sm",
        type === "success"
          ? "border-green-200 bg-green-50 text-green-700"
          : "border-red-200 bg-red-50 text-red-700"
      )}
    >
      {children}
    </div>
  )
}
