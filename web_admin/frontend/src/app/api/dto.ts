// DTOs mirror web_admin/backend/src/api/schemas.py verbatim.

export interface RecordingEvent {
  t_ms: number;
  type: string;
  attrs: Record<string, string>;
}

export interface RecordingMeta {
  schema: number | null;
  preamble: Record<string, string>;
  vehicle: Record<string, string>;
  events: RecordingEvent[];
  footer: Record<string, string> | null;
  footer_count: number;
  warnings: string[];
  clean_stop: boolean;
  incident_count: number;
}

export interface FileOut {
  id: number;
  filename: string;
  size_bytes: number;
  uploaded_at: string;
  source_deleted: boolean;
  duration_s: number | null;
  fs_hz: number | null;
  gps_coverage_ratio: number | null;
  recording_meta: RecordingMeta | null;
  runs_count: number;
}

export interface CoefficientSnapshot {
  set_id: number;
  name: string;
  params: { A?: number; B?: number; bias?: number };
}

export interface RunCoefficients {
  eq3: CoefficientSnapshot | null;
  eq6_bias: CoefficientSnapshot | null;
}

export interface RunSummary {
  segments_total: number;
  km_total: number;
  mean_iri_multi: number | null;
  low_speed_count: number;
  partial_count: number;
  events_total: number;
  incidents_total: number;
  clean_stop: boolean | null;
  vehicle_type: string | null;
  coefficients?: RunCoefficients | null;
  mean_iri_multi_corrected?: number | null;
}

export interface RunOut {
  id: number;
  file_id: number;
  filename: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  status: 'queued' | 'running' | 'done' | 'failed';
  params: { low_speed_policy?: string; coefficients?: RunCoefficients };
  result_dir: string | null;
  summary: RunSummary | null;
  error: string | null;
}

export interface SegmentRow {
  seg_id: number;
  s_start: number;
  s_end: number;
  length_m: number;
  grms: number | null;
  iri_psd_raw: number | null;
  iri_psd: number | null;
  iri_multi: number | null;
  mean_speed_kmh: number | null;
  events_per_km: number | null;
  partial: boolean;
  speed_valid: boolean;
  low_speed_class: string | null;
  needs_class12_survey: boolean;
  iri_multi_corrected?: number | null;
  [key: string]: unknown;
}

export interface IriHistogramBin {
  bin_start: number;
  bin_end: number;
  count: number;
}

export interface WorstSegment {
  run_id: number;
  filename: string;
  seg_id: number;
  iri_psd: number;
  iri_multi: number | null;
  needs_class12_survey: boolean;
}

export interface DashboardOut {
  files_total: number;
  runs_done: number;
  km_total: number;
  low_speed_total: number;
  iri_histogram: IriHistogramBin[];
  worst_segments: WorstSegment[];
}

export interface GeoJsonFeatureCollection {
  type: 'FeatureCollection';
  features: Array<{
    type: 'Feature';
    properties: Record<string, unknown>;
    geometry: { type: string; coordinates: unknown };
  }>;
}

export interface ReferenceOut {
  id: number;
  filename: string;
  uploaded_at: string;
  road_name: string;
  direction: string | null;
  lane: number | null;
  category: number | null;
  step_m: number;
  measured_at: string | null;
  intervals_count: number;
  chainage_span_m: number;
  bbox: number[] | null;
  parse_warnings: string[];
  source_deleted: boolean;
  comparisons_count: number;
}

export interface ComparisonSummary {
  n_pairs: number;
  spearman_rho: number;
  pearson_r: number;
  mae: number;
  bias: number;
  n_eff: number;
  eq3_r2: number | null;
  gates: Record<string, unknown>;
}

export interface ComparisonOut {
  id: number;
  run_id: number;
  reference_id: number;
  run_filename: string | null;
  reference_road: string | null;
  created_at: string;
  status: 'queued' | 'running' | 'done' | 'failed';
  params: Record<string, number>;
  result_dir: string | null;
  summary: ComparisonSummary | null;
  error: string | null;
}

export interface CoefficientSetOut {
  id: number;
  name: string;
  model: 'eq3' | 'eq6_bias';
  params: { A?: number; B?: number; bias?: number };
  vehicle_type: string | null;
  phone_model: string | null;
  status: 'draft' | 'confirmed' | 'archived';
  comparison_id: number | null;
  stats_snapshot: Record<string, number | null> | null;
  created_at: string;
  confirmed_at: string | null;
  confirmed_note: string | null;
}

export interface ConfirmOut {
  set: CoefficientSetOut;
  archived_set_id: number | null;
  reanalyze_candidates: number;
}

export interface ArtifactEntry {
  name: string;
  size_bytes: number;
}

export interface ChartScatterPoint {
  seg_id: number;
  psd_sqrt_scalar: number;
  iri_ref: number;
  iri_multi: number;
  chainage_m: number;
}

export interface ChartProfilePoint {
  chainage_m: number;
  iri_ref: number;
  iri_multi: number;
  iri_multi_bias_corrected: number;
  seg_id: number;
}

export interface ChartBAPoint {
  seg_id: number;
  mean: number;
  diff: number;
}

export interface ChartData {
  scatter: ChartScatterPoint[];
  profile: ChartProfilePoint[];
  bland_altman: ChartBAPoint[];
  // NaN -> null via backend _json_safe
  eq3_fit: { A: number | null; B: number | null; r2: number | null; mae: number | null; n: number };
  bias: number;
  gates: Record<string, unknown>;
}
