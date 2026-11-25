import { MaandrapportView } from "@/components/klanten/maandrapport/MaandrapportView"
import { fetchCustomerDetail } from "@/lib/customer-api"
import {
  MONTH_PARAM,
  defaultMonth,
  isMonthInRange,
  parseMonth,
  shiftMonth,
} from "@/lib/monthly-report"
import type { PageSearchParams } from "@/lib/search-params"

export const metadata = {
  title: "Maandrapport",
}

type MaandrapportPageProps = {
  params: Promise<{ customerId: string }>
  searchParams: Promise<PageSearchParams>
}

// `?maand=YYYY-MM` kiest de maand; ontbreekt die, is hij ongeldig, in de toekomst of te oud,
// dan de standaardmaand (bepaald op de server, in de tijdzone Europe/Amsterdam).
export default async function MaandrapportPage({ params, searchParams }: MaandrapportPageProps) {
  const [{ customerId }, query] = await Promise.all([params, searchParams])
  const customer = await fetchCustomerDetail(customerId)

  const now = new Date()
  const requested = parseMonth(query[MONTH_PARAM])
  const month = requested && isMonthInRange(requested, now) ? requested : defaultMonth(now)
  const previousMonth = shiftMonth(month, -1)
  const nextMonth = shiftMonth(month, 1)

  return (
    <MaandrapportView
      // Bij een andere klant of maand begint de staat opnieuw.
      key={`${customer.id}|${month}`}
      customerId={customer.id}
      customerName={customer.name}
      domain={customer.domain}
      month={month}
      previousMonth={isMonthInRange(previousMonth, now) ? previousMonth : null}
      nextMonth={isMonthInRange(nextMonth, now) ? nextMonth : null}
      formOfAddress={customer.form_of_address}
      toneOfVoice={customer.tone_of_voice}
    />
  )
}
