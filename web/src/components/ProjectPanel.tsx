import { Link } from "react-router-dom";
import type { Project } from "../types";
import { StatusPill } from "./StatusPill";

interface Props {
  project: Project | null;
  onClose: () => void;
}

export function ProjectPanel({ project, onClose }: Props) {
  if (!project) return null;
  return (
    <div className="absolute right-0 top-0 z-10 h-full w-full max-w-md overflow-y-auto border-l border-border bg-panel/95 shadow-xl backdrop-blur transition-transform duration-300">
      <div className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-border bg-panel/95 px-4 py-3">
        <div>
          <div className="font-mono text-sm text-muted">{project.case_number || "—"}</div>
          <div className="mt-0.5 line-clamp-2 text-base font-semibold">
            {project.address || "Address unavailable"}
          </div>
        </div>
        <button
          onClick={onClose}
          className="ml-auto rounded-md p-1.5 text-muted hover:bg-border/40 hover:text-fg"
          aria-label="Close"
        >
          <svg viewBox="0 0 24 24" className="h-5 w-5" fill="currentColor">
            <path d="M18.3 5.71L12 12l6.3 6.29-1.41 1.42L10.59 13.4 4.3 19.71l-1.41-1.42L9.17 12 2.88 5.71 4.3 4.29l6.3 6.3 6.29-6.3z" />
          </svg>
        </button>
      </div>

      <div className="space-y-4 px-4 py-4 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <StatusPill status={project.status} />
          {project.section && (
            <span className="rounded-md bg-border/40 px-2 py-0.5 text-xs text-muted">{project.section}</span>
          )}
          {project.last_seen_date && (
            <span className="text-xs text-muted">Last seen: {project.last_seen_date}</span>
          )}
        </div>

        {project.description && (
          <Section title="Description">
            <p className="whitespace-pre-line leading-relaxed">{project.description}</p>
          </Section>
        )}

        {(project.applicant_name || project.applicant_address || project.applicant_phone || project.applicant_email) && (
          <Section title="Applicant">
            {project.applicant_name && <div className="font-medium">{project.applicant_name}</div>}
            {project.applicant_address && <div className="text-muted">{project.applicant_address}</div>}
            <div className="mt-1 flex flex-wrap gap-3 text-xs">
              {project.applicant_phone && <span className="text-muted">{project.applicant_phone}</span>}
              {project.applicant_email && (
                <a href={`mailto:${project.applicant_email}`} className="text-accent hover:underline">
                  {project.applicant_email}
                </a>
              )}
            </div>
          </Section>
        )}

        <Section title="Details">
          <dl className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-1.5 text-sm">
            {project.hearing_body && <Detail k="Hearing body" v={project.hearing_body} />}
            {project.planner_initials && <Detail k="Planner" v={project.planner_initials} />}
            {project.district && <Detail k="District" v={project.district} />}
            {project.zone && <Detail k="Zoning" v={project.zone} />}
            {project.property_owner && <Detail k="Property owner" v={project.property_owner} />}
            {project.latitude !== null && (
              <Detail
                k="Coordinates"
                v={`${project.latitude!.toFixed(5)}, ${project.longitude!.toFixed(5)}`}
              />
            )}
          </dl>
        </Section>

        {project.last_source_url && (
          <Section title="Source">
            <a
              href={project.last_source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="break-all text-accent hover:underline"
            >
              {project.last_source_title || project.last_source_url}
            </a>
          </Section>
        )}

        <div className="pt-2">
          <Link
            to={`/p/${encodeURIComponent(project.case_number)}`}
            className="btn"
          >
            Open detail page →
          </Link>
        </div>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted">{title}</div>
      <div>{children}</div>
    </div>
  );
}

function Detail({ k, v }: { k: string; v: string }) {
  return (
    <>
      <dt className="text-muted">{k}</dt>
      <dd className="text-fg">{v}</dd>
    </>
  );
}
