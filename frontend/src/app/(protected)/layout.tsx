import { Suspense } from 'react'
import { SidebarInset, SidebarProvider, SidebarTrigger } from '@/components/ui/sidebar'
import { AppSidebar } from '@/components/app-sidebar'
import { getCurrentUser } from '@/lib/auth'
import { fetchCustomerList } from '@/lib/customer-api'
import { readActiveCustomerCookie } from '@/lib/active-customer.server'

async function SidebarWithUser() {
  const [user, customerList, initialCustomerId] = await Promise.all([
    getCurrentUser(),
    fetchCustomerList(),
    readActiveCustomerCookie(),
  ])
  if (!user) return null
  // Alleen wat de klantkiezer nodig heeft naar de client sturen.
  const customers = customerList.map(({ id, name, domain }) => ({ id, name, domain }))
  return (
    <AppSidebar
      user={user}
      customers={customers}
      initialCustomerId={initialCustomerId}
      variant="inset"
    />
  )
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
