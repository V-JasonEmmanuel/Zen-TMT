import { AlertTriangle, CheckCircle2, Circle, Loader2, MinusCircle, XCircle } from "lucide-react";
import type { Job, Stage } from "../types";
import { Alert, Button } from "./ui";

function StageIcon({ s }: { s: Stage }) {
  switch (s.status) {
    case "done": return <CheckCircle2 className="h-5 w-5 text-emerald-600" />;
    case "running": return <Loader2 className="h-5 w-5 animate-spin text-slate-900" />;
    case "failed": return <XCircle className="h-5 w-5 text-red-600" />;
    case "warning": return <AlertTriangle className="h-5 w-5 text-amber-500" />;
    case "skipped": return <MinusCircle className="h-5 w-5 text-slate-300" />;
    default: return <Circle className="h-5 w-5 text-slate-300" />;
  }
}

const TITLES: Record<Job["kind"], string> = {
  full: "Generating your content", slide: "Regenerating slide", render: "Updating outputs", video: "Generating video",
};

/** Real, backend-driven progress: every row is an actual pipeline stage. */
export function JobProgress({ job, onCancel, onDismiss }: { job: Job; onCancel?: () => void; onDismiss?: () => void }) {
  const active = job.status === "running" || job.status === "queued";
  const done = job.stages.filter((s) => ["done", "warning", "skipped", "failed"].includes(s.status)).length;
  const pct = Math.round((done / Math.max(1, job.stages.length)) * 100);
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-center justify-between gap-4">
        <div>
          <h3 className="text-base font-semibold">{TITLES[job.kind]}</h3>
          <p className="text-sm text-slate-500">
            {job.status === "queued" ? `Waiting in queue${job.queue_position ? ` (position ${job.queue_position})` : ""}…` :
              active ? "Everything runs locally on this computer." :
                job.status === "completed" ? "Completed successfully." :
                  job.status === "completed_with_warnings" ? "Completed with notes - see below." :
                    job.status === "cancelled" ? "Cancelled." : "Stopped because of an error."}
          </p>
        </div>
        {active && onCancel && <Button variant="secondary" size="sm" onClick={onCancel}>Cancel</Button>}
        {!active && onDismiss && <Button variant="ghost" size="sm" onClick={onDismiss}>Dismiss</Button>}
      </div>
      <div className="mb-4 h-1.5 overflow-hidden rounded-full bg-slate-100">
        <div className={`h-full rounded-full transition-all duration-500 ${job.status === "failed" ? "bg-red-500" : "bg-slate-900"}`} style={{ width: `${pct}%` }} />
      </div>
      <ol className="space-y-2.5">
        {job.stages.map((s) => (
          <li key={s.key} className="flex items-start gap-3">
            <StageIcon s={s} />
            <div className="min-w-0 flex-1">
              <div className={`text-sm ${s.status === "pending" || s.status === "skipped" ? "text-slate-400" : "font-medium text-slate-800"}`}>{s.label}</div>
              {s.message && s.status !== "pending" && (
                <div className={`text-xs ${s.status === "failed" ? "text-red-600" : s.status === "warning" ? "text-amber-700" : "text-slate-500"} ${s.status === "running" ? "animate-pulse-soft" : ""}`}>{s.message}</div>
              )}
            </div>
          </li>
        ))}
      </ol>
      {job.error && <div className="mt-4"><Alert tone="error" title="Generation stopped">{job.error}</Alert></div>}
      {!active && job.warnings.length > 0 && (
        <div className="mt-4">
          <Alert tone="warning" title="Notes">
            <ul className="list-disc space-y-0.5 pl-4">{[...new Set(job.warnings)].map((w) => <li key={w}>{w}</li>)}</ul>
          </Alert>
        </div>
      )}
    </div>
  );
}
