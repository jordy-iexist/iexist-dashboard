import { ChecklistPrint } from "@/components/livegang/ChecklistPrint"

export const metadata = {
  title: "Livegang checklist (print)",
}

type PrintPageProps = {
  params: Promise<{ customerId: string }>
  searchParams: Promise<{ fase?: string }>
}

export default async function ChecklistPrintPage({ params, searchParams }: PrintPageProps) {
  const { customerId } = await params
  const { fase } = await searchParams
  return <ChecklistPrint customerId={customerId} phase={fase === "3" ? 3 : 2} />
}
