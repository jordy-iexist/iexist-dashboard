import { Suspense } from 'react'
import { SidebarProvider, SidebarTrigger } from '@/components/ui/sidebar'
import { AppSidebar } from '@/components/app-sidebar'
import { getCurrentUser } from '@/lib/auth'

async function SidebarWithUser() {
  const user = await getCurrentUser()
  if (!user) return null
  return <AppSidebar user={user} />
}

export default function ProtectedLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <SidebarProvider>
      <Suspense fallback={<aside className="w-64 shrink-0 border-r" />}>
        <SidebarWithUser />
      </Suspense>
      <main className="flex flex-1 flex-col">
        <header className="sticky top-0 z-10 flex h-14 items-center gap-4 border-b bg-background px-4 lg:px-6">
          <SidebarTrigger />
        </header>
        <div className="flex-1 p-4 lg:p-6">
          {children}
        </div>
      </main>
    </SidebarProvider>
  )
}
