import { ChecklistPrint } from "@/components/livegang/ChecklistPrint"

export const metadata = {
  title: "Livegang checklist (print)",
}

type PrintPageProps = {
  params: Promise<{ customerId: string }>
  searchParams: Promise<{ fase?: string; ronde?: string }>
}

export default async function ChecklistPrintPage({ params, searchParams }: PrintPageProps) {
  const { customerId } = await params
  const { fase, ronde } = await searchParams
  const phase = fase === "4" ? 4 : fase === "3" ? 3 : 2
  const period = phase === 4 && ronde && /^\d{4}-Q[1-4]$/.test(ronde) ? ronde : undefined
  return <ChecklistPrint customerId={customerId} phase={phase} period={period} />
}
