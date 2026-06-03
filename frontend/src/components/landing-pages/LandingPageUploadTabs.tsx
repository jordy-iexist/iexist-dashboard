"use client"

import { useState } from "react"

import { LandingPageCsvUpload } from "@/components/landing-pages/LandingPageCsvUpload"
import { ManualLandingPageEntry } from "@/components/landing-pages/ManualLandingPageEntry"

type Tab = "csv" | "manual"

export function LandingPageUploadTabs() {
  const [activeTab, setActiveTab] = useState<Tab>("csv")

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
        <LandingPageCsvUpload />
      ) : (
        <ManualLandingPageEntry />
      )}
    </div>
  )
}
