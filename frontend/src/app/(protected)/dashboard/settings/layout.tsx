// Het menu van Instellingen staat in het paneel naast de sidebar (app-sidebar.tsx);
// op smal scherm dient het overzicht (page.tsx) als menu.
export default function SettingsLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return <div className="min-w-0 max-w-4xl rounded-xl border bg-card p-6">{children}</div>
}
