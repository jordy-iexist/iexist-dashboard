"use client"

import { useState } from "react"
import { FileSpreadsheet, PencilLine } from "lucide-react"

import { CsvUpload } from "@/components/CsvUpload"
import { ManualBlogEntry } from "@/components/ManualBlogEntry"

type Tab = "csv" | "manual"

const TABS: { id: Tab; label: string; icon: typeof FileSpreadsheet }[] = [
  { id: "csv", label: "CSV uploaden", icon: FileSpreadsheet },
  { id: "manual", label: "Handmatig invullen", icon: PencilLine },
]

export function BlogUploadTabs() {
  const [activeTab, setActiveTab] = useState<Tab>("csv")
  const [refreshKey, setRefreshKey] = useState(0)

  return (
    <div className="space-y-6">
      <div className="flex w-fit gap-1 rounded-full bg-brand-yellow/10 p-1">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => setActiveTab(id)}
            className={`inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === id
                ? "bg-brand-yellow text-brand-blue shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <Icon className="size-4" />
            {label}
          </button>
        ))}
      </div>

      {activeTab === "csv" ? (
        <CsvUpload key={`csv-${refreshKey}`} />
      ) : (
        <ManualBlogEntry onSuccess={() => setRefreshKey((k) => k + 1)} />
      )}
    </div>
  )
}
