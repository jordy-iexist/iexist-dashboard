"use client"

import { Draggable } from "@hello-pangea/dnd"
import { memo } from "react"

import { SeverityBadge } from "@/components/livegang/shared"
import { AssigneeAvatar, KindBadge } from "@/components/werkvoorraad/parts"
import { cardMeta, type WorkCard as WorkCardData } from "@/lib/work-queue"
import { cn } from "@/lib/utils"

/** Titel met het aantal erachter: "Meta description ontbreekt – 14 pagina's". */
export function cardTitle(card: Pick<WorkCardData, "title" | "item_count" | "unit">): string {
  if (card.item_count <= 0) return card.title
  return card.unit ? `${card.title} – ${card.item_count} ${card.unit}` : `${card.title} – ${card.item_count}`
}

/**
 * Eén kaart op het bord, sleepbaar. Klik of Enter opent het paneel; na een sleepactie blokkeert
 * de sleepbibliotheek de klik zelf. Spatie start slepen met het toetsenbord.
 */
export const WorkCard = memo(function WorkCard({
  card,
  index,
  onOpen,
}: {
  card: WorkCardData
  index: number
  onOpen: (cardId: string) => void
}) {
  const title = cardTitle(card)
  const done = card.status === "done"
  return (
    <Draggable draggableId={card.id} index={index}>
      {(provided, snapshot) => (
        <div
          ref={provided.innerRef}
          {...provided.draggableProps}
          {...provided.dragHandleProps}
          onClick={() => onOpen(card.id)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !snapshot.isDragging) {
              event.preventDefault()
              onOpen(card.id)
            }
          }}
          className={cn(
            // Marge in plaats van `gap` op de lijst: de sleepbibliotheek rekent met marges.
            "mb-2 cursor-pointer rounded-lg border bg-card p-3 text-left shadow-xs outline-none transition-shadow select-none",
            "hover:border-foreground/20 focus-visible:ring-[3px] focus-visible:ring-ring/50",
            snapshot.isDragging && "shadow-lg ring-1 ring-foreground/10"
          )}
        >
          <div className="flex flex-wrap items-center gap-1">
            <KindBadge kind={card.kind} />
            {card.severity === "hoog" && <SeverityBadge severity="hoog" />}
          </div>
          <p className="mt-2 line-clamp-2 text-sm leading-snug font-semibold break-words" title={title}>
            {title}
          </p>
          <p className="mt-0.5 truncate text-xs text-muted-foreground" title={card.customer_name}>
            {card.customer_name}
          </p>
          <div className="mt-2 flex items-center justify-between gap-2">
            <span
              className={cn(
                "min-w-0 truncate text-xs",
                done ? "text-green-700 dark:text-green-400" : "text-muted-foreground"
              )}
            >
              {cardMeta(card)}
            </span>
            <AssigneeAvatar userId={card.assignee_id} name={card.assignee_name} />
          </div>
        </div>
      )}
    </Draggable>
  )
})
