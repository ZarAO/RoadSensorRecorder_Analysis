import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import {
  AggregateChartData, AggregateOut, ArtifactEntry, ChartData, CoefficientSetOut, ComparisonOut,
  ConfirmOut, DashboardOut, FileOut, GeoJsonFeatureCollection, PreviewResolutionOut,
  ReferenceIntervalRow, ReferenceOut, RunOut, SegmentRow,
} from './dto';

@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);
  private readonly base = '/api';

  listFiles(): Observable<FileOut[]> {
    return this.http.get<FileOut[]>(`${this.base}/files`);
  }

  uploadFile(file: File): Observable<FileOut> {
    const form = new FormData();
    form.append('file', file, file.name);
    return this.http.post<FileOut>(`${this.base}/files`, form);
  }

  deleteFile(id: number): Observable<void> {
    return this.http.delete<void>(`${this.base}/files/${id}`);
  }

  createRun(fileId: number, params: { low_speed_policy?: string }): Observable<RunOut> {
    return this.http.post<RunOut>(`${this.base}/runs`, { file_id: fileId, params });
  }

  runAllUnanalyzed(): Observable<RunOut[]> {
    return this.http.post<RunOut[]>(`${this.base}/runs/run-all-unanalyzed`, {});
  }

  listRuns(fileId?: number): Observable<RunOut[]> {
    const suffix = fileId != null ? `?file_id=${fileId}` : '';
    return this.http.get<RunOut[]>(`${this.base}/runs${suffix}`);
  }

  getRun(id: number): Observable<RunOut> {
    return this.http.get<RunOut>(`${this.base}/runs/${id}`);
  }

  deleteRun(id: number): Observable<void> {
    return this.http.delete<void>(`${this.base}/runs/${id}`);
  }

  getSegments(runId: number): Observable<SegmentRow[]> {
    return this.http.get<SegmentRow[]>(`${this.base}/runs/${runId}/segments`);
  }

  getArtifactText(runId: number, name: string): Observable<string> {
    return this.http.get(this.artifactUrl(runId, name), { responseType: 'text' });
  }

  getDashboard(): Observable<DashboardOut> {
    return this.http.get<DashboardOut>(`${this.base}/dashboard`);
  }

  getGlobalMap(): Observable<GeoJsonFeatureCollection> {
    return this.http.get<GeoJsonFeatureCollection>(`${this.base}/global-map`);
  }

  rebuildGlobalMap(): Observable<GeoJsonFeatureCollection> {
    return this.http.post<GeoJsonFeatureCollection>(`${this.base}/global-map/rebuild`, {});
  }

  artifactUrl(runId: number, name: string): string {
    return `${this.base}/runs/${runId}/artifacts/${name}`;
  }

  logUrl(runId: number): string {
    return `${this.base}/runs/${runId}/log`;
  }

  listRunArtifacts(runId: number): Observable<ArtifactEntry[]> {
    return this.http.get<ArtifactEntry[]>(`${this.base}/runs/${runId}/artifact-list`);
  }

  listReferences(): Observable<ReferenceOut[]> {
    return this.http.get<ReferenceOut[]>(`${this.base}/references`);
  }

  uploadReference(file: File, measuredAt?: string): Observable<ReferenceOut> {
    const form = new FormData();
    form.append('file', file, file.name);
    if (measuredAt != null) {
      form.append('measured_at', measuredAt);
    }
    return this.http.post<ReferenceOut>(`${this.base}/references`, form);
  }

  getReference(id: number): Observable<ReferenceOut> {
    return this.http.get<ReferenceOut>(`${this.base}/references/${id}`);
  }

  deleteReference(id: number): Observable<void> {
    return this.http.delete<void>(`${this.base}/references/${id}`);
  }

  getReferenceIntervals(id: number): Observable<ReferenceIntervalRow[]> {
    return this.http.get<ReferenceIntervalRow[]>(`${this.base}/references/${id}/intervals`);
  }

  getReferenceGeojson(id: number): Observable<GeoJsonFeatureCollection> {
    return this.http.get<GeoJsonFeatureCollection>(`${this.base}/references/${id}/geojson`);
  }

  createComparison(runId: number, referenceId: number): Observable<ComparisonOut> {
    return this.http.post<ComparisonOut>(`${this.base}/comparisons`,
      { run_id: runId, reference_id: referenceId });
  }

  listComparisons(runId?: number): Observable<ComparisonOut[]> {
    const suffix = runId != null ? `?run_id=${runId}` : '';
    return this.http.get<ComparisonOut[]>(`${this.base}/comparisons${suffix}`);
  }

  getComparison(id: number): Observable<ComparisonOut> {
    return this.http.get<ComparisonOut>(`${this.base}/comparisons/${id}`);
  }

  deleteComparison(id: number): Observable<void> {
    return this.http.delete<void>(`${this.base}/comparisons/${id}`);
  }

  comparisonArtifactUrl(id: number, name: string): string {
    return `${this.base}/comparisons/${id}/artifacts/${name}`;
  }

  getComparisonChartData(id: number): Observable<ChartData> {
    return this.http.get<ChartData>(this.comparisonArtifactUrl(id, 'chart_data.json'));
  }

  createAggregate(referenceId: number, runIds: number[]): Observable<AggregateOut> {
    return this.http.post<AggregateOut>(`${this.base}/aggregate-comparisons`,
      { reference_id: referenceId, run_ids: runIds });
  }

  listAggregates(): Observable<AggregateOut[]> {
    return this.http.get<AggregateOut[]>(`${this.base}/aggregate-comparisons`);
  }

  getAggregate(id: number): Observable<AggregateOut> {
    return this.http.get<AggregateOut>(`${this.base}/aggregate-comparisons/${id}`);
  }

  deleteAggregate(id: number): Observable<void> {
    return this.http.delete<void>(`${this.base}/aggregate-comparisons/${id}`);
  }

  aggregateArtifactUrl(id: number, name: string): string {
    return `${this.base}/aggregate-comparisons/${id}/artifacts/${name}`;
  }

  getAggregateChartData(id: number): Observable<AggregateChartData> {
    return this.http.get<AggregateChartData>(this.aggregateArtifactUrl(id, 'chart_data.json'));
  }

  listCoefficientSets(): Observable<CoefficientSetOut[]> {
    return this.http.get<CoefficientSetOut[]>(`${this.base}/coefficient-sets`);
  }

  /** Provenance is exactly one of comparison_id / aggregate_comparison_id
   *  (the backend answers 422 otherwise). */
  createCoefficientSet(payload: {
    comparison_id?: number; aggregate_comparison_id?: number; model: string; name: string;
    vehicle_type: string; phone_model?: string | null;
    device_id?: string | null; vehicle_id?: string | null;
  }): Observable<CoefficientSetOut> {
    return this.http.post<CoefficientSetOut>(`${this.base}/coefficient-sets`, payload);
  }

  /** How many uploaded files a set with this FULL resolution key would be
   *  applied to — shown before creating/confirming, so a key that matches
   *  nothing (or that a more specific confirmed set already owns) is visible. */
  previewResolution(payload: {
    model: string; vehicle_type: string | null; phone_model: string | null;
    device_id: string | null; vehicle_id: string | null;
  }): Observable<PreviewResolutionOut> {
    return this.http.post<PreviewResolutionOut>(
      `${this.base}/coefficient-sets/preview-resolution`, payload);
  }

  confirmCoefficientSet(id: number, note?: string): Observable<ConfirmOut> {
    return this.http.post<ConfirmOut>(`${this.base}/coefficient-sets/${id}/confirm`, { note });
  }

  archiveCoefficientSet(id: number): Observable<CoefficientSetOut> {
    return this.http.post<CoefficientSetOut>(`${this.base}/coefficient-sets/${id}/archive`, {});
  }

  reanalyzeCoefficientSet(id: number): Observable<RunOut[]> {
    return this.http.post<RunOut[]>(`${this.base}/coefficient-sets/${id}/reanalyze`, {});
  }
}
