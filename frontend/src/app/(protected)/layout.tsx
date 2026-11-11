import { Suspense } from 'react'
import { SidebarInset, SidebarProvider, SidebarTrigger } from '@/components/ui/sidebar'
import { AppSidebar } from '@/components/app-sidebar'
import { getCurrentUser } from '@/lib/auth'

async function SidebarWithUser() {
  const user = await getCurrentUser()
  if (!user) return null
  return <AppSidebar user={user} variant="inset" />
}

export default function ProtectedLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <SidebarProvider className="bg-sidebar">
      <Suspense fallback={<aside className="w-64 shrink-0 bg-sidebar" />}>
        <SidebarWithUser />
      </Suspense>
      <SidebarInset className="min-w-0">
        {/* Mobile only: the sidebar is a sheet there, so it needs its own opener */}
        <div className="flex h-12 items-center border-b px-4 md:hidden">
          <SidebarTrigger />
        </div>
        <div className="flex-1 p-4 lg:p-6">
          {children}
        </div>
      </SidebarInset>
    </SidebarProvider>
  )
}
