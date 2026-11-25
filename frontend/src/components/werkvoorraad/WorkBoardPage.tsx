"use client"

import { useSearchParams } from "next/navigation"
import { useCallback, useMemo, useState } from "react"

import { EmptyState, ErrorNote } from "@/components/analytics/states"
import { Button } from "@/components/ui/button"
import { Board } from "@/components/werkvoorraad/Board"
import { BoardHeader } from "@/components/werkvoorraad/BoardHeader"
import { NewTaskDialog } from "@/components/werkvoorraad/NewTaskDialog"
import { BoardNotice, BoardSkeleton } from "@/components/werkvoorraad/parts"
import { boardKeyOf, useWorkBoard } from "@/components/werkvoorraad/use-work-board"
import { WorkItemSheet } from "@/components/werkvoorraad/WorkItemSheet"
import { writeUrlParams } from "@/lib/url-state"
import {
  BOARD_PARAMS,
  parseBoardFilters,
  type BoardFilters,
  type WorkColumn,
  type WorkStatus,
} from "@/lib/work-queue"

/** Bord met filters uit het adres (`klant`, `medewerker`, `soort`, `bron`, `taak`). */
export function WorkBoardPage({ currentUserId }: { currentUserId: string | null }) {
  const searchParams = useSearchParams()
  const filters = useMemo(() => parseBoardFilters(searchParams), [searchParams])
  const [newTaskStatus, setNewTaskStatus] = useState<WorkStatus | null>(null)

  const board = useWorkBoard({
    customerId: filters.customerId,
    assigneeId: filters.assigneeId,
    paused: newTaskStatus !== null || filters.cardId !== null,
  })
  const { move, setDragging } = board

  const setFilters = useCallback(
    (patch: Partial<Pick<BoardFilters, "customerId" | "assigneeId" | "kind" | "source" | "cardId">>) => {
      const params: Record<string, string | null> = {}
      if ("customerId" in patch) params[BOARD_PARAMS.customer] = patch.customerId ?? null
      if ("assigneeId" in patch) params[BOARD_PARAMS.assignee] = patch.assigneeId ?? null
      if ("kind" in patch) params[BOARD_PARAMS.kind] = patch.kind ?? null
      if ("source" in patch) params[BOARD_PARAMS.source] = patch.source ?? null
      if ("cardId" in patch) params[BOARD_PARAMS.card] = patch.cardId ?? null
      // Met syncRouter loopt useSearchParams() mee (en daarmee het ophalen bij klant/medewerker).
      writeUrlParams(params, { syncRouter: true })
    },
    []
  )

  const openCard = useCallback((cardId: string) => setFilters({ cardId }), [setFilters])
  const closeCard = useCallback(() => setFilters({ cardId: null }), [setFilters])
  const handleMove = useCallback(
    (cardId: string, toStatus: WorkStatus, toIndex: number) => void move(cardId, toStatus, toIndex),
    [move]
  )
  const sheetMove = useCallback((cardId: string, toStatus: WorkStatus) => move(cardId, toStatus), [move])
  const { remove } = board
  const sheetDelete = useCallback(
    async (cardId: string) => {
      const ok = await remove(cardId)
      if (ok) closeCard()
      return ok
    },
    [remove, closeCard]
  )

  // Browserfilters (soort, bron); gefilterde kolommen houden hun identiteit als er niets wegvalt.
  const columns = board.board?.columns
  const filtered = useMemo<WorkColumn[]>(() => {
    if (!columns) return []
    if (!filters.kind && !filters.source) return columns
    return columns.map((column) => ({
      ...column,
      cards: column.cards.filter(
        (card) => (!filters.kind || card.kind === filters.kind) && (!filters.source || card.source === filters.source)
      ),
    }))
  }, [columns, filters.kind, filters.source])

  const counts = useMemo(() => {
    if (!columns) return null
    const open = filtered.filter((column) => column.status !== "done").flatMap((column) => column.cards)
    return {
      open: open.length,
      customers: new Set(open.map((card) => card.customer_id)).size,
      shown: filtered.reduce((sum, column) => sum + column.cards.length, 0),
      total: columns.reduce((sum, column) => sum + column.cards.length, 0),
    }
  }, [columns, filtered])

  const selectedCard = useMemo(() => {
    if (!filters.cardId || !columns) return null
    for (const column of columns) {
      const card = column.cards.find((item) => item.id === filters.cardId)
      if (card) return card
    }
    return null
  }, [columns, filters.cardId])

  if (board.status === "loading" && !board.board) return <BoardSkeleton />

  // Het getoonde bord hoort (nog) bij andere klant- of medewerkerfilters: gedimd tot het nieuwe er is.
  const stale = board.boardKey !== null && board.boardKey !== boardKeyOf(filters.customerId, filters.assigneeId)
  const hasFilters = Boolean(filters.customerId || filters.assigneeId || filters.kind || filters.source)
  const notice = board.notice

  return (
    // Vaste hoogte (scherm min. mobiele balk/marges en padding van de layout): kolommen scrollen los.
    <div className="flex h-[calc(100svh-5rem)] min-h-[520px] flex-col gap-5 md:h-[calc(100svh-2.75rem)] lg:h-[calc(100svh-3.75rem)]">
      <BoardHeader
        filters={filters}
        openCount={counts?.open ?? null}
        customerCount={counts?.customers ?? null}
        customers={board.board?.customers ?? []}
        users={board.board?.users ?? []}
        currentUserId={currentUserId}
        refreshing={board.refreshing}
        onFiltersChange={setFilters}
        onRefresh={() => void board.reload()}
        onNewTask={() => setNewTaskStatus("todo")}
      />

      {board.status === "error" && !board.board ? (
        <ErrorNote>
          <span className="flex flex-wrap items-center gap-3">
            <span>Het bord kon niet geladen worden: {board.error}</span>
            <Button type="button" variant="outline" size="sm" onClick={() => void board.reload()}>
              Opnieuw proberen
            </Button>
          </span>
        </ErrorNote>
      ) : counts && counts.shown === 0 ? (
        <div aria-busy={stale || undefined} className={stale ? "opacity-60" : undefined}>
          {counts.total === 0 && !hasFilters ? (
            <EmptyState>
              <p className="font-medium text-foreground">Nog geen taken</p>
              <p className="mt-1">
                Kaarten komen hier vanzelf binnen uit de SEO/GEO-scan, de concurrentieanalyses, Search Console en
                Aanpassingen. Met &ldquo;+ Taak&rdquo; zet je zelf een taak op het bord.
              </p>
            </EmptyState>
          ) : (
            <EmptyState>
              <p>Geen taken met deze filters.</p>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="mt-3"
                onClick={() => setFilters({ customerId: null, assigneeId: null, kind: null, source: null })}
              >
                Filters wissen
              </Button>
            </EmptyState>
          )}
        </div>
      ) : (
        <Board
          columns={columns ?? []}
          filtered={filtered}
          busy={stale}
          onMove={handleMove}
          onDraggingChange={setDragging}
          onOpen={openCard}
          onAddTask={setNewTaskStatus}
        />
      )}

      {notice && (
        <div className="pointer-events-none fixed inset-x-0 bottom-4 z-40 flex justify-center px-4">
          <div className="pointer-events-auto w-full max-w-md">
            <BoardNotice
              key={notice.id}
              tone={notice.tone}
              message={notice.message}
              actionLabel={notice.undo ? "Ongedaan maken" : undefined}
              onAction={notice.undo ? board.undo : undefined}
              onDismiss={board.dismissNotice}
            />
          </div>
        </div>
      )}

      <WorkItemSheet
        cardId={filters.cardId}
        card={selectedCard}
        users={board.board?.users ?? []}
        onClose={closeCard}
        onPatch={board.patch}
        onMove={sheetMove}
        onDelete={sheetDelete}
      />

      <NewTaskDialog
        open={newTaskStatus !== null}
        onOpenChange={(open) => {
          if (!open) setNewTaskStatus(null)
        }}
        customers={board.board?.customers ?? []}
        users={board.board?.users ?? []}
        defaults={{
          customerId: filters.customerId,
          status: newTaskStatus ?? "todo",
          assigneeId: currentUserId,
        }}
        onCreate={board.create}
      />
    </div>
  )
}
