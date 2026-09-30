/** Wire contract v1, shared with ingest/juso.py. No provider keys or DB writer here. */
export interface AddressSelection {
  provider: 'juso';
  pnu: string;
  admCd: string;
  rnMgtSn: string;
  udrtYn: string;
  buldMnnm: string;
  buldSlno: string;
  mtYn: string;
  lnbrMnnm: string;
  lnbrSlno: string;
  bdMgtSn: string;
  roadAddrPart1: string;
  jibunAddr: string;
  bdNm: string;
  rn: string;
  sggNm: string;
  emdNm: string;
}

export interface RegisteredLocation {
  status: 'ready';
  lng: number;
  lat: number;
  coordinate_provider: 'juso' | 'vworld';
  source_crs: 'EPSG:5179' | 'EPSG:4326';
  source_x: number;
  source_y: number;
  reason: 'juso_coordinate_key_pending' | null;
}

export type CoordinateOutcome = RegisteredLocation | {
  status: 'not_found' | 'invalid';
  coordinate_provider: 'juso' | 'vworld';
};

/** Server implementations belong to the authorized Route Handler or /ingest.
 * Search uses no-store. Locate runs once at registration, persists only in owner candidate.
 * Revalidate selection server-side; caller coordinates never enter the shared cache.
 */
export interface AddressProvider {
  search(query: string): Promise<{ total: number; choices: AddressSelection[] }>;
  locate(selection: AddressSelection): Promise<CoordinateOutcome>;
}
