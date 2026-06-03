"use client"

import { useState } from "react"

import { CsvUpload } from "@/components/CsvUpload"
import { ManualBlogEntry } from "@/components/ManualBlogEntry"

type Tab = "csv" | "manual"

export function BlogUploadTabs() {
  const [activeTab, setActiveTab] = useState<Tab>("csv")
  const [refreshKey, setRefreshKey] = useState(0)

  return (
    <div className="space-y-6">
      <div className="flex gap-1 rounded-lg border p-1 w-fit">
        <button
          type="button"
          onClick={() => setActiveTab("csv")}
          className={`rounded-md px-4 py-1.5 text-sm font-medium transition-colors ${
            activeTab === "csv"
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          CSV uploaden
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("manual")}
          className={`rounded-md px-4 py-1.5 text-sm font-medium transition-colors ${
            activeTab === "manual"
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          Handmatig invullen
        </button>
      </div>

      {activeTab === "csv" ? (
        <CsvUpload key={`csv-${refreshKey}`} />
      ) : (
        <ManualBlogEntry onSuccess={() => setRefreshKey((k) => k + 1)} />
      )}
    </div>
  )
}
