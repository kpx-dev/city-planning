import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { loadProjects } from "../data";
import type { Project } from "../types";
import { StatusPill } from "./StatusPill";

export function ProjectDetail() {
  const { caseNumber } = useParams();
  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadProjects()
      .then((projects) => {
        const decoded = decodeURIComponent(caseNumber || "");
        const match = projects.find(
          (p) => p.case_number.toLowerCase() === decoded.toLowerCase()
        );
        setProject(match ?? null);
      })
      .finally(() => setLoading(false));
  }, [caseNumber]);

  if (loading) return <div className="p-8 text-muted">Loading…</div>;
  if (!project) {
    return (
      <div className="mx-auto max-w-3xl p-8">
        <Link to="/" className="text-accent hover:underline">← Back to map</Link>
        <h1 className="mt-4 text-xl font-semibold">Case not found</h1>
        <p className="mt-2 text-muted">No project found for case "{caseNumber}".</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-bg text-fg">
      <div className="mx-auto max-w-3xl px-4 py-6">
        <Link to="/" className="text-accent hover:underline">← Back to map</Link>
        <div className="mt-4">
          <div className="font-mono text-sm text-muted">{project.case_number}</div>
          <h1 className="mt-1 text-2xl font-semibold">{project.address || "Address unavailable"}</h1>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <StatusPill status={project.status} />
            {project.section && (
              <span className="rounded-md bg-border/40 px-2 py-0.5 text-xs text-muted">{project.section}</span>
            )}
            {project.last_seen_date && (
              <span className="text-xs text-muted">Last seen: {project.last_seen_date}</span>
            )}
            {project.first_seen_date && project.first_seen_date !== project.last_seen_date && (
              <span className="text-xs text-muted">First seen: {project.first_seen_date}</span>
            )}
          </div>
        </div>

        {project.description && (
          <section className="panel mt-6 p-4">
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted">Description</h2>
            <p className="whitespace-pre-line leading-relaxed">{project.description}</p>
          </section>
        )}

        <section className="panel mt-4 grid grid-cols-1 gap-x-6 gap-y-2 p-4 sm:grid-cols-2">
          {project.applicant_name && <Field k="Applicant" v={project.applicant_name} />}
          {project.applicant_address && <Field k="Applicant address" v={project.applicant_address} />}
          {project.applicant_phone && <Field k="Phone" v={project.applicant_phone} />}
          {project.applicant_email && <Field k="Email" v={project.applicant_email} />}
          {project.hearing_body && <Field k="Hearing body" v={project.hearing_body} />}
          {project.planner_initials && <Field k="Planner" v={project.planner_initials} />}
          {project.district && <Field k="District" v={project.district} />}
          {project.zone && <Field k="Zoning" v={project.zone} />}
          {project.property_owner && <Field k="Property owner" v={project.property_owner} />}
          {project.latitude !== null && (
            <Field k="Coordinates" v={`${project.latitude!.toFixed(5)}, ${project.longitude!.toFixed(5)}`} />
          )}
        </section>

        {project.last_source_url && (
          <section className="panel mt-4 p-4">
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted">Source</h2>
            <a
              href={project.last_source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="break-all text-accent hover:underline"
            >
              {project.last_source_title || project.last_source_url}
            </a>
          </section>
        )}
      </div>
    </div>
  );
}

function Field({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <div className="text-[11px] font-semibold uppercase tracking-wider text-muted">{k}</div>
      <div className="mt-0.5">{v}</div>
    </div>
  );
}
