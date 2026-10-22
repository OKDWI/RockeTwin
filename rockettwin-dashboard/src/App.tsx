import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import {
  Activity, AlertOctagon, AlertTriangle, ArrowDownToLine, Check, CheckCircle2,
  ChevronDown, CircleDot, Clock3, Cpu, Gauge, HardDrive, Layers3, Pause, Play,
  Radio, RotateCcw, Satellite, ShieldCheck, Signal, SlidersHorizontal, Terminal,
  Upload, Wifi, XCircle, Zap,
} from 'lucide-react';
import {
  CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts';
import { checkHealth, predictReading, resetMission } from './lib/api';
import { missionIdFromFilename, parseManifestFile, parseMissionFile } from './lib/csv';
import type { ChartPoint, ManifestRow, Prediction, TelemetryRow } from './types';

type Mission = { id: string; name: string; rows: TelemetryRow[]; source: string };
type LogItem = { id: number; time: string; kind: 'system' | 'good' | 'warn' | 'bad'; message: string };
const CHART_WINDOW = 100;

function fmt(value: number | undefined, digits = 2) {
  return Number.isFinite(value) ? Number(value).toLocaleString('en-US', { maximumFractionDigits: digits, minimumFractionDigits: digits }) : '—';
}
function clock(value: number) {
  if (!Number.isFinite(value)) return '00:00:00';
  const seconds = Math.max(0, Math.floor(value));
  return `${String(Math.floor(seconds / 3600)).padStart(2, '0')}:${String(Math.floor((seconds % 3600) / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
}
function phaseLabel(phase: string | undefined) {
  return (phase || 'UNKNOWN').replaceAll('_', ' ');
}
function faultLabel(fault: string | undefined) {
  if (!fault || fault === 'nominal') return 'No active fault';
  return fault.replaceAll('_', ' ');
}

export default function App() {
  const [missions, setMissions] = useState<Mission[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [manifest, setManifest] = useState<ManifestRow[]>([]);
  const [currentIndex, setCurrentIndex] = useState(-1);
  const [currentRow, setCurrentRow] = useState<TelemetryRow | null>(null);
  const [prediction, setPrediction] = useState<Prediction | null>(null);
  const [history, setHistory] = useState<ChartPoint[]>([]);
  const [logs, setLogs] = useState<LogItem[]>([]);
  const [playing, setPlaying] = useState(false);
  const [busy, setBusy] = useState(false);
  const [speed, setSpeed] = useState(250);
  const [apiState, setApiState] = useState<'checking' | 'online' | 'offline'>('checking');
  const [modelAvailable, setModelAvailable] = useState(false);
  const [modelLoaded, setModelLoaded] = useState(false);
  const [error, setError] = useState('');
  const [showLoader, setShowLoader] = useState(false);
  const [activeTab, setActiveTab] = useState<'telemetry' | 'sensors'>('telemetry');
  const stopRef = useRef(false);
  const runIdRef = useRef(0);
  const logIdRef = useRef(0);
  const lastLoggedFaultRef = useRef<string>('');
  const fileInputRef = useRef<HTMLInputElement>(null);
  const manifestInputRef = useRef<HTMLInputElement>(null);
  const selectedMission = missions.find((mission) => mission.id === selectedId) ?? null;
  const truth = useMemo(() => manifest.find((item) => item.mission_id === selectedId || item.mission_id === selectedMission?.name), [manifest, selectedId, selectedMission]);
  const onset = truth?.fault_onset_time_s ?? null;
  const completed = Boolean(selectedMission && currentIndex >= selectedMission.rows.length - 1 && currentIndex >= 0 && !playing);
  const progress = selectedMission && selectedMission.rows.length ? Math.max(0, (currentIndex + 1) / selectedMission.rows.length * 100) : 0;

  const addLog = useCallback((kind: LogItem['kind'], message: string) => {
    const item = { id: ++logIdRef.current, time: new Date().toLocaleTimeString('en-GB', { hour12: false }), kind, message };
    setLogs((old) => [item, ...old].slice(0, 30));
  }, []);

  const refreshHealth = useCallback(async () => {
    try {
      const health = await checkHealth();
      setApiState(health.status === 'ok' ? 'online' : 'offline');
      setModelAvailable(Boolean(health.model_available));
      setModelLoaded(Boolean(health.model_loaded));
    } catch {
      setApiState('offline'); setModelAvailable(false); setModelLoaded(false);
    }
  }, []);

  useEffect(() => {
    void refreshHealth();
    const timer = window.setInterval(() => void refreshHealth(), 10000);
    addLog('system', 'Mission control interface initialized.');
    return () => { window.clearInterval(timer); stopRef.current = true; runIdRef.current += 1; };
  }, [refreshHealth, addLog]);

  const handleMissionFiles = async (files: FileList | null) => {
    if (!files?.length) return;
    setError(''); setShowLoader(true); stopRef.current = true; setPlaying(false);
    try {
      const incoming: Mission[] = [];
      for (const file of Array.from(files).filter((item) => item.name.toLowerCase().endsWith('.csv'))) {
        const rows = await parseMissionFile(file);
        const id = missionIdFromFilename(file.name);
        incoming.push({ id, name: id, rows, source: file.name });
      }
      if (!incoming.length) throw new Error('Choose one or more mission telemetry CSV files.');
      setMissions((previous) => {
        const merged = [...previous];
        for (const mission of incoming) {
          const existing = merged.findIndex((item) => item.id === mission.id);
          if (existing >= 0) merged[existing] = mission; else merged.push(mission);
        }
        return merged.sort((a, b) => a.name.localeCompare(b.name));
      });
      setSelectedId(incoming[0].id); setCurrentIndex(-1); setCurrentRow(null); setPrediction(null); setHistory([]); lastLoggedFaultRef.current = '';
      setLogs([]); addLog('good', `Loaded ${incoming.length} mission file${incoming.length === 1 ? '' : 's'} · ${incoming.reduce((sum, item) => sum + item.rows.length, 0).toLocaleString()} readings.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to load mission CSV.');
    } finally { setShowLoader(false); if (fileInputRef.current) fileInputRef.current.value = ''; }
  };

  const handleManifest = async (file?: File) => {
    if (!file) return;
    try {
      const parsed = await parseManifestFile(file);
      setManifest(parsed);
      addLog('good', `Loaded ground-truth manifest with ${parsed.length} mission records.`);
      setError('');
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to load manifest.'); }
    if (manifestInputRef.current) manifestInputRef.current.value = '';
  };

  const chooseMission = async (id: string) => {
    stopRef.current = true; runIdRef.current += 1; setPlaying(false); setBusy(false);
    setSelectedId(id); setCurrentIndex(-1); setCurrentRow(null); setPrediction(null); setHistory([]); setError(''); lastLoggedFaultRef.current = '';
    if (id) addLog('system', `Mission selected: ${id}. Ready to initialize stream.`);
  };

  const resetReplay = async () => {
    if (!selectedMission) return;
    stopRef.current = true; runIdRef.current += 1; setPlaying(false); setBusy(true); setError('');
    try {
      await resetMission(selectedMission.id);
      setCurrentIndex(-1); setCurrentRow(null); setPrediction(null); setHistory([]); lastLoggedFaultRef.current = '';
      addLog('system', `Stream state reset for ${selectedMission.id}.`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not reset mission state.'); }
    finally { setBusy(false); }
  };

  const pauseReplay = () => {
    stopRef.current = true; setPlaying(false);
    addLog('warn', 'Replay paused by operator.');
  };

  const playReplay = async () => {
    if (!selectedMission || apiState !== 'online' || !modelAvailable) return;
    if (currentIndex >= selectedMission.rows.length - 1) {
      setError('Mission replay is complete. Reset the mission to run it again.'); return;
    }
    setError(''); stopRef.current = false; setPlaying(true); setBusy(true);
    const runId = ++runIdRef.current;
    try {
      let start = currentIndex + 1;
      if (start === 0) {
        await resetMission(selectedMission.id);
        if (stopRef.current || runIdRef.current !== runId) return;
        addLog('system', `Replay started · ${selectedMission.name} · ${selectedMission.rows.length.toLocaleString()} samples.`);
      } else addLog('system', `Replay resumed at sample ${start + 1}.`);
      for (let index = start; index < selectedMission.rows.length; index += 1) {
        if (stopRef.current || runIdRef.current !== runId) break;
        const row = selectedMission.rows[index];
        const result = await predictReading(selectedMission.id, row);
        if (runIdRef.current !== runId) break;
        const isActualFault = onset !== null && row.mission_time_s >= onset;
        const point: ChartPoint = {
          time: row.mission_time_s, loxPressure: Number(row.mpre104p), rp1Pressure: Number(row.mpre105p),
          loxTemp: Number(row.mrtd104t), rp1Temp: Number(row.mrtd105t),
          mmsw203x: Number(row.mmsw203x), mmsw205x: Number(row.mmsw205x), mmsw301x: Number(row.mmsw301x),
          fault: result.fault, actualFault: isActualFault,
        };
        setCurrentIndex(index); setCurrentRow(row); setPrediction(result);
        setHistory((old) => [...old, point].slice(-CHART_WINDOW));
        if (result.fault_present && result.fault !== lastLoggedFaultRef.current) {
          addLog('bad', `Classifier reports ${faultLabel(result.fault)} · ${String(result.subsystem).toUpperCase()} subsystem · severity ${result.severity}/3.`);
        } else if (!result.fault_present && lastLoggedFaultRef.current) addLog('good', 'Classifier returned to nominal state.');
        lastLoggedFaultRef.current = result.fault_present ? result.fault : ''; 
        if (onset !== null && row.mission_time_s >= onset && index > 0 && selectedMission.rows[index - 1].mission_time_s < onset) {
          addLog('warn', `Ground-truth fault onset crossed at ${fmt(onset, 1)} s (manifest reference).`);
        }
        if (index % 100 === 0 && index > 0) addLog('system', `${index + 1} telemetry readings processed.`);
        await new Promise<void>((resolve) => window.setTimeout(resolve, speed));
      }
      if (!stopRef.current && runIdRef.current === runId) {
        setPlaying(false); addLog('good', `Replay complete · ${selectedMission.name}.`);
      }
    } catch (reason) {
      if (runIdRef.current === runId) {
        setPlaying(false); setError(reason instanceof Error ? reason.message : 'Replay failed.');
        addLog('bad', 'Replay halted because an API request failed. Reset before restarting from sample one.');
      }
    } finally {
      if (runIdRef.current === runId) setBusy(false);
    }
  };

  const status = prediction?.fault_present ? (prediction.severity >= 3 ? 'critical' : 'warning') : prediction ? 'nominal' : 'standby';
  const statusText = prediction ? prediction.fault_present ? (prediction.severity >= 3 ? 'FAULT DETECTED' : 'ANOMALY DETECTED') : 'SYSTEM NOMINAL' : 'AWAITING DATA';

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><Satellite size={22} strokeWidth={1.8}/></div><div><div className="brand-name">ROCKET<span>TWIN</span></div><div className="brand-sub">AUTONOMOUS HEALTH SYSTEMS</div></div></div>
      <div className="side-rule"/>
      <div className="nav-label">OPERATIONS</div>
      <div className="nav-item active"><Gauge size={17}/><span>Mission control</span><span className="nav-dot"/></div>
      <div className="nav-item muted"><Activity size={17}/><span>Telemetry stream</span><span className="nav-count">LIVE</span></div>
      <div className="nav-item muted"><ShieldCheck size={17}/><span>Health intelligence</span></div>
      <div className="nav-label nav-label-spaced">SYSTEM</div>
      <div className="system-check"><span className={`status-dot ${apiState === 'online' ? 'green' : apiState === 'offline' ? 'red' : 'amber'}`}/><div><div className="system-name">Inference API</div><div className="system-desc">{apiState === 'online' ? 'Connected · :8000' : apiState === 'offline' ? 'Connection unavailable' : 'Checking endpoint…'}</div></div></div>
      <div className="system-check"><span className={`status-dot ${modelAvailable ? 'green' : 'red'}`}/><div><div className="system-name">XGBoost model</div><div className="system-desc">{modelAvailable ? modelLoaded ? 'Loaded in memory' : 'Artifact available' : 'Artifact not found'}</div></div></div>
      <div className="sidebar-bottom"><div className="sidebar-foot-icon"><Cpu size={16}/></div><div><div className="system-name">ROCKET_A / DIGITAL TWIN</div><div className="system-desc">Prototype build 0.1.0</div></div><span className="version-pill">DEV</span></div>
    </aside>

    <main className="main-area">
      <header className="topbar"><div className="breadcrumb"><span>OPERATIONS</span><span className="crumb-slash">/</span><strong>MISSION CONTROL</strong></div><div className="topbar-right"><div className="utc-chip"><span className="status-dot green"/> LOCAL SIMULATION ENVIRONMENT</div><div className="topbar-separator"/><div className="operator"><div className="operator-avatar">RT</div><div><div className="operator-name">Flight operator</div><div className="operator-role">ENGINEERING CONSOLE</div></div></div></div></header>

      <div className="page-content">
        <section className="page-heading"><div><div className="eyebrow"><span className="eyebrow-line"/> INTELLIGENT MISSION MONITORING</div><h1>Mission <span>Control.</span></h1><p className="page-subtitle">Real-time telemetry replay, anomaly detection, and subsystem health assessment.</p></div><div className="heading-status"><span className={`status-dot ${apiState === 'online' ? 'green' : apiState === 'offline' ? 'red' : 'amber'}`}/><span>{apiState === 'online' ? 'BACKEND CONNECTED' : apiState === 'offline' ? 'BACKEND OFFLINE' : 'CONNECTING TO BACKEND'}</span><span className="heading-status-sep">·</span><span>BUILD 0.1.0</span></div></section>

        <section className="mission-toolbar panel"><div className="mission-select-wrap"><div className="toolbar-icon"><Layers3 size={18}/></div><div className="mission-select-content"><label htmlFor="mission-select">ACTIVE MISSION</label><div className="select-line"><select id="mission-select" value={selectedId} onChange={(event) => void chooseMission(event.target.value)} disabled={playing || missions.length === 0}><option value="">{missions.length ? 'Select a mission' : 'Load telemetry CSV to begin'}</option>{missions.map((mission) => <option value={mission.id} key={mission.id}>{mission.name} · {mission.rows.length.toLocaleString()} samples</option>)}</select><ChevronDown size={15}/></div></div></div><div className="toolbar-divider"/><div className="mission-meta"><span className="meta-label">SOURCE</span><span className="meta-value source-value">{selectedMission?.source ?? 'No source loaded'}</span></div><div className="mission-meta"><span className="meta-label">SAMPLES</span><span className="meta-value mono">{selectedMission ? selectedMission.rows.length.toLocaleString() : '—'}</span></div><div className="toolbar-actions"><button className="button button-secondary" onClick={() => fileInputRef.current?.click()} disabled={playing || showLoader}><Upload size={15}/>{showLoader ? 'Loading…' : 'Load mission'}</button><button className="button button-ghost" onClick={() => manifestInputRef.current?.click()} title="Load optional manifest.csv ground truth"><ArrowDownToLine size={15}/>Manifest</button><input ref={fileInputRef} className="hidden-input" type="file" accept=".csv,text/csv" multiple onChange={(event) => void handleMissionFiles(event.target.files)}/><input ref={manifestInputRef} className="hidden-input" type="file" accept=".csv,text/csv" onChange={(event) => void handleManifest(event.target.files?.[0])}/></div></section>

        {error && <div className="error-banner"><AlertTriangle size={17}/><span>{error}</span><button onClick={() => setError('')} aria-label="Dismiss error"><XCircle size={16}/></button></div>}
        {!missions.length && <section className="welcome-panel panel"><div className="welcome-orbit orbit-one"/><div className="welcome-orbit orbit-two"/><div className="welcome-copy"><div className="welcome-icon"><Radio size={22}/></div><div className="eyebrow">READY FOR TELEMETRY INGESTION</div><h2>Bring a mission online.</h2><p>Load one or more recorded mission CSVs from <code>dataset/telemetry/</code>. RocketTwin will replay each sample through your existing FastAPI streaming inference endpoint — one reading at a time.</p><div className="welcome-actions"><button className="button button-primary" onClick={() => fileInputRef.current?.click()}><Upload size={16}/> Load telemetry CSV</button><span className="supported-format"><Check size={14}/> Existing dataset format supported</span></div><div className="welcome-foot"><span><span className="status-dot green"/> CSV parser ready</span><span><span className={`status-dot ${apiState === 'online' ? 'green' : 'amber'}`}/>{apiState === 'online' ? 'API reachable' : 'Waiting for API'}</span><span><span className={`status-dot ${modelAvailable ? 'green' : 'amber'}`}/>{modelAvailable ? 'Model artifact found' : 'Model check pending'}</span></div></div><div className="welcome-graphic"><div className="radar-ring ring-a"/><div className="radar-ring ring-b"/><div className="radar-ring ring-c"/><div className="radar-center"><Satellite size={46}/></div><div className="radar-cross cross-x"/><div className="radar-cross cross-y"/><div className="radar-point point-a"/><div className="radar-point point-b"/><div className="radar-coord coord-a">18°31′N</div><div className="radar-coord coord-b">073°51′E</div></div></section>}

        {missions.length > 0 && <>
          <section className="metrics-grid">
            <MetricCard label="MISSION ELAPSED" value={currentRow ? clock(currentRow.mission_time_s) : '00:00:00'} note={currentRow ? `T+${fmt(currentRow.mission_time_s, 1)} seconds` : 'Awaiting replay start'} icon={<Clock3 size={18}/>} accent="cyan"/>
            <MetricCard label="SYSTEM HEALTH" value={status === 'nominal' ? 'NOMINAL' : status === 'critical' ? 'CRITICAL' : status === 'warning' ? 'WARNING' : 'STANDBY'} note={prediction ? prediction.fault_present ? `Severity ${prediction.severity} / 3` : 'No active classifier fault' : 'No prediction received'} icon={<ShieldCheck size={18}/>} accent={status === 'critical' ? 'red' : status === 'warning' ? 'amber' : 'green'} status={status}/>
            <MetricCard label="READINGS PROCESSED" value={prediction?.readings_processed?.toLocaleString() ?? '0'} note={`Of ${selectedMission?.rows.length.toLocaleString() ?? '0'} available samples`} icon={<Activity size={18}/>} accent="violet"/>
            <MetricCard label="FAULT CLASSIFICATION" value={prediction ? prediction.fault_present ? faultLabel(prediction.fault) : 'NOMINAL' : '—'} note={prediction?.subsystem && prediction.subsystem !== 'none' ? `${prediction.subsystem.toUpperCase()} subsystem` : 'Awaiting model inference'} icon={<AlertOctagon size={18}/>} accent={prediction?.fault_present ? 'red' : 'cyan'} compact/>
          </section>

          <section className="workspace-grid">
            <div className="left-column">
              <div className="panel chart-panel"><div className="panel-heading"><div><div className="panel-kicker">LIVE DATA STREAM <span className="live-pulse"/></div><h2>Telemetry channels</h2><p className="panel-description">Rolling sensor history · last {Math.min(CHART_WINDOW, history.length)} samples</p></div><div className="chart-tabs"><button className={activeTab === 'telemetry' ? 'selected' : ''} onClick={() => setActiveTab('telemetry')}>Pressure / temp</button><button className={activeTab === 'sensors' ? 'selected' : ''} onClick={() => setActiveTab('sensors')}>Sensor signals</button></div></div>
                {history.length ? <div className="charts-stack">{activeTab === 'telemetry' ? <><TelemetryChart title="TANK PRESSURE" unit="psia" data={history} lines={[{ key: 'loxPressure', name: 'LOX tank', color: '#5de0f2' }, { key: 'rp1Pressure', name: 'RP-1 tank', color: '#a99bff' }]} onset={onset}/><TelemetryChart title="TANK TEMPERATURE" unit="°R" data={history} lines={[{ key: 'loxTemp', name: 'LOX tank', color: '#5de0f2' }, { key: 'rp1Temp', name: 'RP-1 tank', color: '#a99bff' }]} onset={onset}/></> : <TelemetryChart title="SWITCH / SENSOR CHANNELS" unit="signal" data={history} lines={[{ key: 'mmsw203x', name: 'MMSW203X', color: '#5de0f2' }, { key: 'mmsw205x', name: 'MMSW205X', color: '#a99bff' }, { key: 'mmsw301x', name: 'MMSW301X', color: '#f7b86b' }]} onset={onset}/>}</div> : <div className="chart-empty"><div className="chart-empty-icon"><Activity size={24}/></div><strong>Telemetry stream is idle</strong><span>Start mission replay to populate live channel history.</span><div className="empty-skeleton"><i/><i/><i/><i/><i/><i/><i/><i/><i/><i/><i/><i/></div></div>}
                <div className="chart-footer"><div className="chart-footer-item"><span className="footer-label">CURRENT FLIGHT PHASE</span><strong>{phaseLabel(currentRow?.flight_phase)}</strong></div><div className="chart-footer-item"><span className="footer-label">STREAM UPDATE</span><strong>{currentRow ? 'Sequential inference' : 'Waiting for first sample'}</strong></div><div className="chart-footer-item"><span className="footer-label">GROUND TRUTH</span><strong className={truth && truth.label !== 'nominal' ? 'text-amber' : ''}>{truth ? truth.label.replaceAll('_', ' ') : 'Manifest not loaded'}</strong></div></div>
              </div>
              <div className="panel sensor-panel"><div className="panel-heading compact-heading"><div><div className="panel-kicker">INSTRUMENTATION</div><h2>Sensor snapshot</h2></div><span className="instrument-count">07 CHANNELS</span></div><div className="sensor-grid"><SensorCard name="MPRE104P" description="LOX tank pressure" value={currentRow?.mpre104p} unit="psia" color="cyan"/><SensorCard name="MPRE105P" description="RP-1 tank pressure" value={currentRow?.mpre105p} unit="psia" color="violet"/><SensorCard name="MRTD104T" description="LOX tank temperature" value={currentRow?.mrtd104t} unit="°R" color="cyan"/><SensorCard name="MRTD105T" description="RP-1 tank temperature" value={currentRow?.mrtd105t} unit="°R" color="violet"/><SensorCard name="MMSW203X" description="Switch channel 203" value={currentRow?.mmsw203x} unit="signal" color="amber"/><SensorCard name="MMSW205X" description="Switch channel 205" value={currentRow?.mmsw205x} unit="signal" color="amber"/><SensorCard name="MMSW301X" description="Switch channel 301" value={currentRow?.mmsw301x} unit="signal" color="amber"/></div></div>
            </div>
            <div className="right-column">
              <div className="panel replay-panel"><div className="panel-heading compact-heading"><div><div className="panel-kicker">OPERATOR CONTROLS</div><h2>Mission replay</h2></div><div className={`replay-state ${playing ? 'state-running' : completed ? 'state-done' : ''}`}><span className="status-dot"/>{playing ? 'RUNNING' : completed ? 'COMPLETE' : currentIndex >= 0 ? 'PAUSED' : 'STANDBY'}</div></div><div className="replay-visual"><div className={`replay-big-icon ${playing ? 'is-playing' : ''}`}><Satellite size={31}/></div><div className="replay-mission-name">{selectedMission?.name}</div><div className="replay-mission-sub">ROCKET_A · SYNTHETIC TELEMETRY</div><div className="replay-clock">T+ <span>{fmt(currentRow?.mission_time_s, 1)}</span> <small>SEC</small></div></div><div className="progress-labels"><span>MISSION PROGRESS</span><span className="mono">{selectedMission ? `${Math.max(0, currentIndex + 1).toLocaleString()} / ${selectedMission.rows.length.toLocaleString()}` : '0 / 0'}</span></div><div className="progress-track"><div className="progress-fill" style={{ width: `${progress}%` }}/><div className="progress-glow" style={{ left: `${progress}%` }}/></div><div className="progress-time"><span>START · T+{selectedMission ? fmt(selectedMission.rows[0]?.mission_time_s, 0) : '0'}s</span><span>END · T+{selectedMission ? fmt(selectedMission.rows[selectedMission.rows.length - 1]?.mission_time_s, 0) : '—'}s</span></div><div className="replay-buttons"><button className="button button-primary play-button" onClick={() => playing ? pauseReplay() : void playReplay()} disabled={!selectedMission || apiState !== 'online' || !modelAvailable || busy && !playing || completed}>{playing ? <><Pause size={17} fill="currentColor"/> Pause stream</> : <><Play size={17} fill="currentColor"/> {currentIndex >= 0 ? 'Resume replay' : 'Start replay'}</>}</button><button className="icon-button" onClick={() => void resetReplay()} disabled={!selectedMission || busy} title="Reset stream and rolling feature history"><RotateCcw size={17}/></button></div><div className="speed-control"><div className="speed-label"><SlidersHorizontal size={14}/> REPLAY INTERVAL <span>·</span> {speed} ms / sample</div><div className="speed-options">{[{label:'4×',value:60},{label:'2×',value:125},{label:'1×',value:250},{label:'0.5×',value:500},{label:'0.25×',value:1000}].map((option) => <button key={option.value} className={speed === option.value ? 'speed-active' : ''} onClick={() => setSpeed(option.value)} disabled={playing}>{option.label}</button>)}</div></div>{(!modelAvailable || apiState !== 'online') && <div className="control-warning"><AlertTriangle size={14}/>{apiState !== 'online' ? 'Start FastAPI on port 8000 to enable replay.' : 'Model artifact unavailable. Train/load the model before replay.'}</div>}</div>

              <div className="panel fault-panel"><div className="panel-heading compact-heading"><div><div className="panel-kicker">INFERENCE OUTPUT</div><h2>Health assessment</h2></div><div className={`health-icon ${status}`}><ShieldCheck size={18}/></div></div><div className={`health-banner ${status}`}><div className="health-banner-icon">{status === 'nominal' ? <CheckCircle2 size={19}/> : status === 'critical' ? <AlertOctagon size={19}/> : status === 'warning' ? <AlertTriangle size={19}/> : <CircleDot size={19}/>}</div><div><strong>{statusText}</strong><span>{prediction ? prediction.fault_present ? 'Classifier indicates a non-nominal condition' : 'Classifier reports nominal operation' : 'No inference result yet'}</span></div></div><div className="assessment-rows"><AssessmentRow label="FAULT CLASS" value={prediction ? faultLabel(prediction.fault) : '—'} highlight={Boolean(prediction?.fault_present)}/><AssessmentRow label="AFFECTED SUBSYSTEM" value={prediction?.subsystem && prediction.subsystem !== 'none' ? prediction.subsystem.toUpperCase() : prediction ? 'NONE' : '—'}/><AssessmentRow label="SEVERITY LEVEL" value={prediction ? prediction.severity === 0 ? '0 / 3 · NONE' : `${prediction.severity} / 3 · ${prediction.severity >= 3 ? 'HIGH' : 'MODERATE'}` : '—'} highlight={Boolean(prediction?.severity)}/><AssessmentRow label="MODEL MODE" value={prediction?.mode === 'streaming' ? 'TEMPORAL / STREAMING' : prediction ? 'INFERENCE' : '—'}/></div><div className="assessment-note"><Zap size={14}/><span>Assessment is the trained classifier's output. It is not a certified flight-safety decision.</span></div></div>

              <div className="panel valve-panel"><div className="panel-heading compact-heading"><div><div className="panel-kicker">COMPONENT TELEMETRY</div><h2>Valve state snapshot</h2></div><span className="instrument-count">7 VALVES</span></div><div className="valve-list">{[['vr01','Vent regulator'],['sv31','Solenoid valve'],['sv03','Solenoid valve'],['pv03','LOX propellant'],['vr06','Vent regulator'],['sv02','Solenoid valve'],['pv02','RP-1 propellant']].map(([key, description]) => { const value = currentRow?.[`${key}_state`]; const opened = String(value ?? '').toLowerCase() === 'open'; return <div className="valve-row" key={key}><div className={`valve-icon ${opened ? 'opened' : value ? 'closed' : ''}`}><Signal size={14}/></div><div className="valve-description"><strong>{key.toUpperCase()}</strong><span>{description}</span></div><span className={`valve-state ${opened ? 'open' : value ? 'closed' : 'unknown'}`}><span/>{value ? String(value).toUpperCase() : '—'}</span></div>; })}</div><div className="valve-foot"><span>Command/state values from recorded CSV</span><HardDrive size={13}/></div></div>
            </div>
          </section>

          <section className="panel event-panel"><div className="panel-heading compact-heading"><div><div className="panel-kicker">STREAM OBSERVABILITY</div><h2>Mission event log</h2></div><div className="event-panel-right"><span className="event-count">{logs.length} EVENTS</span><button className="clear-log" onClick={() => setLogs([])} disabled={!logs.length}>Clear log</button></div></div><div className="event-table-head"><span>TIME</span><span>TYPE</span><span>EVENT DESCRIPTION</span><span>STATUS</span></div><div className="event-list">{logs.length ? logs.map((item) => <div className="event-row" key={item.id}><span className="event-time mono">{item.time}</span><span><span className={`event-type ${item.kind}`}>{item.kind.toUpperCase()}</span></span><span className="event-message">{item.message}</span><span className={`event-status ${item.kind}`}>{item.kind === 'bad' ? 'ATTENTION' : item.kind === 'warn' ? 'NOTICE' : item.kind === 'good' ? 'RECORDED' : 'INFO'}</span></div>) : <div className="events-empty"><Terminal size={17}/><span>System events will appear here when the mission stream starts.</span></div>}</div><div className="event-foot"><span><span className="status-dot green"/> EVENT LOG ACTIVE</span><span>Showing most recent 30 events · local session only</span></div></section>

          <section className="bottom-strip"><div><div className="bottom-strip-icon"><Wifi size={16}/></div><div><strong>STREAM CONNECTION</strong><span>{apiState === 'online' ? 'HTTP inference · local proxy' : 'Awaiting backend connection'}</span></div></div><div><div className="bottom-strip-icon"><Cpu size={16}/></div><div><strong>INFERENCE ENGINE</strong><span>XGBoost · temporal feature calculator</span></div></div><div><div className="bottom-strip-icon"><Activity size={16}/></div><div><strong>DETECTION TRACKING</strong><span>{onset !== null ? `Ground-truth onset at ${fmt(onset, 1)} s` : 'Optional manifest not attached'}</span></div></div><div className="bottom-tag">ROCKETTWIN <span>·</span> ENGINEERING PROTOTYPE</div></section>
        </>}
        <footer className="page-footer"><span>ROCKETTWIN INTELLIGENT DIGITAL TWIN FRAMEWORK</span><span>SIMULATED TELEMETRY · NOT FOR FLIGHT OPERATIONS</span></footer>
      </div>
    </main>
  </div>;
}

function MetricCard({ label, value, note, icon, accent, status, compact = false }: { label: string; value: string; note: string; icon: ReactNode; accent: string; status?: string; compact?: boolean }) {
  return <div className={`metric-card accent-${accent}`}><div className="metric-top"><span>{label}</span><div className="metric-icon">{icon}</div></div><div className={`metric-value ${compact ? 'metric-compact' : ''} ${status === 'critical' ? 'text-red' : status === 'warning' ? 'text-amber' : ''}`}>{value}</div><div className="metric-note"><span className={`status-dot ${status === 'critical' ? 'red' : status === 'warning' ? 'amber' : accent === 'green' ? 'green' : 'blue'}`}/>{note}</div><div className="metric-bottom-line"/></div>;
}

function TelemetryChart({ title, unit, data, lines, onset }: { title: string; unit: string; data: ChartPoint[]; lines: { key: keyof ChartPoint; name: string; color: string }[]; onset: number | null }) {
  return <div className="chart-block"><div className="chart-block-heading"><span>{title}</span><span className="chart-unit">UNIT · {unit}</span></div><div className="chart-area"><ResponsiveContainer width="100%" height="100%"><LineChart data={data} margin={{ top: 8, right: 10, bottom: 0, left: -17 }}><CartesianGrid stroke="#243246" strokeDasharray="3 5" vertical={false}/><XAxis dataKey="time" type="number" domain={['dataMin', 'dataMax']} tickFormatter={(value: number) => `${Math.round(value)}s`} tick={{ fill: '#6f829a', fontSize: 10, fontFamily: 'DM Mono' }} axisLine={{ stroke: '#2a394d' }} tickLine={false} minTickGap={34}/><YAxis tick={{ fill: '#6f829a', fontSize: 10, fontFamily: 'DM Mono' }} axisLine={false} tickLine={false} width={47} domain={['auto', 'auto']}/><Tooltip contentStyle={{ background: '#101c2c', border: '1px solid #2d4058', borderRadius: 8, fontSize: 11, color: '#e6effb' }} labelStyle={{ color: '#93a7bf', fontFamily: 'DM Mono' }} labelFormatter={(value) => `T+${value}s`} formatter={(value, name) => [typeof value === 'number' ? value.toFixed(4) : value, name]}/><Legend iconType="circle" iconSize={6} wrapperStyle={{ fontSize: 10, color: '#91a3b9', paddingTop: 5 }}/>{onset !== null && data.some((point) => point.time >= onset) && <ReferenceLine x={onset} stroke="#f5b85c" strokeDasharray="4 4" label={{ value: 'FAULT ONSET', position: 'insideTopRight', fill: '#f5b85c', fontSize: 9 }} />}{lines.map((line) => <Line key={String(line.key)} type="monotone" dataKey={line.key} name={line.name} stroke={line.color} strokeWidth={1.9} dot={false} activeDot={{ r: 3, strokeWidth: 0 }} isAnimationActive={false} connectNulls/>)}</LineChart></ResponsiveContainer></div></div>;
}

function SensorCard({ name, description, value, unit, color }: { name: string; description: string; value: number | undefined; unit: string; color: string }) {
  return <div className={`sensor-card sensor-${color}`}><div className="sensor-card-top"><span className="sensor-name">{name}</span><span className={`sensor-indicator ${value !== undefined ? 'active' : ''}`}/></div><div className="sensor-value">{value === undefined ? '—' : fmt(value, 3)}<span>{unit}</span></div><div className="sensor-description">{description}</div><div className="sensor-mini-line"><i/><i/><i/><i/><i/><i/><i/><i/><i/><i/><i/><i/><i/><i/><i/></div></div>;
}

function AssessmentRow({ label, value, highlight = false }: { label: string; value: string; highlight?: boolean }) {
  return <div className="assessment-row"><span>{label}</span><strong className={highlight ? 'assessment-highlight' : ''}>{value}</strong></div>;
}
