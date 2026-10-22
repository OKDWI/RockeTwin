export type TelemetryRow = {
  mission_time_s: number;
  flight_phase: string;
  mpre104p: number;
  mrtd104t: number;
  mpre105p: number;
  mrtd105t: number;
  mmsw203x: number;
  mmsw205x: number;
  mmsw301x: number;
  vr01_state?: string;
  sv31_state?: string;
  sv03_state?: string;
  pv03_state?: string;
  vr06_state?: string;
  sv02_state?: string;
  pv02_state?: string;
  [key: string]: string | number | undefined;
};

export type Prediction = {
  fault_present: boolean;
  fault: string;
  subsystem: string;
  severity: number;
  mission_id?: string;
  mission_time_s?: number;
  readings_processed?: number;
  mode?: string;
};

export type ManifestRow = {
  mission_id: string;
  label: string;
  fault_onset_time_s: number | null;
  n_telemetry_rows?: number;
};

export type ChartPoint = {
  time: number;
  loxPressure: number;
  rp1Pressure: number;
  loxTemp: number;
  rp1Temp: number;
  mmsw203x: number;
  mmsw205x: number;
  mmsw301x: number;
  fault: string;
  actualFault: boolean;
};
