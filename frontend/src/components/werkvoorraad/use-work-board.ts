"use client"

// Toestand van het bord: ophalen (met afbreken van verouderde verzoeken), optimistisch verplaatsen
// via een wachtrij, terugspringen bij een fout, en meldingen (incl. "Ongedaan maken" na Klaar).

import { useCallback, useEffect, useReducer, useRef } from "react"

import {
  createCard,
  deleteCard,
  fetchBoard,
  moveCard,
  neighbourIds,
  SOURCE_LABELS,
  updateCard,
  WorkQueueError,
  type WorkBoard,
  type WorkCard,
  type WorkCardCreate,
  type WorkCardDetail,
  type WorkCardPatch,
  type WorkColumn,
  type WorkStatus,
} from "@/lib/work-queue"

/** Na zoveel ms zonder ophalen ververst het bord bij terugkeer naar het tabblad. */
const STALE_AFTER_MS = 60_000
/** Zo lang blijft een melding met "Ongedaan maken" staan. */
const UNDO_NOTICE_MS = 8_000

type Placement = { status: WorkStatus; index: number }

export type BoardNoticeState = {
  id: number
  tone: "info" | "error"
  message: string
  /** Gezet bij "afgerond": terugzetten naar deze plek. */
  undo?: { cardId: string } & Placement
}

type State = {
  board: WorkBoard | null
  /** Sleutel van de backendfilters waarmee `board` is opgehaald. */
  boardKey: string | null
  status: "loading" | "ready" | "error"
  error: string | null
  notice: BoardNoticeState | null
  refreshing: boolean
}

type Action =
  | { type: "fetch-start" }
  | { type: "fetch-success"; board: WorkBoard; key: string }
  | { type: "fetch-error"; message: string }
  | { type: "fetch-end" }
  | { type: "move"; cardId: string; toStatus: WorkStatus; toIndex: number; now: Date }
  | { type: "replace"; card: WorkCard; keepPlacement: boolean }
  | { type: "remove"; cardId: string }
  | { type: "notice"; notice: BoardNoticeState | null }

const INITIAL: State = { board: null, boardKey: null, status: "loading", error: null, notice: null, refreshing: false }

/** Alleen de velden van een kaart (het antwoord van de PATCH is een `WorkCardDetail`). */
function toCard(detail: WorkCardDetail): WorkCard {
  return {
    id: detail.id,
    customer_id: detail.customer_id,
    customer_name: detail.customer_name,
    source: detail.source,
    kind: detail.kind,
    title: detail.title,
    item_count: detail.item_count,
    unit: detail.unit,
    severity: detail.severity,
    status: detail.status,
    position: detail.position,
    assignee_id: detail.assignee_id,
    assignee_name: detail.assignee_name,
    has_note: detail.has_note,
    resolved_by_source: detail.resolved_by_source,
    done_at: detail.done_at,
    created_at: detail.created_at,
  }
}

/** Kolom en index van een kaart in de volledige lijsten, of null. */
export function findPlacement(columns: readonly WorkColumn[], cardId: string): Placement | null {
  for (const column of columns) {
    const index = column.cards.findIndex((card) => card.id === cardId)
    if (index !== -1) return { status: column.status, index }
  }
  return null
}

/**
 * Zet een index in de zichtbare (gefilterde, ingekorte) lijst om naar een index in de volledige
 * kolomlijst: direct na de zichtbare kaart erboven, of direct vóór de eerste zichtbare kaart.
 * `visible` en `full` zijn de lijsten van de doelkolom zonder de gesleepte kaart.
 */
export function visibleToFullIndex(
  visible: readonly Pick<WorkCard, "id">[],
  full: readonly Pick<WorkCard, "id">[],
  visibleIndex: number
): number {
  if (visibleIndex > 0) {
    const above = visible[Math.min(visibleIndex, visible.length) - 1]
    const at = above ? full.findIndex((card) => card.id === above.id) : -1
    return at === -1 ? full.length : at + 1
  }
  const below = visible[0]
  const at = below ? full.findIndex((card) => card.id === below.id) : -1
  return at === -1 ? 0 : at
}

function mapBoard(state: State, map: (columns: WorkColumn[]) => WorkColumn[]): State {
  if (!state.board) return state
  const columns = map(state.board.columns)
  return columns === state.board.columns ? state : { ...state, board: { ...state.board, columns } }
}

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "fetch-start":
      return { ...state, refreshing: true }
    case "fetch-success":
      return { ...state, board: action.board, boardKey: action.key, status: "ready", error: null, refreshing: false }
    case "fetch-error":
      // Met een bord in beeld blijft dat staan; de fout komt dan als melding.
      return state.board
        ? { ...state, refreshing: false }
        : { ...state, status: "error", error: action.message, refreshing: false }
    case "fetch-end":
      return { ...state, refreshing: false }
    case "move":
      return mapBoard(state, (columns) => moveCard(columns, action.cardId, action.toStatus, action.toIndex, action.now))
    case "replace":
      return mapBoard(state, (columns) => {
        const at = findPlacement(columns, action.card.id)
        if (!at) return columns
        const existing = columns.find((column) => column.status === at.status)!.cards[at.index]
        // Staat de kaart (door een latere sleepactie) al ergens anders, dan blijft die plek staan.
        const keep = action.keepPlacement || at.status === action.card.status
        const next: WorkCard = keep
          ? {
              ...action.card,
              status: existing.status,
              done_at: existing.status === action.card.status ? action.card.done_at : existing.done_at,
            }
          : action.card
        let result = columns
        if (!keep) {
          const target = columns.find((column) => column.status === action.card.status)
          const index = action.card.status === "done" ? 0 : (target?.cards.length ?? 0)
          result = moveCard(columns, action.card.id, action.card.status, index)
        }
        return result.map((column) =>
          column.cards.some((card) => card.id === next.id)
            ? { ...column, cards: column.cards.map((card) => (card.id === next.id ? next : card)) }
            : column
        )
      })
    case "remove":
      return mapBoard(state, (columns) =>
        columns.some((column) => column.cards.some((card) => card.id === action.cardId))
          ? columns.map((column) =>
              column.cards.some((card) => card.id === action.cardId)
                ? {
                    ...column,
                    cards: column.cards.filter((card) => card.id !== action.cardId),
                    count: Math.max(0, column.count - 1),
                  }
                : column
            )
          : columns
      )
    case "notice":
      return { ...state, notice: action.notice }
  }
}

export function boardKeyOf(customerId: string | null, assigneeId: string | null) {
  return `${customerId ?? ""}|${assigneeId ?? ""}`
}

function errorMessage(error: unknown) {
  if (error instanceof WorkQueueError) return error.message
  if (error instanceof Error && error.message) return error.message
  return "Er ging iets mis."
}

function isAbort(error: unknown) {
  return error instanceof DOMException && error.name === "AbortError"
}

export type UseWorkBoard = ReturnType<typeof useWorkBoard>

/**
 * Bord voor de backendfilters `customerId` en `assigneeId`. `paused` = een dialog of paneel staat
 * open: dan geen automatische verversing (de knop werkt wel).
 */
export function useWorkBoard({
  customerId,
  assigneeId,
  paused,
}: {
  customerId: string | null
  assigneeId: string | null
  paused: boolean
}) {
  const [state, dispatch] = useReducer(reducer, INITIAL)

  // Spiegel van het bord, synchroon bijgewerkt bij eigen wijzigingen (buren, terugspringen).
  const boardRef = useRef<WorkBoard | null>(null)
  const apply = useCallback((action: Action) => {
    const current = boardRef.current
    if (current) {
      const next = reducer({ ...INITIAL, board: current, status: "ready" }, action).board
      boardRef.current = next
    }
    dispatch(action)
  }, [])

  // Bijgewerkt in een effect dat vóór het laad-effect staat, zodat `reload` de nieuwe filters leest.
  const filtersRef = useRef({ customerId, assigneeId })
  const pausedRef = useRef(paused)
  useEffect(() => {
    filtersRef.current = { customerId, assigneeId }
    pausedRef.current = paused
  }, [customerId, assigneeId, paused])

  const requestSeq = useRef(0)
  const controllerRef = useRef<AbortController | null>(null)
  const lastFetchRef = useRef(0)
  const draggingRef = useRef(false)
  const queueRef = useRef<Promise<unknown>>(Promise.resolve())
  const pendingRef = useRef(0)
  /** Ophalen tijdens een lopende mutatie, of een fout: na de wachtrij nog eens verversen. */
  const refreshAfterQueueRef = useRef(false)
  const noticeSeq = useRef(0)

  const showNotice = useCallback(
    (notice: Omit<BoardNoticeState, "id">) => apply({ type: "notice", notice: { ...notice, id: ++noticeSeq.current } }),
    [apply]
  )
  const dismissNotice = useCallback(() => apply({ type: "notice", notice: null }), [apply])

  const reload = useCallback(
    async ({ background = false }: { background?: boolean } = {}) => {
      const { customerId: customer, assigneeId: assignee } = filtersRef.current
      const key = boardKeyOf(customer, assignee)
      const seq = ++requestSeq.current
      controllerRef.current?.abort()
      const controller = new AbortController()
      controllerRef.current = controller
      lastFetchRef.current = Date.now()
      if (pendingRef.current > 0) refreshAfterQueueRef.current = true
      if (!background) dispatch({ type: "fetch-start" })
      try {
        const board = await fetchBoard({ customerId: customer, assigneeId: assignee }, controller.signal)
        if (seq !== requestSeq.current) return
        boardRef.current = board
        dispatch({ type: "fetch-success", board, key })
      } catch (error) {
        if (seq !== requestSeq.current || isAbort(error)) return
        const message = errorMessage(error)
        if (boardRef.current) {
          dispatch({ type: "fetch-end" })
          if (!background) showNotice({ tone: "error", message: `Verversen mislukt: ${message}` })
        } else {
          dispatch({ type: "fetch-error", message })
        }
      }
    },
    [showNotice]
  )

  /** Verversing op de achtergrond; uitgesteld zolang er gesleept of gemuteerd wordt. */
  const backgroundRefresh = useCallback(() => {
    if (draggingRef.current || pendingRef.current > 0) {
      refreshAfterQueueRef.current = true
      return
    }
    void reload({ background: true })
  }, [reload])

  /** Zet een mutatie in de wachtrij, zodat verzoeken in volgorde bij de backend aankomen. */
  const enqueue = useCallback(
    <T>(task: () => Promise<T>): Promise<T> => {
      pendingRef.current += 1
      const run = queueRef.current.then(task, task)
      queueRef.current = run.catch(() => undefined)
      const settle = () => {
        pendingRef.current -= 1
        if (pendingRef.current === 0 && refreshAfterQueueRef.current && !draggingRef.current) {
          refreshAfterQueueRef.current = false
          void reload({ background: true })
        }
      }
      run.then(settle, settle)
      return run
    },
    [reload]
  )

  // Laden en bij wisselen van de backendfilters.
  useEffect(() => {
    void reload()
  }, [customerId, assigneeId, reload])

  // Afbreken bij weggaan.
  useEffect(() => () => controllerRef.current?.abort(), [])

  // Terugkeer naar het tabblad: verversen als het laatste ophalen ouder is dan 60 s.
  useEffect(() => {
    function onReturn() {
      if (document.visibilityState !== "visible") return
      if (pausedRef.current || Date.now() - lastFetchRef.current < STALE_AFTER_MS) return
      if (!boardRef.current) return
      backgroundRefresh()
    }
    window.addEventListener("focus", onReturn)
    document.addEventListener("visibilitychange", onReturn)
    return () => {
      window.removeEventListener("focus", onReturn)
      document.removeEventListener("visibilitychange", onReturn)
    }
  }, [backgroundRefresh])

  // Melding met "Ongedaan maken" verdwijnt na 8 seconden.
  const notice = state.notice
  useEffect(() => {
    if (!notice || notice.tone !== "info") return
    const timer = window.setTimeout(() => {
      dispatch({ type: "notice", notice: null })
    }, UNDO_NOTICE_MS)
    return () => window.clearTimeout(timer)
  }, [notice])

  const setDragging = useCallback(
    (dragging: boolean) => {
      draggingRef.current = dragging
      if (!dragging && pendingRef.current === 0 && refreshAfterQueueRef.current) {
        refreshAfterQueueRef.current = false
        void reload({ background: true })
      }
    },
    [reload]
  )

  /**
   * Verplaatst een kaart naar `toStatus` op `toIndex` in de VOLLEDIGE kolomlijst (zonder index:
   * onderaan, en in Klaar bovenaan). Optimistisch; bij een fout springt de kaart terug.
   */
  const move = useCallback(
    (cardId: string, toStatus: WorkStatus, toIndex?: number, { withUndo = true } = {}): Promise<boolean> => {
      const board = boardRef.current
      const origin = board ? findPlacement(board.columns, cardId) : null
      if (!board || !origin) return Promise.resolve(false)
      const card = board.columns.find((column) => column.status === origin.status)!.cards[origin.index]
      const target = board.columns.find((column) => column.status === toStatus)
      if (!target) return Promise.resolve(false)
      const sameColumn = origin.status === toStatus
      const length = target.cards.length - (sameColumn ? 1 : 0)
      const index = toIndex ?? (toStatus === "done" ? 0 : length)
      if (sameColumn && index === origin.index) return Promise.resolve(true)

      apply({ type: "move", cardId, toStatus, toIndex: index, now: new Date() })

      if (withUndo && toStatus === "done" && origin.status !== "done" && (card.source === "scan" || card.source === "analysis")) {
        const amount = card.unit && card.item_count > 0 ? `${card.item_count} ${card.unit}` : "Taak"
        showNotice({
          tone: "info",
          message: `${amount} afgerond in ${SOURCE_LABELS[card.source]}`,
          undo: { cardId, ...origin },
        })
      }

      return enqueue(async () => {
        // Buren op het moment van versturen, in de volledige kolomlijst.
        const current = boardRef.current
        const at = current ? findPlacement(current.columns, cardId) : null
        if (!current || !at || at.status !== toStatus) return false // inmiddels teruggesprongen of weg
        const cards = current.columns.find((column) => column.status === toStatus)!.cards
        try {
          const detail = await updateCard(cardId, { status: toStatus, ...neighbourIds(cards, at.index) })
          apply({ type: "replace", card: toCard(detail), keepPlacement: true })
          return true
        } catch (error) {
          const now = boardRef.current ? findPlacement(boardRef.current.columns, cardId) : null
          if (now) apply({ type: "move", cardId, toStatus: origin.status, toIndex: origin.index, now: new Date() })
          showNotice({ tone: "error", message: errorMessage(error) })
          refreshAfterQueueRef.current = true
          return false
        }
      })
    },
    [apply, enqueue, showNotice]
  )

  /** "Ongedaan maken" uit de melding: terug naar de vorige kolom en plek. */
  const undo = useCallback(() => {
    const target = state.notice?.undo
    dismissNotice()
    if (target) void move(target.cardId, target.status, target.index, { withUndo: false })
  }, [state.notice, dismissNotice, move])

  /** Wijzigt een kaart (toewijzen, notitie, titel); geeft de volledige kaart of null bij een fout. */
  const patch = useCallback(
    (cardId: string, body: WorkCardPatch): Promise<WorkCardDetail | null> =>
      enqueue(async () => {
        try {
          const detail = await updateCard(cardId, body)
          apply({ type: "replace", card: toCard(detail), keepPlacement: false })
          return detail
        } catch (error) {
          showNotice({ tone: "error", message: errorMessage(error) })
          return null
        }
      }),
    [apply, enqueue, showNotice]
  )

  /** Verwijdert een kaart (komt niet terug). */
  const remove = useCallback(
    (cardId: string): Promise<boolean> =>
      enqueue(async () => {
        try {
          await deleteCard(cardId)
          apply({ type: "remove", cardId })
          return true
        } catch (error) {
          showNotice({ tone: "error", message: errorMessage(error) })
          return false
        }
      }),
    [apply, enqueue, showNotice]
  )

  /** Nieuwe eigen taak; daarna wordt het bord opnieuw opgehaald. */
  const create = useCallback(
    (body: WorkCardCreate): Promise<boolean> =>
      enqueue(async () => {
        try {
          await createCard(body)
          refreshAfterQueueRef.current = true
          return true
        } catch (error) {
          showNotice({ tone: "error", message: errorMessage(error) })
          return false
        }
      }),
    [enqueue, showNotice]
  )

  return {
    board: state.board,
    boardKey: state.boardKey,
    status: state.status,
    error: state.error,
    notice: state.notice,
    refreshing: state.refreshing,
    reload,
    move,
    patch,
    create,
    remove,
    undo,
    dismissNotice,
    setDragging,
  }
}
