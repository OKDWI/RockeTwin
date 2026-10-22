import type { Prediction, TelemetryRow } from '../types';

const API = '/api';

export async function checkHealth(): Promise<{ status: string; model_available: boolean; model_loaded: boolean }> {
  const response = await fetch(`${API}/health`);
  if (!response.ok) throw new Error(`API health check failed (${response.status})`);
  return response.json();
}

export async function resetMission(missionId: string): Promise<void> {
  const response = await fetch(`${API}/missions/${encodeURIComponent(missionId)}/reset`, { method: 'POST' });
  if (!response.ok) throw new Error(`Mission reset failed (${response.status}): ${await response.text()}`);
}

export async function predictReading(missionId: string, row: TelemetryRow): Promise<Prediction> {
  const payload = {
    mission_time_s: Number(row.mission_time_s),
    mpre104p: Number(row.mpre104p),
    mrtd104t: Number(row.mrtd104t),
    mpre105p: Number(row.mpre105p),
    mrtd105t: Number(row.mrtd105t),
    mmsw203x: Number(row.mmsw203x),
    mmsw205x: Number(row.mmsw205x),
    mmsw301x: Number(row.mmsw301x),
    flight_phase: String(row.flight_phase || 'UNKNOWN'),
  };
  const response = await fetch(`${API}/missions/${encodeURIComponent(missionId)}/predict`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`Inference failed (${response.status}): ${detail}`);
  }
  return response.json();
}
