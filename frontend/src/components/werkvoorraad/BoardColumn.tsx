"use client"

import { Droppable } from "@hello-pangea/dnd"
import { Plus } from "lucide-react"
import { memo } from "react"

import { WorkCard } from "@/components/werkvoorraad/WorkCard"
import { type WorkCard as WorkCardData, type WorkStatus } from "@/lib/work-queue"
import { cn } from "@/lib/utils"

export const PAGE_SIZE = 50

/**
 * Eén kolom: kop met teller, een los scrollende kaartlijst (eerst `limit` kaarten) en onderaan
 * "+ Taak toevoegen". `cards` is de lijst na de browserfilters; de teller toont die lengte.
 */
export const BoardColumn = memo(function BoardColumn({
  status,
  label,
  cards,
  limit,
  onShowMore,
  onOpen,
  onAddTask,
}: {
  status: WorkStatus
  label: string
  cards: WorkCardData[]
  limit: number
  onShowMore: (status: WorkStatus) => void
  onOpen: (cardId: string) => void
  onAddTask: (status: WorkStatus) => void
}) {
  const visible = cards.length > limit ? cards.slice(0, limit) : cards
  const hidden = cards.length - visible.length
  const headingId = `werkvoorraad-kolom-${status}`

  return (
    <section
      aria-labelledby={headingId}
      className="flex max-h-full w-[268px] shrink-0 flex-col rounded-xl bg-muted/60 dark:bg-muted/40"
    >
      <header className="flex items-center justify-between gap-2 px-3 pt-3 pb-2">
        <h2 id={headingId} className="truncate text-sm font-semibold">
          {label}
        </h2>
        <span
          className="inline-flex min-w-6 items-center justify-center rounded-full bg-card px-1.5 py-0.5 text-xs font-medium text-muted-foreground tabular-nums"
          aria-label={`${cards.length} ${cards.length === 1 ? "taak" : "taken"}`}
        >
          {cards.length}
        </span>
      </header>

      <Droppable droppableId={status}>
        {(provided, snapshot) => (
          <div
            ref={provided.innerRef}
            {...provided.droppableProps}
            className={cn(
              "min-h-24 flex-1 overflow-y-auto px-2 pt-0.5",
              snapshot.isDraggingOver && "rounded-lg bg-foreground/[0.03]"
            )}
          >
            {visible.map((card, index) => (
              <WorkCard key={card.id} card={card} index={index} onOpen={onOpen} />
            ))}
            {provided.placeholder}
            {visible.length === 0 && !snapshot.isDraggingOver && (
              <div className="mb-2 flex min-h-20 items-center justify-center rounded-lg border border-dashed border-muted-foreground/30 px-3 text-center text-xs text-muted-foreground">
                Sleep een kaart hierheen
              </div>
            )}
            {hidden > 0 && (
              <button
                type="button"
                onClick={() => onShowMore(status)}
                className="mb-2 w-full rounded-md py-1.5 text-xs font-medium text-muted-foreground outline-none hover:bg-card hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50"
              >
                Toon nog {Math.min(PAGE_SIZE, hidden)} (van {cards.length})
              </button>
            )}
          </div>
        )}
      </Droppable>

      <div className="px-2 pt-1 pb-2">
        <button
          type="button"
          onClick={() => onAddTask(status)}
          className="flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-sm text-muted-foreground outline-none hover:bg-card hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50"
        >
          <Plus className="size-4" aria-hidden />
          Taak toevoegen
        </button>
      </div>
    </section>
  )
})
