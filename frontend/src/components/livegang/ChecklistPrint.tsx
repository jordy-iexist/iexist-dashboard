"use client"

import { Printer } from "lucide-react"
import { useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { EffectiveIcon } from "@/components/livegang/ChecklistTab"
import { AutoStatusBadge, PercentRing } from "@/components/livegang/shared"
import { apiFetch, formatDateTime, MANUAL_STATUS_LABELS, type Checklist } from "@/lib/launch-checklist"

// Verberg de dashboard-chrome (sidebar, header) bij afdrukken.
const PRINT_CSS = `
@media print {
  [data-slot="sidebar"], [data-slot="sidebar-gap"], [data-slot="sidebar-container"], main > header { display: none !important; }
  main > div { padding: 0 !important; }
  .checklist-section { break-inside: avoid-page; }
  .checklist-item { break-inside: avoid; }
  @page { margin: 14mm; }
}
`

export function ChecklistPrint({ customerId, phase = 2 }: { customerId: string; phase?: 2 | 3 }) {
  const [checklist, setChecklist] = useState<Checklist | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    apiFetch<Checklist>(`/customers/${customerId}/${phase === 3 ? "content-checklist" : "checklist"}`)
      .then(setChecklist)
      .catch((err: Error) => setError(err.message))
  }, [customerId, phase])

  if (error) return <p className="rounded-md border border-red-300 px-3 py-2 text-sm text-red-700">{error}</p>
  if (!checklist) return <p className="text-sm text-muted-foreground">Checklist laden…</p>

  return (
    <div className="mx-auto w-full max-w-4xl space-y-6 print:max-w-none">
      <style>{PRINT_CSS}</style>

      <header className="flex flex-wrap items-start gap-4 border-b pb-4">
        <div className="min-w-0 flex-1">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            {phase === 3 ? "Livegang fase 3 · Contentcreatie & onpage optimalisatie" : "Livegang fase 2 · GEO/SEO-checklist"}
          </p>
          <h1 className="text-2xl font-bold text-primary">{checklist.customer_name}</h1>
          <p className="text-sm text-muted-foreground">{checklist.base_url}</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {checklist.scan ? `Scan: ${formatDateTime(checklist.scan.completed_at)}` : "Nog niet gescand"} · Afgedrukt:{" "}
            {formatDateTime(new Date().toISOString())}
            {checklist.is_webshop ? " · Webshop" : ""}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <PercentRing percent={checklist.percent} size={72} />
          <p className="text-sm">
            {checklist.done} / {checklist.total}
            <br />
            <span className="text-xs text-muted-foreground">afgerond</span>
          </p>
        </div>
        <Button onClick={() => window.print()} className="print:hidden">
          <Printer /> Afdrukken / opslaan als PDF
        </Button>
      </header>

      {checklist.sections.map((section) => (
        <section key={section.key} className="checklist-section space-y-2">
          <h2 className="flex items-baseline justify-between border-b pb-1 text-base font-semibold">
            {section.label}
            <span className="text-xs font-normal text-muted-foreground">
              {section.done} / {section.total}
            </span>
          </h2>
          <ul className="space-y-2">
            {section.items.map((item) => (
              <li key={item.key} className="checklist-item flex gap-3 text-sm">
                <EffectiveIcon item={item} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={item.effective === "nvt" ? "text-muted-foreground line-through" : "font-medium"}>{item.label}</span>
                    {item.mode !== "manual" && <AutoStatusBadge status={item.auto?.status} />}
                    {item.manual_status && (
                      <span className="text-xs text-muted-foreground">Handmatig: {MANUAL_STATUS_LABELS[item.manual_status]}</span>
                    )}
                  </div>
                  {item.auto?.message && <p className="text-xs text-muted-foreground">{item.auto.message}</p>}
                  {item.note && <p className="text-xs italic">Notitie: {item.note}</p>}
                </div>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  )
}
