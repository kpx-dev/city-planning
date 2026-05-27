export type Status = "in_process" | "approved" | "completed" | "withdrawn" | "unknown";

export interface Project {
  id: number;
  city_id: number;
  city_slug: string;
  city_name: string;
  city_state: string;
  case_number: string;
  address: string;
  description: string;
  applicant_name: string;
  applicant_address: string;
  applicant_phone: string;
  applicant_email: string;
  planner_initials: string;
  district: string;
  hearing_body: string;
  status: Status;
  section: string;
  zone: string;
  property_owner: string;
  latitude: number | null;
  longitude: number | null;
  first_seen_date: string | null;
  last_seen_date: string | null;
  first_source_url: string | null;
  last_source_url: string | null;
  last_source_title: string | null;
}

export interface CityRef {
  id: number;
  name: string;
  state: string;
  slug: string;
}

export interface Source {
  id: number;
  city_id: number;
  url: string;
  title: string;
  report_period_start: string | null;
  report_period_end: string | null;
  published_date: string | null;
}

export interface Meta {
  generated_at: string;
  cities: CityRef[];
  sources: Source[];
  counts: {
    total: number;
    geocoded: number;
    by_status: Record<string, number>;
    by_year: Record<string, number>;
  };
}
