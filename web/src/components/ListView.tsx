import { useState } from "react";
import { Link } from "react-router-dom";
import type { Project } from "../types";
import { StatusPill } from "./StatusPill";

interface Props {
  projects: Project[];
}

type SortKey = "case_number" | "address" | "last_seen_date" | "status";

export function ListView({ projects }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>("last_seen_date");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const sorted = [...projects].sort((a, b) => {
    const av = (a[sortKey] || "").toString();
    const bv = (b[sortKey] || "").toString();
    const cmp = av.localeCompare(bv);
    return sortDir === "asc" ? cmp : -cmp;
  });

  function head(label: string, key: SortKey) {
    const active = sortKey === key;
    return (
      <th
        scope="col"
        className="sticky top-0 z-10 cursor-pointer select-none border-b border-border bg-panel px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-muted"
        onClick={() => {
          if (sortKey === key) setSortDir(sortDir === "asc" ? "desc" : "asc");
          else {
            setSortKey(key);
            setSortDir("asc");
          }
        }}
      >
        <span className="inline-flex items-center gap-1">
          {label}
          {active ? (sortDir === "asc" ? "▲" : "▼") : ""}
        </span>
      </th>
    );
  }

  return (
    <div className="flex-1 overflow-auto">
      <table className="w-full border-separate border-spacing-0 text-sm">
        <thead>
          <tr>
            {head("Case #", "case_number")}
            {head("Address", "address")}
            <th scope="col" className="sticky top-0 border-b border-border bg-panel px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-muted">
              Description
            </th>
            {head("Status", "status")}
            <th scope="col" className="sticky top-0 border-b border-border bg-panel px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-muted">
              Hearing body
            </th>
            {head("Last seen", "last_seen_date")}
          </tr>
        </thead>
        <tbody>
          {sorted.map((p) => (
            <tr key={p.id} className="hover:bg-border/30">
              <td className="border-b border-border px-3 py-2 align-top font-mono text-xs text-accent">
                <Link to={`/p/${encodeURIComponent(p.case_number)}`} className="hover:underline">
                  {p.case_number || "—"}
                </Link>
              </td>
              <td className="border-b border-border px-3 py-2 align-top">{p.address}</td>
              <td className="border-b border-border px-3 py-2 align-top text-muted">
                <div className="line-clamp-2 max-w-xl">{p.description}</div>
              </td>
              <td className="border-b border-border px-3 py-2 align-top whitespace-nowrap">
                <StatusPill status={p.status} />
              </td>
              <td className="border-b border-border px-3 py-2 align-top text-muted">{p.hearing_body}</td>
              <td className="border-b border-border px-3 py-2 align-top text-muted whitespace-nowrap">{p.last_seen_date}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {sorted.length === 0 && (
        <div className="p-10 text-center text-muted">No projects match those filters.</div>
      )}
    </div>
  );
}
