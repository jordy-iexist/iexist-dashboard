import { SettingsNav } from "@/components/settings/SettingsNav"

export default function SettingsLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <div className="flex gap-10">
      <aside className="hidden w-52 shrink-0 md:block">
        <div className="sticky top-20">
          <SettingsNav />
        </div>
      </aside>
      <div className="min-w-0 max-w-4xl flex-1">{children}</div>
    </div>
  )
}
