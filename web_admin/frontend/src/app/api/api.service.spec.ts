import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController, provideHttpClientTesting,
} from '@angular/common/http/testing';

import { ApiService } from './api.service';

describe('ApiService', () => {
  let api: ApiService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    api = TestBed.inject(ApiService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('lists files from /api/files', () => {
    api.listFiles().subscribe();
    httpMock.expectOne('/api/files').flush([]);
  });

  it('creates a run with file_id and params', () => {
    api.createRun(7, { low_speed_policy: 'invalid' }).subscribe();
    const req = httpMock.expectOne('/api/runs');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({
      file_id: 7, params: { low_speed_policy: 'invalid' },
    });
    req.flush({});
  });

  it('builds artifact and log URLs', () => {
    expect(api.artifactUrl(3, 'plots/x.png')).toBe('/api/runs/3/artifacts/plots/x.png');
    expect(api.logUrl(3)).toBe('/api/runs/3/log');
  });

  it('uploads a reference as multipart FormData with measured_at', () => {
    const file = new File(['data'], 'ref.xlsx');
    api.uploadReference(file, '2026-01-01').subscribe();
    const req = httpMock.expectOne('/api/references');
    expect(req.request.method).toBe('POST');
    expect(req.request.body instanceof FormData).toBe(true);
    const body = req.request.body as FormData;
    expect((body.get('file') as File).name).toBe('ref.xlsx');
    expect(body.get('measured_at')).toBe('2026-01-01');
    req.flush({});
  });

  it('confirms a coefficient set with a note in the POST body', () => {
    api.confirmCoefficientSet(4, 'looks good').subscribe();
    const req = httpMock.expectOne('/api/coefficient-sets/4/confirm');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ note: 'looks good' });
    req.flush({});
  });

  it('lists comparisons filtered by run_id', () => {
    api.listComparisons(5).subscribe();
    httpMock.expectOne('/api/comparisons?run_id=5').flush([]);
  });
});
