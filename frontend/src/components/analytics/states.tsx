import { Info } from "lucide-react"

import { cn } from "@/lib/utils"

/** Leegstaat in een gestippelde kaart (nog geen klant gekozen, geen data). */
export function EmptyState({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("rounded-lg border border-dashed bg-card px-6 py-10 text-center text-sm text-muted-foreground", className)}>
      {children}
    </div>
  )
}

/** Geen klant in het adres en geen laatst gekozen klant: kiezen gaat via de sidebar. */
export function NoCustomerState() {
  return <EmptyState>Kies linksboven een klant om Analytics te zien.</EmptyState>
}

/** Foutmelding van de backend als gewone melding (geen crash). */
export function ErrorNote({ children }: { children: React.ReactNode }) {
  return (
    <p role="alert" className="rounded-md border border-red-300 bg-card px-3 py-2 text-sm text-red-700 dark:text-red-300">
      {children}
    </p>
  )
}

/** Toelichtingen in gewone taal, elk met een info-icoon. */
export function InfoNotes({ notes, className }: { notes: string[]; className?: string }) {
  if (notes.length === 0) return null
  return (
    <ul className={cn("space-y-1.5 text-sm text-muted-foreground", className)}>
      {notes.map((note) => (
        <li key={note} className="flex items-start gap-2">
          <Info className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span>{note}</span>
        </li>
      ))}
    </ul>
  )
}

/** Opvallende mededeling in een wit vlak (bijv. "er is nog maar één meting"). */
export function Notice({ children }: { children: React.ReactNode }) {
  return (
    <p className="flex items-start gap-2 rounded-lg border bg-card px-4 py-3 text-sm text-muted-foreground">
      <Info className="mt-0.5 size-4 shrink-0" aria-hidden />
      <span>{children}</span>
    </p>
  )
}
