"use client"

import { Pencil, Plus, Trash2 } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"
import {
  DataEditor,
  GridCellKind,
  type DataEditorRef,
  type EditableGridCell,
  type EditListItem,
  type GridCell,
  type GridColumn,
  type GridKeyEventArgs,
  type Item,
} from "@glideapps/glide-data-grid"
import "@glideapps/glide-data-grid/dist/index.css"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  type CustomerSheetResponse,
  type SheetColumn,
  type SheetRow,
} from "@/lib/customer-sheet-types"

type SheetRowState = {
  id: string
  title: string
  createdAt: string
  placed: boolean
  placedDate: string | null
  isOwner: boolean
  words: string | null
  anchor1: string | null
  anchor1Url: string | null
  anchor2: string | null
  anchor2Url: string | null
  placementUrl: string | null
} & Record<string, string | boolean | number | null | undefined>

type LastChange =
  | { kind: "cell"; rowIndex: number; columnId: string; blogId: string; prevValue: string }
  | {
      kind: "placed"
      rowIndex: number
      blogId: string
      prevPlaced: boolean
      prevPlacedDate: string | null
    }
  | { kind: "placementUrl"; rowIndex: number; blogId: string; prevValue: string }

type Feedback = {
  type: "success" | "error" | null
  message: string
}

type ErrorResponse = {
  error?: string
}

const FIXED_COLUMN_COUNT = 7
const PLACED_COLUMN_INDEX = 5
const PLACEMENT_URL_COLUMN_INDEX = 6
const PLACED_BG_COLOR = "#dcfce7"

function getErrorMessage(payload: ErrorResponse | null, fallback: string): string {
  return payload?.error?.trim() ? payload.error : fallback
}

function formatDate(value: string | null, withTime = false) {
  if (!value) {
    return "—"
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return "—"
  }
  return new Intl.DateTimeFormat("nl-NL", {
    dateStyle: "medium",
    ...(withTime ? { timeStyle: "short" } : {}),
  }).format(date)
}

function toRowState(row: SheetRow): SheetRowState {
  const state: SheetRowState = {
    id: row.id,
    title: row.title,
    createdAt: row.created_at,
    placed: Boolean(row.published_at),
    placedDate: row.published_at,
    isOwner: row.is_owner,
    words: row.words,
    anchor1: row.anchor_1,
    anchor1Url: row.anchor_1_url,
    anchor2: row.anchor_2,
    anchor2Url: row.anchor_2_url,
    placementUrl: row.placement_url,
  }
  for (const [columnId, value] of Object.entries(row.cells)) {
    state[columnId] = value ?? ""
  }
  return state
}

export function KlantSpreadsheet({ customerId }: { customerId: string }) {
  const [columns, setColumns] = useState<SheetColumn[]>([])
  const [rows, setRows] = useState<SheetRowState[]>([])
  const [columnWidths, setColumnWidths] = useState<Record<string, number>>({})
  const [isLoading, setIsLoading] = useState(true)
  const [feedback, setFeedback] = useState<Feedback>({ type: null, message: "" })
  const [lastChange, setLastChange] = useState<LastChange | null>(null)

  const rowsRef = useRef<SheetRowState[]>([])
  const columnsRef = useRef<SheetColumn[]>([])
  const gridRef = useRef<DataEditorRef>(null)

  const [isAddingColumn, setIsAddingColumn] = useState(false)
  const [newColumnLabel, setNewColumnLabel] = useState("")
  const [isSavingColumn, setIsSavingColumn] = useState(false)
  const [editingColumnId, setEditingColumnId] = useState<string | null>(null)
  const [editingColumnLabel, setEditingColumnLabel] = useState("")
  const [deletingColumnId, setDeletingColumnId] = useState<string | null>(null)

  const updateRow = useCallback((rowIndex: number, patch: Partial<SheetRowState>) => {
    setRows((current) => {
      const next = current.map((r, i) => (i === rowIndex ? { ...r, ...patch } : r))
      rowsRef.current = next
      return next
    })
  }, [])

  // Forceert een repaint van een rij. Nodig omdat de grid de actieve/net
  // bewerkte cel via een apart overlay-mechanisme tekent, dat na een
  // programmatische wijziging (undo, revert-bij-fout) niet vanzelf ververst.
  const damageRow = useCallback((rowIndex: number) => {
    const columnCount = FIXED_COLUMN_COUNT + columnsRef.current.length
    gridRef.current?.updateCells(
      Array.from({ length: columnCount }, (_, col) => ({ cell: [col, rowIndex] as Item }))
    )
  }, [])

  const loadSheet = useCallback(async () => {
    setIsLoading(true)
    try {
      const response = await fetch(`/api/customers/${customerId}/sheet`, {
        cache: "no-store",
      })
      const payload = (await response.json().catch(() => null)) as
        | (CustomerSheetResponse & ErrorResponse)
        | null
      if (!response.ok) {
        throw new Error(getErrorMessage(payload, "Kon spreadsheet niet ophalen."))
      }
      const nextColumns = payload?.columns ?? []
      const nextRows = (payload?.rows ?? []).map(toRowState)
      setColumns(nextColumns)
      columnsRef.current = nextColumns
      setRows(nextRows)
      rowsRef.current = nextRows
      setLastChange(null)
    } catch (error) {
      setFeedback({
        type: "error",
        message:
          error instanceof Error ? error.message : "Kon spreadsheet niet ophalen.",
      })
    } finally {
      setIsLoading(false)
    }
  }, [customerId])

  useEffect(() => {
    void loadSheet()
  }, [loadSheet])

  const handlePlacedToggle = useCallback(
    (rowIndex: number, checked: boolean, recordUndo: boolean) => {
      const sheetRow = rowsRef.current[rowIndex]
      if (!sheetRow || !sheetRow.isOwner) return

      const prevPlaced = sheetRow.placed
      const prevPlacedDate = sheetRow.placedDate
      setFeedback({ type: null, message: "" })
      const optimisticDate = checked ? new Date().toISOString() : null
      updateRow(rowIndex, { placed: checked, placedDate: optimisticDate })

      void (async () => {
        try {
          const response = await fetch(`/api/blogs/${sheetRow.id}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ is_published: checked }),
          })
          const payload = (await response.json().catch(() => null)) as
            | (ErrorResponse & { published_at?: string | null })
            | null
          if (!response.ok) {
            throw new Error(
              getErrorMessage(payload, "Geplaatst-status aanpassen is mislukt.")
            )
          }
          const serverDate = checked ? payload?.published_at ?? optimisticDate : null
          updateRow(rowIndex, { placed: Boolean(serverDate), placedDate: serverDate })
          damageRow(rowIndex)
          if (recordUndo) {
            setLastChange({
              kind: "placed",
              rowIndex,
              blogId: sheetRow.id,
              prevPlaced,
              prevPlacedDate,
            })
          }
        } catch (error) {
          updateRow(rowIndex, { placed: prevPlaced, placedDate: prevPlacedDate })
          damageRow(rowIndex)
          setFeedback({
            type: "error",
            message:
              error instanceof Error
                ? error.message
                : "Geplaatst-status aanpassen is mislukt.",
          })
        }
      })()
    },
    [updateRow, damageRow]
  )

  const saveCell = useCallback(
    async (
      blogId: string,
      columnId: string,
      value: string,
      rowIndex: number,
      prevValue: string,
      recordUndo: boolean
    ) => {
      try {
        const response = await fetch(`/api/customers/${customerId}/sheet/cells`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            blog_id: blogId,
            column_id: columnId,
            value: value || null,
          }),
        })
        const payload = (await response.json().catch(() => null)) as ErrorResponse | null
        if (!response.ok) {
          throw new Error(getErrorMessage(payload, "Kon cel niet opslaan."))
        }
        if (recordUndo) {
          setLastChange({ kind: "cell", rowIndex, columnId, blogId, prevValue })
        }
      } catch (error) {
        updateRow(rowIndex, { [columnId]: prevValue })
        damageRow(rowIndex)
        setFeedback({
          type: "error",
          message: error instanceof Error ? error.message : "Kon cel niet opslaan.",
        })
      }
    },
    [customerId, updateRow, damageRow]
  )

  const savePlacementUrl = useCallback(
    async (
      blogId: string,
      value: string,
      rowIndex: number,
      prevValue: string,
      recordUndo: boolean
    ) => {
      try {
        const response = await fetch(`/api/blogs/${blogId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ placement_url: value || null }),
        })
        const payload = (await response.json().catch(() => null)) as ErrorResponse | null
        if (!response.ok) {
          throw new Error(getErrorMessage(payload, "Kon plaatsings-URL niet opslaan."))
        }
        if (recordUndo) {
          setLastChange({ kind: "placementUrl", rowIndex, blogId, prevValue })
        }
      } catch (error) {
        updateRow(rowIndex, { placementUrl: prevValue || null })
        damageRow(rowIndex)
        setFeedback({
          type: "error",
          message:
            error instanceof Error ? error.message : "Kon plaatsings-URL niet opslaan.",
        })
      }
    },
    [updateRow, damageRow]
  )

  const applyCellEdit = useCallback(
    (col: number, row: number, newValue: EditableGridCell, recordUndo: boolean) => {
      const sheetRow = rowsRef.current[row]
      if (!sheetRow) return

      if (col === PLACED_COLUMN_INDEX) {
        if (newValue.kind !== GridCellKind.Boolean) return
        const checked = Boolean(newValue.data)
        if (checked === sheetRow.placed) return
        handlePlacedToggle(row, checked, recordUndo)
        return
      }

      if (col === PLACEMENT_URL_COLUMN_INDEX) {
        if (newValue.kind !== GridCellKind.Uri) return
        const nextValue = newValue.data
        const prevValue = sheetRow.placementUrl ?? ""
        if (nextValue === prevValue) return
        updateRow(row, { placementUrl: nextValue || null })
        void savePlacementUrl(sheetRow.id, nextValue, row, prevValue, recordUndo)
        return
      }

      if (col < FIXED_COLUMN_COUNT) {
        // Overige vaste kolommen zijn read-only; negeer een eventuele plak-poging.
        return
      }

      const sheetColumn = columnsRef.current[col - FIXED_COLUMN_COUNT]
      if (!sheetColumn) return
      if (newValue.kind !== GridCellKind.Text) return

      const nextValue = newValue.data
      const prevValue = String(sheetRow[sheetColumn.id] ?? "")
      if (nextValue === prevValue) return

      updateRow(row, { [sheetColumn.id]: nextValue })
      void saveCell(sheetRow.id, sheetColumn.id, nextValue, row, prevValue, recordUndo)
    },
    [handlePlacedToggle, savePlacementUrl, saveCell, updateRow]
  )

  const handleCellEdited = useCallback(
    (cell: Item, newValue: EditableGridCell) => {
      applyCellEdit(cell[0], cell[1], newValue, true)
    },
    [applyCellEdit]
  )

  const handleCellsEdited = useCallback(
    (edits: readonly EditListItem[]) => {
      // Vul-acties over meerdere cellen (bv. fill-handle): elke cel wordt los
      // opgeslagen, maar zo'n bulkwijziging is bewust niet met Cmd+Z terug te
      // draaien — undo dekt alleen losse, individuele wijzigingen.
      setLastChange(null)
      for (const edit of edits) {
        applyCellEdit(edit.location[0], edit.location[1], edit.value, false)
      }
      return true
    },
    [applyCellEdit]
  )

  const handleGridPaste = useCallback(
    (target: Item, values: readonly (readonly string[])[]) => {
      // Eigen plak-implementatie i.p.v. de library-standaard: die vult een
      // meerregelig plakblok niet betrouwbaar naar beneden door een
      // meerdere-rijen-selectie. Hier vult elke geplakte regel de volgende
      // rij, startend bij de bovenste (actieve) cel van de selectie. Net als
      // andere bulkwijzigingen is dit bewust niet met Cmd/Ctrl+Z terug te
      // draaien — undo dekt alleen losse, individuele wijzigingen.
      const [targetCol] = target
      const targetRow = target[1]
      setLastChange(null)

      for (let offset = 0; offset < values.length; offset += 1) {
        const destRow = targetRow + offset
        if (!rowsRef.current[destRow]) break

        const rowValues = values[offset]
        for (let colOffset = 0; colOffset < rowValues.length; colOffset += 1) {
          const destCol = targetCol + colOffset
          const rawValue = (rowValues[colOffset] ?? "").trim()

          if (destCol === PLACEMENT_URL_COLUMN_INDEX) {
            applyCellEdit(
              destCol,
              destRow,
              { kind: GridCellKind.Uri, data: rawValue, allowOverlay: true, readonly: false },
              false
            )
            continue
          }

          if (destCol < FIXED_COLUMN_COUNT) {
            // Overige vaste kolommen (Titel, Aangemaakt, Woorden, Ankers,
            // Geplaatst) zijn read-only of hebben geen zinnig teksttype.
            continue
          }

          applyCellEdit(
            destCol,
            destRow,
            {
              kind: GridCellKind.Text,
              data: rawValue,
              displayData: rawValue,
              allowOverlay: true,
              readonly: false,
            },
            false
          )
        }
      }

      return true
    },
    [applyCellEdit]
  )

  const handleUndo = useCallback(() => {
    const change = lastChange
    if (!change) return
    setLastChange(null)

    if (change.kind === "cell") {
      updateRow(change.rowIndex, { [change.columnId]: change.prevValue })
      damageRow(change.rowIndex)
      void fetch(`/api/customers/${customerId}/sheet/cells`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          blog_id: change.blogId,
          column_id: change.columnId,
          value: change.prevValue || null,
        }),
      }).then(async (response) => {
        if (!response.ok) {
          const payload = (await response.json().catch(() => null)) as ErrorResponse | null
          setFeedback({
            type: "error",
            message: getErrorMessage(payload, "Ongedaan maken is mislukt."),
          })
        } else {
          setFeedback({ type: "success", message: "Wijziging ongedaan gemaakt." })
        }
      })
    } else if (change.kind === "placed") {
      updateRow(change.rowIndex, {
        placed: change.prevPlaced,
        placedDate: change.prevPlacedDate,
      })
      damageRow(change.rowIndex)
      void fetch(`/api/blogs/${change.blogId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_published: change.prevPlaced }),
      }).then(async (response) => {
        if (!response.ok) {
          const payload = (await response.json().catch(() => null)) as ErrorResponse | null
          setFeedback({
            type: "error",
            message: getErrorMessage(payload, "Ongedaan maken is mislukt."),
          })
        } else {
          setFeedback({ type: "success", message: "Wijziging ongedaan gemaakt." })
        }
      })
    } else if (change.kind === "placementUrl") {
      updateRow(change.rowIndex, { placementUrl: change.prevValue || null })
      damageRow(change.rowIndex)
      void fetch(`/api/blogs/${change.blogId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ placement_url: change.prevValue || null }),
      }).then(async (response) => {
        if (!response.ok) {
          const payload = (await response.json().catch(() => null)) as ErrorResponse | null
          setFeedback({
            type: "error",
            message: getErrorMessage(payload, "Ongedaan maken is mislukt."),
          })
        } else {
          setFeedback({ type: "success", message: "Wijziging ongedaan gemaakt." })
        }
      })
    }
  }, [lastChange, customerId, updateRow, damageRow])

  const handleGridKeyDown = useCallback(
    (event: GridKeyEventArgs) => {
      if (!lastChange) return
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "z") {
        event.preventDefault()
        handleUndo()
      }
    },
    [lastChange, handleUndo]
  )

  const addColumn = async () => {
    const label = newColumnLabel.trim()
    if (!label) return

    setIsSavingColumn(true)
    setFeedback({ type: null, message: "" })
    try {
      const response = await fetch(`/api/customers/${customerId}/sheet/columns`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ label }),
      })
      const payload = (await response.json().catch(() => null)) as ErrorResponse | null
      if (!response.ok) {
        throw new Error(getErrorMessage(payload, "Kon kolom niet toevoegen."))
      }
      setNewColumnLabel("")
      setIsAddingColumn(false)
      await loadSheet()
    } catch (error) {
      setFeedback({
        type: "error",
        message:
          error instanceof Error ? error.message : "Kon kolom niet toevoegen.",
      })
    } finally {
      setIsSavingColumn(false)
    }
  }

  const startEditColumn = (column: SheetColumn) => {
    setEditingColumnId(column.id)
    setEditingColumnLabel(column.label)
  }

  const cancelEditColumn = () => {
    setEditingColumnId(null)
    setEditingColumnLabel("")
  }

  const saveEditColumn = async () => {
    if (!editingColumnId) return
    const label = editingColumnLabel.trim()
    if (!label) return

    setIsSavingColumn(true)
    setFeedback({ type: null, message: "" })
    try {
      const response = await fetch(
        `/api/customers/${customerId}/sheet/columns/${editingColumnId}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ label }),
        }
      )
      const payload = (await response.json().catch(() => null)) as ErrorResponse | null
      if (!response.ok) {
        throw new Error(getErrorMessage(payload, "Kon kolom niet hernoemen."))
      }
      cancelEditColumn()
      await loadSheet()
    } catch (error) {
      setFeedback({
        type: "error",
        message:
          error instanceof Error ? error.message : "Kon kolom niet hernoemen.",
      })
    } finally {
      setIsSavingColumn(false)
    }
  }

  const deleteColumn = async (column: SheetColumn) => {
    const confirmed = window.confirm(
      `Kolom "${column.label}" verwijderen? Ingevulde waarden in deze kolom gaan verloren.`
    )
    if (!confirmed) return

    setDeletingColumnId(column.id)
    setFeedback({ type: null, message: "" })
    try {
      const response = await fetch(
        `/api/customers/${customerId}/sheet/columns/${column.id}`,
        { method: "DELETE" }
      )
      const payload = (await response.json().catch(() => null)) as ErrorResponse | null
      if (!response.ok) {
        throw new Error(getErrorMessage(payload, "Kon kolom niet verwijderen."))
      }
      await loadSheet()
    } catch (error) {
      setFeedback({
        type: "error",
        message:
          error instanceof Error ? error.message : "Kon kolom niet verwijderen.",
      })
    } finally {
      setDeletingColumnId(null)
    }
  }

  const gridColumns: GridColumn[] = [
    { title: "Titel", id: "__title", width: columnWidths.__title ?? 240 },
    { title: "Aangemaakt", id: "__created", width: columnWidths.__created ?? 150 },
    { title: "Woorden", id: "__words", width: columnWidths.__words ?? 90 },
    { title: "Anker 1", id: "__anchor1", width: columnWidths.__anchor1 ?? 160 },
    { title: "Anker 2", id: "__anchor2", width: columnWidths.__anchor2 ?? 160 },
    { title: "Geplaatst", id: "__placed", width: columnWidths.__placed ?? 170 },
    {
      title: "Plaatsings-URL",
      id: "__placementUrl",
      width: columnWidths.__placementUrl ?? 220,
    },
    ...columns.map(
      (column): GridColumn => ({
        title: column.label,
        id: column.id,
        width: columnWidths[column.id] ?? 140,
      })
    ),
  ]

  const getCellContent = useCallback(
    ([col, row]: Item): GridCell => {
      const sheetRow = rows[row]
      if (!sheetRow) {
        return { kind: GridCellKind.Loading, allowOverlay: false }
      }

      if (col === 0) {
        const href = `/dashboard/blogs/${sheetRow.id}`
        return {
          kind: GridCellKind.Uri,
          data: href,
          displayData: sheetRow.title,
          readonly: true,
          allowOverlay: false,
          hoverEffect: true,
          onClickUri: (args) => {
            args.preventDefault()
            window.open(href, "_blank")
          },
        }
      }
      if (col === 1) {
        const display = formatDate(sheetRow.createdAt, true)
        return {
          kind: GridCellKind.Text,
          data: sheetRow.createdAt,
          displayData: display,
          readonly: true,
          allowOverlay: false,
        }
      }
      if (col === 2) {
        const display = sheetRow.words ?? "—"
        return {
          kind: GridCellKind.Text,
          data: sheetRow.words ?? "",
          displayData: display,
          readonly: true,
          allowOverlay: false,
        }
      }
      if (col === 3 || col === 4) {
        const text = col === 3 ? sheetRow.anchor1 : sheetRow.anchor2
        const url = col === 3 ? sheetRow.anchor1Url : sheetRow.anchor2Url
        if (url) {
          return {
            kind: GridCellKind.Uri,
            data: url,
            displayData: text ?? url,
            readonly: true,
            allowOverlay: false,
            hoverEffect: true,
            onClickUri: (args) => {
              args.preventDefault()
              window.open(url, "_blank")
            },
          }
        }
        return {
          kind: GridCellKind.Text,
          data: text ?? "",
          displayData: text ?? "—",
          readonly: true,
          allowOverlay: false,
        }
      }
      if (col === PLACED_COLUMN_INDEX) {
        return {
          kind: GridCellKind.Boolean,
          data: sheetRow.placed,
          allowOverlay: false,
          readonly: !sheetRow.isOwner,
          themeOverride: sheetRow.placed ? { bgCell: PLACED_BG_COLOR } : undefined,
        }
      }
      if (col === PLACEMENT_URL_COLUMN_INDEX) {
        const url = sheetRow.placementUrl ?? ""
        return {
          kind: GridCellKind.Uri,
          data: url,
          displayData: url || "—",
          readonly: false,
          allowOverlay: true,
          hoverEffect: Boolean(url),
          onClickUri: url
            ? (args) => {
                args.preventDefault()
                window.open(url, "_blank")
              }
            : undefined,
        }
      }

      const column = columns[col - FIXED_COLUMN_COUNT]
      if (!column) {
        return { kind: GridCellKind.Loading, allowOverlay: false }
      }
      const value = String(sheetRow[column.id] ?? "")
      return {
        kind: GridCellKind.Text,
        data: value,
        displayData: value,
        readonly: false,
        allowOverlay: true,
      }
    },
    [rows, columns]
  )

  const handleColumnResize = useCallback((column: GridColumn, newSize: number) => {
    if (!column.id) return
    setColumnWidths((current) => ({ ...current, [column.id as string]: newSize }))
  }, [])

  return (
    <div className="space-y-4">
      {feedback.message && (
        <div
          className={`rounded-md border px-3 py-2 text-sm ${
            feedback.type === "success"
              ? "border-green-200 bg-green-50 text-green-700"
              : "border-red-200 bg-red-50 text-red-700"
          }`}
        >
          {feedback.message}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-muted/30 p-2">
        <span className="text-xs font-medium text-muted-foreground">
          Eigen kolommen:
        </span>
        {columns.map((column) => (
          <div
            key={column.id}
            className="flex items-center gap-1 rounded-full border bg-background px-2 py-1"
          >
            {editingColumnId === column.id ? (
              <>
                <Input
                  value={editingColumnLabel}
                  onChange={(event) => setEditingColumnLabel(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault()
                      void saveEditColumn()
                    }
                    if (event.key === "Escape") {
                      cancelEditColumn()
                    }
                  }}
                  autoFocus
                  disabled={isSavingColumn}
                  className="h-6 w-28 text-xs"
                />
                <Button
                  size="icon-sm"
                  variant="ghost"
                  aria-label="Opslaan"
                  onClick={() => void saveEditColumn()}
                  disabled={isSavingColumn || !editingColumnLabel.trim()}
                >
                  <Pencil className="size-3" />
                </Button>
              </>
            ) : (
              <>
                <span className="text-xs">{column.label}</span>
                <Button
                  size="icon-sm"
                  variant="ghost"
                  aria-label={`${column.label} hernoemen`}
                  onClick={() => startEditColumn(column)}
                >
                  <Pencil className="size-3" />
                </Button>
                <Button
                  size="icon-sm"
                  variant="ghost"
                  aria-label={`${column.label} verwijderen`}
                  onClick={() => void deleteColumn(column)}
                  disabled={deletingColumnId === column.id}
                >
                  <Trash2 className="size-3" />
                </Button>
              </>
            )}
          </div>
        ))}
        {isAddingColumn ? (
          <div className="flex items-center gap-1">
            <Input
              placeholder="Kolomnaam"
              value={newColumnLabel}
              onChange={(event) => setNewColumnLabel(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault()
                  void addColumn()
                }
                if (event.key === "Escape") {
                  setIsAddingColumn(false)
                  setNewColumnLabel("")
                }
              }}
              autoFocus
              disabled={isSavingColumn}
              className="h-7 w-32 text-xs"
            />
            <Button
              size="sm"
              onClick={() => void addColumn()}
              disabled={isSavingColumn || !newColumnLabel.trim()}
            >
              Toevoegen
            </Button>
          </div>
        ) : (
          <Button size="sm" variant="outline" onClick={() => setIsAddingColumn(true)}>
            <Plus className="size-4" />
            Kolom toevoegen
          </Button>
        )}
      </div>

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Spreadsheet laden...</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Nog geen blogs gekoppeld aan deze klant.
        </p>
      ) : (
        <div className="overflow-hidden rounded-lg border">
          <DataEditor
            ref={gridRef}
            columns={gridColumns}
            rows={rows.length}
            getCellContent={getCellContent}
            onCellEdited={handleCellEdited}
            onCellsEdited={handleCellsEdited}
            onColumnResize={handleColumnResize}
            onPaste={handleGridPaste}
            onKeyDown={handleGridKeyDown}
            getCellsForSelection={true}
            rangeSelect="multi-rect"
            rowHeight={32}
            headerHeight={32}
            theme={{ baseFontStyle: "13px" }}
            width="100%"
            smoothScrollX
            smoothScrollY
          />
        </div>
      )}
    </div>
  )
}
