export type ColumnMapping = Record<string, string>

export function normalizeForMatch(input: string): string {
  return input
    .toLowerCase()
    .trim()
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .replace(/[^a-z0-9 ]/g, "")
}

export function findMatchingHeader(headers: string[], fieldName: string): string | null {
  const normalizedFieldName = normalizeForMatch(fieldName)
  if (!normalizedFieldName) {
    return null
  }

  for (const header of headers) {
    if (normalizeForMatch(header) === normalizedFieldName) {
      return header
    }
  }

  return null
}

export function reconcileColumnMapping(
  headers: string[],
  fields: readonly string[],
  previousMapping: ColumnMapping
): ColumnMapping {
  const nextMapping: ColumnMapping = {}

  for (const field of fields) {
    const previousHeader = previousMapping[field]
    if (previousHeader && headers.includes(previousHeader)) {
      nextMapping[field] = previousHeader
      continue
    }

    const autoMatch = findMatchingHeader(headers, field)
    if (autoMatch) {
      nextMapping[field] = autoMatch
      continue
    }

    nextMapping[field] = ""
  }

  return nextMapping
}

function countDelimiterOutsideQuotes(line: string, delimiter: string): number {
  let count = 0
  let inQuotes = false

  for (let index = 0; index < line.length; index += 1) {
    const char = line[index]

    if (char === '"') {
      const nextChar = line[index + 1]
      if (inQuotes && nextChar === '"') {
        index += 1
        continue
      }
      inQuotes = !inQuotes
      continue
    }

    if (!inQuotes && char === delimiter) {
      count += 1
    }
  }

  return count
}

export function detectDelimiter(line: string): "," | ";" | "\t" {
  const candidates = [",", ";", "\t"] as const
  let bestDelimiter: "," | ";" | "\t" = ","
  let bestScore = -1

  for (const candidate of candidates) {
    const score = countDelimiterOutsideQuotes(line, candidate)
    if (score > bestScore) {
      bestDelimiter = candidate
      bestScore = score
    }
  }

  return bestDelimiter
}

export function parseCsvHeaderLine(line: string): string[] {
  const headers: string[] = []
  const delimiter = detectDelimiter(line)
  let current = ""
  let inQuotes = false

  for (let index = 0; index < line.length; index += 1) {
    const char = line[index]

    if (char === '"') {
      const nextChar = line[index + 1]
      if (inQuotes && nextChar === '"') {
        current += '"'
        index += 1
        continue
      }
      inQuotes = !inQuotes
      continue
    }

    if (char === delimiter && !inQuotes) {
      headers.push(current.trim())
      current = ""
      continue
    }

    current += char
  }

  headers.push(current.trim())

  if (headers.length > 0) {
    headers[0] = headers[0].replace(/^﻿/, "")
  }

  return headers.filter((header) => header.length > 0)
}

export async function readCsvHeaders(file: File): Promise<string[]> {
  const content = await file.text()
  const firstDataLine = content
    .split(/\r?\n/)
    .find((line) => line.trim().length > 0)

  if (!firstDataLine) {
    return []
  }

  return parseCsvHeaderLine(firstDataLine)
}
