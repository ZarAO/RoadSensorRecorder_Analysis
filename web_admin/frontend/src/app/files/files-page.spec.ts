import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';

import { ApiService } from '../api/api.service';
import { FileOut, RecordingMeta } from '../api/dto';
import { FilesPage } from './files-page';

const META: RecordingMeta = {
  schema: 2,
  preamble: {},
  vehicle: { vehicle_type: 'sedan', vehicle_make_model: 'Skoda Octavia' },
  events: [],
  footer: { reason: 'user' },
  footer_count: 1,
  warnings: [],
  clean_stop: true,
  incident_count: 0,
};

const FILE: FileOut = {
  id: 1, filename: 'drive.csv', size_bytes: 1000,
  uploaded_at: '2026-08-20T10:00:00Z', source_deleted: false,
  duration_s: 120, fs_hz: 100, gps_coverage_ratio: 0.98,
  recording_meta: META, runs_count: 0,
};

describe('FilesPage', () => {
  function setup(file: FileOut = FILE) {
    const api = {
      listFiles: () => of([file]),
      uploadFile: () => of(file),
      deleteFile: () => of(void 0),
      createRun: () => of(null),
      runAllUnanalyzed: () => of([]),
    } as unknown as ApiService;

    TestBed.configureTestingModule({
      imports: [FilesPage],
      providers: [provideRouter([]), { provide: ApiService, useValue: api }],
    });
    return TestBed.createComponent(FilesPage);
  }

  it('renders the vehicle chip and clean-stop badge', async () => {
    const fixture = setup();
    await fixture.whenStable();
    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('sedan');
    expect(text).toContain('Skoda Octavia');
    expect(text).toContain('чиста зупинка');
  });

  it('renders pre-v2.1 badge and no-profile chip for bare files', async () => {
    const bare: FileOut = {
      ...FILE,
      recording_meta: { ...META, schema: null, vehicle: {}, footer: null,
                        clean_stop: false },
    };
    const fixture = setup(bare);
    await fixture.whenStable();
    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('без профілю');
    expect(text).toContain('pre-v2.1');
  });
});
