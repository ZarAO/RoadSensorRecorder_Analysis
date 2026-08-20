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
});
