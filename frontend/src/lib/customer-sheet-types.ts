export type SheetColumn = {
  id: string
  label: string
  position: number
}

export type SheetRow = {
  id: string
  title: string
  created_at: string
  published_at: string | null
  is_owner: boolean
  words: string | null
  anchor_1: string | null
  anchor_1_url: string | null
  anchor_2: string | null
  anchor_2_url: string | null
  placement_url: string | null
  cells: Record<string, string | null>
}

export type CustomerSheetResponse = {
  columns: SheetColumn[]
  rows: SheetRow[]
}
