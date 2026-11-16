import { ChecklistPrint } from "@/components/livegang/ChecklistPrint"

export const metadata = {
  title: "Livegangchecklist (print)",
}

type PrintPageProps = {
  params: Promise<{ customerId: string }>
}

export default async function GoLiveChecklistPrintPage({ params }: PrintPageProps) {
  const { customerId } = await params
  return <ChecklistPrint customerId={customerId} phase={5} />
}
