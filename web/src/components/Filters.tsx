import type { Status } from "../types";

export interface FilterState {
  q: string;
  status: Status | "all";
  year: string;
  hearingBody: string;
}

interface Props {
  state: FilterState;
  onChange: (s: FilterState) => void;
  years: string[];
  hearingBodies: string[];
  total: number;
  filtered: number;
}

export function Filters({ state, onChange, years, hearingBodies, total, filtered }: Props) {
  return (
    <div className="flex flex-col gap-2 border-b border-border bg-panel/40 px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <input
          className="input h-9 max-w-xs flex-1"
          placeholder="Search case #, address, description…"
          value={state.q}
          onChange={(e) => onChange({ ...state, q: e.target.value })}
        />
        <select
          className="input h-9 w-36"
          value={state.status}
          onChange={(e) => onChange({ ...state, status: e.target.value as FilterState["status"] })}
        >
          <option value="all">All statuses</option>
          <option value="in_process">In process</option>
          <option value="approved">Approved</option>
          <option value="completed">Completed</option>
          <option value="withdrawn">Withdrawn</option>
          <option value="unknown">Unknown</option>
        </select>
        <select
          className="input h-9 w-28"
          value={state.year}
          onChange={(e) => onChange({ ...state, year: e.target.value })}
        >
          <option value="">All years</option>
          {years.map((y) => (
            <option key={y} value={y}>
              {y}
            </option>
          ))}
        </select>
        {hearingBodies.length > 0 && (
          <select
            className="input h-9 w-44"
            value={state.hearingBody}
            onChange={(e) => onChange({ ...state, hearingBody: e.target.value })}
          >
            <option value="">All hearing bodies</option>
            {hearingBodies.map((h) => (
              <option key={h} value={h}>
                {h}
              </option>
            ))}
          </select>
        )}
        <div className="ml-auto text-xs text-muted">
          {filtered.toLocaleString()} / {total.toLocaleString()} projects
        </div>
      </div>
    </div>
  );
}
