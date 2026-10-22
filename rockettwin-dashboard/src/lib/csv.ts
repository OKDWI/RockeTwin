import Papa from 'papaparse';
import type { ManifestRow, TelemetryRow } from '../types';

const REQUIRED = ['mission_time_s', 'mpre104p', 'mrtd104t', 'mpre105p', 'mrtd105t', 'mmsw203x', 'mmsw205x', 'mmsw301x'];

function parseFile<T>(file: File): Promise<T[]> {
  return new Promise((resolve, reject) => {
    Papa.parse<T>(file, {
      header: true, skipEmptyLines: true, dynamicTyping: true,
      complete: (result) => {
        if (result.errors.length) {
          const severe = result.errors.find((error) => error.type !== 'FieldMismatch');
          if (severe) return reject(new Error(`CSV parse error: ${severe.message}`));
        }
        resolve(result.data);
      },
      error: (error) => reject(error),
    });
  });
}

export async function parseMissionFile(file: File): Promise<TelemetryRow[]> {
  const data = await parseFile<Record<string, unknown>>(file);
  if (!data.length) throw new Error(`${file.name} contains no telemetry rows.`);
  const missing = REQUIRED.filter((column) => !(column in data[0]));
  if (missing.length) throw new Error(`${file.name} is missing required columns: ${missing.join(', ')}`);
  const rows = data.map((raw, index) => {
    const row = raw as unknown as TelemetryRow;
    for (const key of REQUIRED) {
      if (!Number.isFinite(Number(row[key]))) throw new Error(`${file.name}, row ${index + 2}: ${key} is not numeric.`);
    }
    if (!Number.isFinite(Number(row.mission_time_s))) throw new Error(`${file.name}, row ${index + 2}: invalid mission_time_s.`);
    return { ...row, mission_time_s: Number(row.mission_time_s) };
  }).sort((a, b) => a.mission_time_s - b.mission_time_s);
  for (let i = 1; i < rows.length; i++) {
    if (rows[i].mission_time_s <= rows[i - 1].mission_time_s) {
      throw new Error(`${file.name} has duplicate or non-increasing mission timestamps near row ${i + 2}.`);
    }
  }
  return rows;
}

export async function parseManifestFile(file: File): Promise<ManifestRow[]> {
  const data = await parseFile<Record<string, unknown>>(file);
  return data.map((row) => ({
    mission_id: String(row.mission_id ?? ''),
    label: String(row.label ?? 'unknown'),
    fault_onset_time_s: row.fault_onset_time_s === '' || row.fault_onset_time_s == null || !Number.isFinite(Number(row.fault_onset_time_s)) ? null : Number(row.fault_onset_time_s),
    n_telemetry_rows: Number(row.n_telemetry_rows) || undefined,
  })).filter((row) => row.mission_id);
}

export function missionIdFromFilename(name: string): string {
  return name.replace(/\.csv$/i, '').replace(/[^a-zA-Z0-9_-]/g, '_').slice(0, 90) || `mission_${Date.now()}`;
}
