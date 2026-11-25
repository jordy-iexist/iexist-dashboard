"use client"

import { DragDropContext, type DropResult } from "@hello-pangea/dnd"
import { useCallback, useState } from "react"

import { BoardColumn, PAGE_SIZE } from "@/components/werkvoorraad/BoardColumn"
import { visibleToFullIndex } from "@/components/werkvoorraad/use-work-board"
import { isWorkStatus, STATUS_LABELS, type WorkColumn, type WorkStatus } from "@/lib/work-queue"
import { cn } from "@/lib/utils"

const INITIAL_LIMITS: Record<WorkStatus, number> = {
  todo: PAGE_SIZE,
  doing: PAGE_SIZE,
  review: PAGE_SIZE,
  done: PAGE_SIZE,
}

/**
 * De vier kolommen met slepen. `columns` zijn de volledige lijsten uit de backend, `filtered` dezelfde
 * kolommen na de browserfilters (soort, bron). Een drop in de zichtbare lijst wordt omgezet naar een
 * plek in de volledige lijst, zodat de buren kloppen.
 */
export function Board({
  columns,
  filtered,
  busy,
  onMove,
  onDraggingChange,
  onOpen,
  onAddTask,
}: {
  columns: WorkColumn[]
  filtered: WorkColumn[]
  busy: boolean
  onMove: (cardId: string, toStatus: WorkStatus, toIndex: number) => void
  onDraggingChange: (dragging: boolean) => void
  onOpen: (cardId: string) => void
  onAddTask: (status: WorkStatus) => void
}) {
  const [limits, setLimits] = useState(INITIAL_LIMITS)

  const showMore = useCallback(
    (status: WorkStatus) => setLimits((current) => ({ ...current, [status]: current[status] + PAGE_SIZE })),
    []
  )

  function handleDragEnd(result: DropResult) {
    onDraggingChange(false)
    const { destination, source, draggableId } = result
    if (!destination || !isWorkStatus(destination.droppableId)) return
    if (destination.droppableId === source.droppableId && destination.index === source.index) return
    const toStatus = destination.droppableId
    const full = columns.find((column) => column.status === toStatus)?.cards ?? []
    const shown = filtered.find((column) => column.status === toStatus)?.cards ?? []
    const visible = shown.slice(0, limits[toStatus]).filter((card) => card.id !== draggableId)
    const toIndex = visibleToFullIndex(
      visible,
      full.filter((card) => card.id !== draggableId),
      destination.index
    )
    onMove(draggableId, toStatus, toIndex)
  }

  return (
    <DragDropContext onDragStart={() => onDraggingChange(true)} onDragEnd={handleDragEnd}>
      <div
        aria-busy={busy || undefined}
        className={cn(
          "flex min-h-0 flex-1 items-start gap-3 overflow-x-auto pb-2 transition-opacity",
          busy && "pointer-events-none opacity-60"
        )}
      >
        {filtered.map((column) => (
          <BoardColumn
            key={column.status}
            status={column.status}
            label={STATUS_LABELS[column.status] ?? column.label}
            cards={column.cards}
            limit={limits[column.status]}
            onShowMore={showMore}
            onOpen={onOpen}
            onAddTask={onAddTask}
          />
        ))}
      </div>
    </DragDropContext>
  )
}
