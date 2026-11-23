"use client"

import * as React from "react"
import Link from "next/link"
import { usePathname, useRouter } from "next/navigation"
import { Check, ChevronsUpDown, Plus, Users } from "lucide-react"

import { Input } from "@/components/ui/input"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { useSidebar } from "@/components/ui/sidebar"
import { persistActiveCustomer, switchHref } from "@/lib/active-customer"
import { type CustomersResponse } from "@/lib/customer-types"
import { cn } from "@/lib/utils"

export type CustomerOption = {
  id: string
  name: string
  domain: string
}

// Haalt de actuele klantenlijst op via de API-route; null bij een fout.
export async function fetchCustomerOptions(): Promise<CustomerOption[] | null> {
  try {
    const response = await fetch("/api/customers", { cache: "no-store" })
    if (!response.ok) return null
    const payload = (await response.json()) as Partial<CustomersResponse>
    if (!Array.isArray(payload.websites)) return null
    return payload.websites.map(({ id, name, domain }) => ({ id, name, domain }))
  } catch {
    return null
  }
}

function initialOf(customer: CustomerOption): string {
  return (customer.name.trim() || customer.domain.trim() || "?")
    .charAt(0)
    .toUpperCase()
}

export function CustomerSwitcher({
  customers,
  activeCustomerId,
  onCustomersChange,
}: {
  customers: CustomerOption[]
  activeCustomerId: string | null
  onCustomersChange?: (customers: CustomerOption[]) => void
}) {
  const router = useRouter()
  const pathname = usePathname()
  const { state, isMobile, setOpen: setSidebarOpen, setOpenMobile } =
    useSidebar()
  const [open, setOpen] = React.useState(false)
  const [query, setQuery] = React.useState("")

  const collapsed = state === "collapsed" && !isMobile
  const active = activeCustomerId
    ? customers.find((customer) => customer.id === activeCustomerId) ?? null
    : null

  const results = React.useMemo(() => {
    const needle = query.trim().toLowerCase()
    return customers
      .filter(
        (customer) =>
          !needle ||
          customer.name.toLowerCase().includes(needle) ||
          customer.domain.toLowerCase().includes(needle)
      )
      .sort((a, b) => a.name.localeCompare(b.name, "nl"))
  }, [customers, query])

  const handleOpenChange = (next: boolean) => {
    setOpen(next)
    if (!next) return
    setQuery("")
    // Opnieuw ophalen, zodat een net aangemaakte klant erbij staat.
    void fetchCustomerOptions().then((fresh) => {
      if (fresh) onCustomersChange?.(fresh)
    })
  }

  // Ingeklapt tot iconen: eerst de sidebar uitklappen (zoals bij Livegang).
  const handleTriggerClick = (event: React.MouseEvent) => {
    if (!collapsed) return
    event.preventDefault()
    setSidebarOpen(true)
  }

  const closeAll = () => {
    setOpen(false)
    if (isMobile) setOpenMobile(false)
  }

  const selectCustomer = (customerId: string) => {
    persistActiveCustomer(customerId)
    closeAll()
    router.push(switchHref(pathname, customerId))
  }

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter" && results[0]) {
      event.preventDefault()
      selectCustomer(results[0].id)
    }
  }

  const label = active
    ? active.name
    : activeCustomerId
      ? "Klant laden…"
      : "Kies een klant"

  return (
    // Op mobiel staat de sidebar in een sheet (dialog): modal laat focus en
    // scrollen in de popover dan werken.
    <Popover open={open} onOpenChange={handleOpenChange} modal={isMobile}>
      <PopoverTrigger asChild onClick={handleTriggerClick}>
        <button
          type="button"
          title={collapsed ? active?.name ?? "Kies een klant" : undefined}
          aria-label={collapsed ? label : undefined}
          className={cn(
            "flex w-full min-w-0 items-center gap-2 rounded-lg p-1.5 text-left text-white/85 outline-hidden transition-colors hover:bg-white/10 hover:text-white focus-visible:ring-2 focus-visible:ring-white/30 data-[state=open]:bg-white/10",
            "group-data-[collapsible=icon]:size-8 group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:p-0"
          )}
        >
          <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-white/15 text-xs font-semibold text-white">
            {active ? initialOf(active) : <Users className="size-4" />}
          </span>
          <span className="flex min-w-0 flex-1 flex-col gap-0.5 leading-none group-data-[collapsible=icon]:hidden">
            <span className="truncate text-[13px] font-medium text-white">
              {label}
            </span>
            {active?.domain && (
              <span className="truncate text-xs text-white/50">
                {active.domain}
              </span>
            )}
          </span>
          <ChevronsUpDown className="size-4 shrink-0 text-white/60 group-data-[collapsible=icon]:hidden" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="w-(--radix-popover-trigger-width) min-w-64 p-0"
      >
        <div className="border-b p-2">
          <Input
            autoFocus
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Zoek op naam of domein"
            aria-label="Zoek klant"
            className="h-8"
          />
        </div>
        <div className="max-h-72 overflow-y-auto p-1" role="listbox">
          {results.length === 0 ? (
            <p className="px-2 py-6 text-center text-sm text-muted-foreground">
              Geen klanten gevonden
            </p>
          ) : (
            results.map((customer) => {
              const isActive = customer.id === activeCustomerId
              return (
                <button
                  key={customer.id}
                  type="button"
                  role="option"
                  aria-selected={isActive}
                  onClick={() => selectCustomer(customer.id)}
                  className={cn(
                    "flex w-full min-w-0 items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm outline-hidden hover:bg-accent focus-visible:bg-accent",
                    isActive && "bg-accent font-medium"
                  )}
                >
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="truncate">{customer.name}</span>
                    {customer.domain && (
                      <span className="truncate text-xs text-muted-foreground">
                        {customer.domain}
                      </span>
                    )}
                  </span>
                  {isActive && <Check className="size-4 shrink-0" />}
                </button>
              )
            })
          )}
        </div>
        <div className="flex flex-col border-t p-1">
          <Link
            href="/dashboard/klanten"
            onClick={closeAll}
            className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-accent"
          >
            <Users className="size-4 text-muted-foreground" />
            Klanten beheren
          </Link>
          <Link
            href="/dashboard/klanten/nieuw"
            onClick={closeAll}
            className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-accent"
          >
            <Plus className="size-4 text-muted-foreground" />
            Nieuwe klant
          </Link>
        </div>
      </PopoverContent>
    </Popover>
  )
}
