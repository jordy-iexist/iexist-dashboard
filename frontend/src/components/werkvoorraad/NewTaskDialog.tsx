"use client"

// Dialoog "Nieuwe taak": een eigen taak op de werkvoorraad (titel en klant verplicht).

import { useState } from "react"

import { selectClass } from "@/components/klanten/analyses/form-controls"
import { fieldClassName } from "@/components/settings/SettingsSection"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import {
  KINDS,
  type WorkBoardCustomer,
  type WorkBoardUser,
  type WorkCardCreate,
  type WorkKind,
  type WorkStatus,
} from "@/lib/work-queue"
import { cn } from "@/lib/utils"

const DEFAULT_KIND: WorkKind = "content"

const labelClass = "text-sm font-medium"

type Defaults = { customerId: string | null; status: WorkStatus; assigneeId: string | null }

export function NewTaskDialog({
  open,
  onOpenChange,
  customers,
  users,
  defaults,
  onCreate,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  customers: WorkBoardCustomer[]
  users: WorkBoardUser[]
  defaults: Defaults
  onCreate: (body: WorkCardCreate) => Promise<boolean>
}) {
  const [title, setTitle] = useState("")
  const [customerId, setCustomerId] = useState(defaults.customerId ?? "")
  const [kind, setKind] = useState<WorkKind>(DEFAULT_KIND)
  const [assigneeId, setAssigneeId] = useState(defaults.assigneeId ?? "")
  const [note, setNote] = useState("")
  const [saving, setSaving] = useState(false)
  const [failed, setFailed] = useState(false)

  // Bij openen met een leeg formulier de klant en medewerker uit het bordfilter overnemen.
  const [prevOpen, setPrevOpen] = useState(open)
  if (open !== prevOpen) {
    setPrevOpen(open)
    if (open && !title && !note) {
      setCustomerId(defaults.customerId ?? "")
      setAssigneeId(defaults.assigneeId ?? "")
      setKind(DEFAULT_KIND)
      setFailed(false)
    }
  }

  const customerKnown = customers.some((customer) => customer.id === customerId)
  // Het bordfilter kan "niet toegewezen" (`none`) of een onbekend id zijn: dan niemand.
  const assigneeValue = users.some((user) => user.id === assigneeId) ? assigneeId : ""
  const canSubmit = title.trim() !== "" && customerId !== "" && customerKnown && !saving

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!canSubmit) return
    setSaving(true)
    setFailed(false)
    const ok = await onCreate({
      title: title.trim(),
      customer_id: customerId,
      kind,
      status: defaults.status,
      assignee_id: assigneeValue || null,
      note: note.trim() || null,
    })
    setSaving(false)
    if (!ok) {
      setFailed(true)
      return
    }
    setTitle("")
    setNote("")
    setKind(DEFAULT_KIND)
    setCustomerId(defaults.customerId ?? "")
    setAssigneeId(defaults.assigneeId ?? "")
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !saving && onOpenChange(next)}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Nieuwe taak</DialogTitle>
          <DialogDescription>Een eigen taak op de werkvoorraad.</DialogDescription>
        </DialogHeader>

        <form className="space-y-4" onSubmit={(event) => void submit(event)}>
          <div className="space-y-1.5">
            <label htmlFor="new-task-title" className={labelClass}>
              Titel
            </label>
            <Input
              id="new-task-title"
              value={title}
              required
              maxLength={300}
              autoFocus
              onChange={(event) => setTitle(event.target.value)}
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="new-task-customer" className={labelClass}>
              Klant
            </label>
            <select
              id="new-task-customer"
              className={selectClass}
              value={customerKnown ? customerId : ""}
              required
              onChange={(event) => setCustomerId(event.target.value)}
            >
              <option value="" disabled>
                Kies een klant
              </option>
              {customers.map((customer) => (
                <option key={customer.id} value={customer.id}>
                  {customer.name}
                </option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label htmlFor="new-task-kind" className={labelClass}>
                Soort
              </label>
              <select
                id="new-task-kind"
                className={selectClass}
                value={kind}
                onChange={(event) => setKind(event.target.value as WorkKind)}
              >
                {KINDS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <label htmlFor="new-task-assignee" className={labelClass}>
                Medewerker
              </label>
              <select
                id="new-task-assignee"
                className={selectClass}
                value={assigneeValue}
                onChange={(event) => setAssigneeId(event.target.value)}
              >
                <option value="">Niet toegewezen</option>
                {users.map((user) => (
                  <option key={user.id} value={user.id}>
                    {user.name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="space-y-1.5">
            <label htmlFor="new-task-note" className={labelClass}>
              Notitie
            </label>
            <textarea
              id="new-task-note"
              rows={3}
              className={cn(fieldClassName, "resize-y")}
              value={note}
              onChange={(event) => setNote(event.target.value)}
            />
          </div>

          {failed && (
            <p role="alert" className="text-xs text-red-700 dark:text-red-400">
              Aanmaken mislukt
            </p>
          )}

          <DialogFooter>
            <Button type="button" variant="outline" disabled={saving} onClick={() => onOpenChange(false)}>
              Annuleren
            </Button>
            <Button type="submit" disabled={!canSubmit} className="font-semibold">
              {saving ? "Toevoegen…" : "Taak toevoegen"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
