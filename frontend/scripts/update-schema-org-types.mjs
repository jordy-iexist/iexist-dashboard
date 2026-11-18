#!/usr/bin/env node
/**
 * Ververst `src/lib/schema-org-types.json`: alle typenamen van schema.org, gesorteerd en ontdubbeld.
 * Handmatig draaien, zelden nodig (schema.org brengt een paar keer per jaar een versie uit):
 *
 *   cd frontend && node scripts/update-schema-org-types.mjs
 */
import { writeFile } from "node:fs/promises"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const SOURCE = "https://schema.org/version/latest/schemaorg-current-https-types.csv"
const TARGET = resolve(dirname(fileURLToPath(import.meta.url)), "../src/lib/schema-org-types.json")
const NAME = /^[A-Z][A-Za-z0-9]{1,60}$/

/** Minimale CSV-parser (RFC 4180): velden tussen aanhalingstekens mogen komma's en regeleinden bevatten. */
function parseCsv(text) {
  const rows = []
  let row = []
  let field = ""
  let quoted = false
  for (let i = 0; i < text.length; i++) {
    const ch = text[i]
    if (quoted) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          field += '"'
          i++
        } else {
          quoted = false
        }
      } else {
        field += ch
      }
    } else if (ch === '"') {
      quoted = true
    } else if (ch === ",") {
      row.push(field)
      field = ""
    } else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i++
      row.push(field)
      rows.push(row)
      row = []
      field = ""
    } else {
      field += ch
    }
  }
  if (field !== "" || row.length) {
    row.push(field)
    rows.push(row)
  }
  return rows
}

const response = await fetch(SOURCE)
if (!response.ok) throw new Error(`Ophalen mislukt: ${response.status} ${response.statusText}`)
const rows = parseCsv(await response.text())
const header = rows.shift() ?? []
const col = (name) => {
  const index = header.indexOf(name)
  if (index < 0) throw new Error(`Kolom "${name}" niet gevonden in ${SOURCE}`)
  return index
}
const [LABEL, ID, SUBTYPE_OF, ENUMERATION, SUPERSEDED_BY, PART_OF] = [
  "label",
  "id",
  "subTypeOf",
  "enumerationtype",
  "supersededBy",
  "isPartOf",
].map(col)

// Datatypes (Text, Number, URL, ...) en hun subtypes zijn geen entiteiten die je als schema maakt. In het
// CSV-bestand hebben de basisdatatypes geen subTypeOf; daarom staan ze hier met naam.
const DATA_TYPE_ROOTS = new Set(
  ["DataType", "Boolean", "True", "False", "Date", "DateTime", "Time", "Number", "Text"].map((n) => `https://schema.org/${n}`)
)
const parents = new Map(rows.map((r) => [r[ID], (r[SUBTYPE_OF] ?? "").split(",").map((s) => s.trim()).filter(Boolean)]))
function isDataType(id, seen = new Set()) {
  if (DATA_TYPE_ROOTS.has(id)) return true
  if (seen.has(id)) return false
  seen.add(id)
  return (parents.get(id) ?? []).some((p) => isDataType(p, seen))
}

const names = [
  ...new Set(
    rows
      .filter(
        (r) =>
          !r[ENUMERATION] && // waarde van een opsomming (bijv. ActiveActionStatus), geen type
          !r[SUPERSEDED_BY] && // vervangen door een ander type
          !(r[PART_OF] ?? "").includes("meta.schema.org") &&
          !isDataType(r[ID])
      )
      .map((r) => (r[LABEL] ?? "").trim())
      .filter((n) => NAME.test(n))
  ),
].sort()
if (names.length < 500) throw new Error(`Verdacht weinig types (${names.length}); bestand niet overschreven.`)

await writeFile(TARGET, `${JSON.stringify(names, null, 2)}\n`)
console.log(`${names.length} types geschreven naar ${TARGET}`)
