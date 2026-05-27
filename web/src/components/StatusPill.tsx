import type { Status } from "../types";

const LABEL: Record<Status, string> = {
  in_process: "In process",
  approved: "Approved",
  completed: "Completed",
  withdrawn: "Withdrawn",
  unknown: "Unknown",
};

export function StatusPill({ status }: { status: Status }) {
  return <span className={`pill pill-${status}`}>{LABEL[status]}</span>;
}
