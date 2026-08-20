import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import {
  DashboardOut, FileOut, GeoJsonFeatureCollection, RunOut, SegmentRow,
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
}
