import { WebsiteAuditor } from "@/components/audit/WebsiteAuditor"

export const metadata = {
  title: "Website Audit",
}

export default function AuditPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Website Audit</h1>
        <p className="text-muted-foreground">
          Scan een website op typography, performance, toegankelijkheid, broken links en meer.
        </p>
      </div>
      <WebsiteAuditor />
    </div>
  )
}
