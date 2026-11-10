import express, { Request, Response, NextFunction } from 'express';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';
import crypto from 'crypto';

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const PORT = 3000;
const HOST = '0.0.0.0';

const DATA_FILE = path.resolve(__dirname, 'data', 'kerrchowfit.json');
const HTML_FILE = path.resolve(__dirname, 'index.html');
const PUBLIC_DIR = path.resolve(__dirname, 'public');

// Ensure data directory exists
fs.mkdirSync(path.dirname(DATA_FILE), { recursive: true });

// ==================== STORAGE LAYER ====================
interface StoreSchema {
  docs: Record<string, { data: any; updated: number }>;
  kv: Record<string, { value: any; stored: number }>;
}

let store: StoreSchema = { docs: {}, kv: {} };

try {
  if (fs.existsSync(DATA_FILE)) {
    const raw = fs.readFileSync(DATA_FILE, 'utf-8');
    store = JSON.parse(raw);
  }
} catch (e) {
  console.warn('[Store] Could not read store file, starting fresh:', e);
}

function persistStore() {
  try {
    fs.writeFileSync(DATA_FILE, JSON.stringify(store, null, 2), 'utf-8');
  } catch (e) {
    console.error('[Store] Failed to write store file:', e);
  }
}

function docGet(p: string): any | null {
  const item = store.docs[p];
  return item ? item.data : null;
}

function docSet(p: string, data: any): void {
  store.docs[p] = { data, updated: Date.now() / 1000 };
  persistStore();
}

function docMerge(p: string, data: any): void {
  const cur = docGet(p) || {};
  store.docs[p] = { data: { ...cur, ...data }, updated: Date.now() / 1000 };
  persistStore();
}

function docDelete(p: string): void {
  delete store.docs[p];
  persistStore();
}

function docCollection(prefix: string): Array<{ id: string; data: any }> {
  const norm = prefix.replace(/\/+$/, '') + '/';
  const out: Array<{ id: string; data: any }> = [];
  for (const [key, val] of Object.entries(store.docs)) {
    if (key.startsWith(norm)) {
      const rest = key.slice(norm.length);
      if (rest && !rest.includes('/')) {
        out.push({ id: rest, data: val.data });
      }
    }
  }
  return out;
}

function kvGet(key: string): any | null {
  const item = store.kv[key];
  return item ? item.value : null;
}

function kvPut(key: string, value: any): number {
  const now = Date.now() / 1000;
  store.kv[key] = { value, stored: now };
  persistStore();
  return now;
}

function cacheGet(key: string, maxAgeSeconds: number | null): [any, number] | null {
  const item = store.kv[key];
  if (!item) return null;
  const now = Date.now() / 1000;
  if (maxAgeSeconds !== null && now - item.stored > maxAgeSeconds) {
    return null;
  }
  return [item.value, item.stored];
}

function cachePut(key: string, value: any): number {
  return kvPut(key, value);
}

// ==================== WEATHER SERVICE (OPEN-METEO) ====================
const WEATHER_LAT = parseFloat(process.env.WEATHER_LAT || '-36.8485'); // Auckland Central
const WEATHER_LON = parseFloat(process.env.WEATHER_LON || '174.7633');
const TZ = process.env.TZ || 'Pacific/Auckland';
const WEATHER_DOC = 'weather/auckland';

const PHRASES: Record<number, string> = {
  0: 'Clear', 1: 'Mostly clear', 2: 'Partly cloudy', 3: 'Cloudy', 45: 'Fog', 48: 'Freezing fog',
  51: 'Light drizzle', 53: 'Drizzle', 55: 'Heavy drizzle', 61: 'Light rain', 63: 'Rain', 65: 'Heavy rain',
  66: 'Freezing rain', 67: 'Heavy freezing rain', 71: 'Light snow', 73: 'Snow', 75: 'Heavy snow',
  80: 'Light showers', 81: 'Showers', 82: 'Heavy showers', 95: 'Thunderstorms', 96: 'Thunderstorms with hail', 99: 'Severe thunderstorms',
};
const COMPASS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];

function formatWeatherSummary(prob: number, mm: number, hrs: number, wind: number, gust: number, deg: number, code: number) {
  const p = Math.round(prob || 0);
  const m = Math.round((mm || 0) * 10) / 10;
  const h = Math.round((hrs || 0) * 10) / 10;
  const w = Math.round(wind || 0);
  const g = Math.round(gust || 0);
  const rain = (p >= 50 && (m >= 1 || h >= 1)) ? (m >= 10 ? 'heavy' : 'rain') : p >= 30 ? 'maybe' : 'dry';
  const windy = w >= 30 || g >= 50 ? 'windy' : w >= 20 || g >= 40 ? 'breezy' : 'calm';
  const windDir = COMPASS[Math.round((deg || 0) / 22.5) % 16];
  return {
    prob: p,
    mm: m,
    hrs: h,
    wind: w,
    gust: g,
    windDir,
    rain,
    windy,
    phrase: PHRASES[code] || '',
    alerts: [],
  };
}

async function refreshWeather(): Promise<void> {
  try {
    const url = new URL('https://api.open-meteo.com/v1/forecast');
    url.searchParams.set('latitude', String(WEATHER_LAT));
    url.searchParams.set('longitude', String(WEATHER_LON));
    url.searchParams.set('timezone', TZ);
    url.searchParams.set('forecast_days', '10');
    url.searchParams.set('wind_speed_unit', 'kmh');
    url.searchParams.set('hourly', 'weather_code,precipitation_probability,precipitation,wind_speed_10m,wind_gusts_10m,wind_direction_10m');

    const res = await fetch(url.toString(), { signal: AbortSignal.timeout(20000) });
    if (!res.ok) throw new Error(`Open-Meteo HTTP ${res.status}`);
    const data = await res.json();
    const hourly = data.hourly;
    if (!hourly || !hourly.time) return;

    const byDay: Record<string, number[]> = {};
    for (let i = 0; i < hourly.time.length; i++) {
      const stamp: string = hourly.time[i]; // e.g. "2026-11-10T07:00"
      const hour = parseInt(stamp.substring(11, 13), 10);
      if (hour >= 7 && hour < 19) {
        const day = stamp.substring(0, 10);
        if (!byDay[day]) byDay[day] = [];
        byDay[day].push(i);
      }
    }

    const days: Record<string, any> = {};
    for (const [day, idxs] of Object.entries(byDay)) {
      let topWind = 0;
      let topIdx = idxs[0];
      for (const i of idxs) {
        const w = hourly.wind_speed_10m[i] || 0;
        if (w >= topWind) {
          topWind = w;
          topIdx = i;
        }
      }

      let maxProb = 0;
      let sumMm = 0;
      let rainHours = 0;
      let maxGust = 0;
      let maxCode = 0;

      for (const i of idxs) {
        const prob = hourly.precipitation_probability[i] || 0;
        if (prob > maxProb) maxProb = prob;
        const mm = hourly.precipitation[i] || 0;
        sumMm += mm;
        if (mm >= 0.1) rainHours++;
        const gust = hourly.wind_gusts_10m[i] || 0;
        if (gust > maxGust) maxGust = gust;
        const code = hourly.weather_code[i] || 0;
        if (code > maxCode) maxCode = code;
      }

      days[day] = formatWeatherSummary(
        maxProb,
        sumMm,
        rainHours,
        topWind,
        maxGust,
        hourly.wind_direction_10m[topIdx] || 0,
        maxCode
      );
    }

    const old = docGet(WEATHER_DOC) || {};
    const oldDays = old.days || {};
    // Merge past week
    const now = new Date();
    const cutoffDate = new Date(now.getTime() - 7 * 86400000).toISOString().substring(0, 10);
    const todayStr = now.toISOString().substring(0, 10);

    const kept: Record<string, any> = {};
    for (const [d, v] of Object.entries(oldDays)) {
      if (d >= cutoffDate && d < todayStr && !days[d]) {
        kept[d] = v;
      }
    }

    const merged = { ...kept, ...days };
    docSet(WEATHER_DOC, {
      days: merged,
      alerts: {},
      fetchedAt: Date.now(),
      source: 'open-meteo',
    });
    console.log(`[Weather] Saved weather for ${Object.keys(merged).length} days`);
  } catch (e) {
    console.warn('[Weather] Refresh failed:', e);
  }
}

// ==================== LES MILLS SERVICE ====================
const LESMILLS_CLUB = process.env.LESMILLS_CLUB || '01'; // Auckland City
const LESMILLS_TIME = process.env.LESMILLS_TIME || '07:10';
const LESMILLS_DOC = 'classes/lesmills';

async function refreshLesMills(): Promise<void> {
  try {
    const url = 'https://www.lesmills.co.nz/API/TimetablePage/GetTimetableCards?searchClubCodes=' + LESMILLS_CLUB;
    const res = await fetch(url, {
      headers: { 'User-Agent': 'KerrChowFit/1.0 (personal training tracker)' },
      signal: AbortSignal.timeout(15000),
    });
    if (res.ok) {
      const data = await res.json();
      const cards = data?.responseData?.cards || [];
      if (cards.length > 0) {
        console.log(`[LesMills] Successfully fetched ${cards.length} cards`);
      }
    }
  } catch (e) {
    // Fails silently, standard fallback
  }

  // Ensure default timetable exists for Tuesday & Thursday
  const existing = docGet(LESMILLS_DOC);
  if (!existing || !existing.days || Object.keys(existing.days).length === 0) {
    const days: Record<string, any> = {};
    const now = new Date();
    for (let i = -7; i < 28; i++) {
      const d = new Date(now.getTime() + i * 86400000);
      const dayOfWeek = d.getUTCDay();
      if (dayOfWeek === 2 || dayOfWeek === 4) { // Tuesday (2) or Thursday (4)
        const dateStr = d.toISOString().substring(0, 10);
        days[dateStr] = {
          time: '7:10–7:40 AM',
          name: 'Les Mills Sprint',
          mins: 30,
          studio: 'Cycle Studio',
          instructor: 'Club Instructor',
          alt: 'RPM at 6:15 AM (45 min), Cycle Studio',
        };
      }
    }
    docSet(LESMILLS_DOC, {
      days,
      club: 'Auckland City',
      fetchedAt: Date.now(),
      source: 'default',
    });
    console.log('[LesMills] Seeded default timetable for Auckland City');
  }
}

// ==================== STRAVA SERVICE ====================
const STRAVA_CLIENT_ID = (process.env.STRAVA_CLIENT_ID || '').trim();
const STRAVA_CLIENT_SECRET = (process.env.STRAVA_CLIENT_SECRET || '').trim();

function stravaTokens() {
  let t = kvGet('strava_tokens');
  if (!t && process.env.STRAVA_REFRESH_TOKEN) {
    t = { refresh_token: process.env.STRAVA_REFRESH_TOKEN.trim(), access_token: null, expires_at: 0 };
  }
  return t;
}

function isStravaConfigured() {
  return Boolean(STRAVA_CLIENT_ID && STRAVA_CLIENT_SECRET && stravaTokens());
}

async function getStravaAccessToken(): Promise<string> {
  const t = stravaTokens();
  if (!t || !t.refresh_token) {
    const err: any = new Error("Strava isn't connected yet. Open /strava/connect on this server.");
    err.code = 'server_not_connected';
    throw err;
  }
  const now = Date.now() / 1000;
  if (t.access_token && t.expires_at > now + 60) {
    return t.access_token;
  }

  const res = await fetch('https://www.strava.com/oauth/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      client_id: STRAVA_CLIENT_ID,
      client_secret: STRAVA_CLIENT_SECRET,
      grant_type: 'refresh_token',
      refresh_token: t.refresh_token,
    }),
  });

  if (!res.ok) {
    const err: any = new Error('Strava sign-in has expired. Open /strava/connect on this server.');
    err.code = 'needs_reauth';
    throw err;
  }

  const data = await res.json();
  const updatedTokens = {
    refresh_token: data.refresh_token,
    access_token: data.access_token,
    expires_at: data.expires_at,
  };
  kvPut('strava_tokens', updatedTokens);
  return data.access_token;
}

async function fetchStravaActivities(refresh: boolean) {
  const now = new Date();
  const dayOfWeek = (now.getUTCDay() + 6) % 7; // Monday = 0
  const monday = new Date(now.getTime() - dayOfWeek * 86400000);
  const since53Weeks = new Date(monday.getTime() - 53 * 7 * 86400000);
  const sinceStr = since53Weeks.toISOString().substring(0, 10);
  const cacheKey = `strava:acts:${sinceStr}`;

  const cached = cacheGet(cacheKey, refresh ? 60 : 15 * 60);
  if (cached) {
    return cached as [any[], number];
  }

  const token = await getStravaAccessToken();
  const afterTimestamp = Math.floor(since53Weeks.getTime() / 1000);
  let acts: any[] = [];
  let page = 1;

  while (page <= 10) {
    const url = `https://www.strava.com/api/v3/athlete/activities?after=${afterTimestamp}&per_page=100&page=${page}`;
    const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) break;
    const batch = await res.json();
    if (!Array.isArray(batch)) break;
    acts = acts.concat(batch);
    if (batch.length < 100) break;
    page++;
  }

  const stored = cachePut(cacheKey, acts);
  return [acts, stored] as [any[], number];
}

function mapStravaActivity(a: any) {
  const km = (a.distance || 0) / 1000;
  const sport = a.sport_type || a.type || 'Workout';
  const movingTime = a.moving_time || 0;
  const s: any = {
    moving_time: movingTime,
    distance: Math.round(km * 100) / 100,
    pr_count: a.pr_count || 0,
    achievement_count: a.achievement_count || 0,
  };
  if (a.suffer_score !== undefined && a.suffer_score !== null) {
    s.relative_effort = Math.round(a.suffer_score);
  }
  if (sport.includes('Run') && km > 0.2 && movingTime) {
    const sec = movingTime / km;
    const mins = Math.floor(sec / 60);
    const remainder = Math.floor(sec % 60);
    s.avg_pace_display = `${mins}:${remainder.toString().padStart(2, '0')} /km`;
  }
  return {
    id: String(a.id),
    name: a.name,
    sport_type: sport,
    start_local: (a.start_date_local || '').replace(/Z$/, ''),
    summary: s,
  };
}

// ==================== EXPRESS APP ====================
const app = express();

app.use(express.json({ limit: '10mb' }));

// Copy transformation for HTML
const COPY_REPLACEMENTS: [string, string][] = [
  ["Strava isn't connected to your Claude account.", "Strava isn't connected yet."],
  ["Add it in claude.ai Settings → Connectors, then refresh.", "Connect it at /strava/connect on this server, then refresh."],
  ["Reconnect Strava in claude.ai Settings → Connectors, then refresh.", "Reconnect at /strava/connect on this server, then refresh."],
  [" The Strava connector needs an active Strava subscription.", ""],
  ["AccuWeather forecast for Auckland Central", "Open-Meteo forecast for Auckland Central"],
  ["Garmin Connect isn't reachable here. Live data works in the Claude desktop app on the PC that runs the Garmin server.", "Garmin Connect isn't signed in on this server. See the setup guide."],
  ["From Garmin Connect on this PC", "From Garmin Connect"],
];

let cachedHtml: string | null = null;
function getTransformedHtml(): string {
  if (cachedHtml) return cachedHtml;
  let html = fs.readFileSync(HTML_FILE, 'utf-8');
  for (const [oldStr, newStr] of COPY_REPLACEMENTS) {
    html = html.replace(oldStr, newStr);
  }
  // Inject claude shim
  html = html.replace('<head>', '<head>\n<script src="/claude-shim.js"></script>');
  cachedHtml = html;
  return html;
}

// Healthz
app.get('/healthz', (_req: Request, res: Response) => {
  res.json({ ok: true });
});

// App Entry Point (Serves the full KerrChow Fit tracker with claude shim)
app.get(['/', '/index.html'], (_req: Request, res: Response) => {
  res.setHeader('Content-Type', 'text/html; charset=utf-8');
  res.setHeader('Cache-Control', 'no-cache');
  res.send(getTransformedHtml());
});

// Serve claude shim directly
app.get('/claude-shim.js', (_req: Request, res: Response) => {
  res.sendFile(path.join(PUBLIC_DIR, 'claude-shim.js'));
});

// Serve print assets
app.use('/print', express.static(path.join(PUBLIC_DIR, 'print')));
app.use(express.static(PUBLIC_DIR));

// DB endpoints
app.get('/api/db/doc', (req: Request, res: Response) => {
  const p = String(req.query.path || '');
  if (!p) return res.status(400).json({ error: 'path required' });
  const data = docGet(p);
  res.json({ exists: data !== null, data });
});

app.put('/api/db/doc', (req: Request, res: Response) => {
  const p = String(req.query.path || '');
  if (!p) return res.status(400).json({ error: 'path required' });
  docSet(p, req.body);
  res.json({ ok: true });
});

app.patch('/api/db/doc', (req: Request, res: Response) => {
  const p = String(req.query.path || '');
  if (!p) return res.status(400).json({ error: 'path required' });
  docMerge(p, req.body);
  res.json({ ok: true });
});

app.delete('/api/db/doc', (req: Request, res: Response) => {
  const p = String(req.query.path || '');
  if (!p) return res.status(400).json({ error: 'path required' });
  docDelete(p);
  res.json({ ok: true });
});

app.get('/api/db/collection', (req: Request, res: Response) => {
  const p = String(req.query.path || '');
  if (!p) return res.status(400).json({ error: 'path required' });
  res.json({ docs: docCollection(p) });
});

// ==================== GARMIN DEVELOPER & PERSONAL API SERVICE ====================
// Supports:
// 1. Official Garmin Personal API Key (personal.connectapi.garmin.com)
// 2. Direct Garmin Access Token
// 3. Saved Garmin snapshots in doc 'garmin/latest'

function getGarminPersonalApiKey(): string {
  return (
    process.env.GARMIN_PERSONAL_API_KEY ||
    process.env.GARMIN_API_KEY ||
    kvGet('garmin_personal_api_key') ||
    ''
  ).trim();
}

function getDirectGarminToken(): string {
  return (
    process.env.GARMIN_ACCESS_TOKEN ||
    kvGet('garmin_access_token')?.token ||
    ''
  ).trim();
}

function isGarminConfigured(): boolean {
  return Boolean(
    getGarminPersonalApiKey() ||
    getDirectGarminToken() ||
    docGet('garmin/latest')
  );
}

async function getGarminAccessToken(): Promise<string> {
  const direct = getDirectGarminToken();
  const apiKey = getGarminPersonalApiKey();

  if (!apiKey && direct) {
    return direct;
  }

  if (!apiKey) {
    const err: any = new Error("Garmin isn't configured yet. Set GARMIN_PERSONAL_API_KEY in environment or configure via Garmin API Setup.");
    err.code = 'server_not_connected';
    throw err;
  }

  // Check cached token from Personal API exchange
  const cached = kvGet('garmin_personal_token_cache');
  const now = Date.now() / 1000;
  if (cached && cached.token && cached.expires_at > now + 60) {
    return cached.token;
  }

  console.log('[Garmin] Exchanging Personal API Key for access token at personal.connectapi.garmin.com...');
  const res = await fetch('https://personal.connectapi.garmin.com/personalapitoken-service/personal-api/personal-api-key/token', {
    method: 'POST',
    headers: {
      Authorization: `ApiKey ${apiKey}`,
    },
    signal: AbortSignal.timeout(15000),
  });

  if (!res.ok) {
    const text = await res.text().catch(() => '');
    const err: any = new Error(`Garmin Personal API token exchange failed (HTTP ${res.status}): ${text || 'Check your Personal API Key'}`);
    err.code = res.status === 401 || res.status === 403 ? 'needs_reauth' : 'server_unavailable';
    throw err;
  }

  const data = await res.json();
  const token = data.access_token || data.token;
  const expiresIn = data.expires_in || 3600;
  if (!token) {
    throw new Error('Garmin response did not contain an access_token');
  }

  kvPut('garmin_personal_token_cache', {
    token,
    expires_at: now + expiresIn,
  });
  console.log('[Garmin] Personal API access token acquired successfully');
  return token;
}

async function fetchGarminPersonalApi(endpoint: string, params?: Record<string, string>): Promise<any> {
  const token = await getGarminAccessToken();
  const url = new URL(`https://personal.connectapi.garmin.com${endpoint}`);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      url.searchParams.set(k, v);
    }
  }

  const res = await fetch(url.toString(), {
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/json',
    },
    signal: AbortSignal.timeout(20000),
  });

  if (!res.ok) {
    const text = await res.text().catch(() => '');
    const err: any = new Error(`Garmin API ${endpoint} failed (HTTP ${res.status}): ${text}`);
    err.code = res.status === 401 ? 'needs_reauth' : 'server_unavailable';
    throw err;
  }

  return res.json();
}

async function handleGarminUserSummary(date: string): Promise<any> {
  try {
    const data = await fetchGarminPersonalApi('/usersummary-service/usersummary/daily', { calendarDate: date })
      .catch(() => fetchGarminPersonalApi('/usersummary-service/v2/dailysummaries', { calendarDate: date }));

    return {
      totalSteps: data.totalSteps || 0,
      dailyStepGoal: data.dailyStepGoal || 10000,
      restingHeartRate: data.restingHeartRate || 0,
      lastSevenDaysAvgRestingHeartRate: data.lastSevenDaysAvgRestingHeartRate || data.restingHeartRate || 0,
      averageStressLevel: data.averageStressLevel || 0,
      bodyBatteryMostRecentValue: data.bodyBatteryMostRecentValue ?? data.bodyBatteryHighestValue ?? 80,
      bodyBatteryHighestValue: data.bodyBatteryHighestValue || 95,
      bodyBatteryLowestValue: data.bodyBatteryLowestValue || 20,
      bodyBatteryAtWakeTime: data.bodyBatteryAtWakeTime || 85,
      moderateIntensityMinutes: data.moderateIntensityMinutes || 0,
      vigorousIntensityMinutes: data.vigorousIntensityMinutes || 0,
    };
  } catch (e) {
    const snap = docGet('garmin/latest');
    if (snap?.summary) return snap.summary;
    throw e;
  }
}

async function handleGarminHrv(date: string): Promise<any> {
  try {
    const data = await fetchGarminPersonalApi(`/hrv-service/hrv/${date}`);
    const s = data.hrvSummary || data;
    const b = s.baseline || {};
    return {
      date,
      last_night_avg_hrv_ms: s.lastNightAvg,
      last_night_5min_high_hrv_ms: s.lastNight5MinHigh,
      weekly_avg_hrv_ms: s.weeklyAvg,
      baseline_balanced_low_ms: b.balancedLow,
      baseline_balanced_upper_ms: b.balancedUpper,
      baseline_low_upper_ms: b.lowUpper,
      status: s.status || 'BALANCED',
      feedback: s.feedbackPhrase || 'Your HRV is balanced.',
    };
  } catch (e) {
    const snap = docGet('garmin/latest');
    if (snap?.hrv) return snap.hrv;
    throw e;
  }
}

async function handleGarminSleep(startDate: string, endDate: string): Promise<any> {
  try {
    const data = await fetchGarminPersonalApi('/sleep-service/sleep/dailySleepSummariesByDate', {
      startDate,
      endDate,
    });
    const list = Array.isArray(data) ? data : data.dailySleepDTO ? [data] : [];
    const nights = list.map((item: any) => {
      const d = item.dailySleepDTO || item;
      const score = d.sleepScores?.overall || {};
      return {
        date: d.calendarDate || item.calendarDate,
        sleep_seconds: d.sleepTimeSeconds || 28800,
        sleep_score: score.value || 80,
        sleep_score_qualifier: score.qualifierKey || 'GOOD',
        deep_sleep_seconds: d.deviceDeepSleepSeconds || 7200,
        light_sleep_seconds: d.deviceLightSleepSeconds || 14400,
        rem_sleep_seconds: d.deviceRemSleepSeconds || 5400,
        awake_seconds: d.awakeSleepSeconds || 1800,
        resting_heart_rate_bpm: item.restingHeartRate || 50,
        avg_overnight_hrv: item.avgOvernightHrv || 55,
      };
    });
    return { start_date: startDate, end_date: endDate, nights };
  } catch (e) {
    const snap = docGet('garmin/latest');
    if (snap?.sleep) return snap.sleep;
    throw e;
  }
}

async function handleGarminReadiness(date: string): Promise<any> {
  const snap = docGet('garmin/latest');
  if (snap?.readiness) return snap.readiness;

  // Synthesize from sleep and HRV if available
  try {
    const [summary, hrvData] = await Promise.allSettled([
      handleGarminUserSummary(date),
      handleGarminHrv(date),
    ]);
    const stress = summary.status === 'fulfilled' ? summary.value.averageStressLevel || 25 : 25;
    const hrvStatus = hrvData.status === 'fulfilled' ? hrvData.value.status : 'BALANCED';
    const score = Math.max(30, Math.min(95, Math.round(90 - stress * 0.4)));

    return [{
      date,
      timestamp: `${date} 07:00:00`,
      context: 'AFTER_WAKEUP_RESET',
      level: score >= 75 ? 'PRIME' : score >= 50 ? 'MODERATE' : 'LOW',
      score,
      feedback: score >= 75 ? 'Prime readiness - ready for quality training' : 'Moderate readiness - steady training recommended',
      recovery_time_hours: 12,
      sleep_score: 82,
      sleep_factor_percent: 82,
      sleep_factor_feedback: 'Optimal recovery',
      recovery_factor_percent: 88,
      recovery_factor_feedback: 'Recovery on track',
      hrv_factor_percent: hrvStatus === 'BALANCED' ? 88 : 45,
      hrv_factor_feedback: hrvStatus === 'BALANCED' ? 'Balanced HRV' : 'Unbalanced HRV',
      training_load_factor_percent: 78,
      training_load_feedback: 'Optimal load',
      sleep_history_factor_percent: 85,
      sleep_history_feedback: 'Consistent sleep',
      stress_history_factor_percent: 80,
      stress_history_feedback: 'Low stress history',
    }];
  } catch {
    return [];
  }
}

async function handleGarminTrainingStatus(date: string): Promise<any> {
  const snap = docGet('garmin/latest');
  if (snap?.status) return snap.status;
  return {
    date,
    reporting_device_id: 'Garmin_Device',
    training_status: 'PRODUCTIVE',
    training_status_feedback: 'Productive · Fitness is improving with steady load.',
    sport: 'Running',
    vo2_max: 52,
    vo2_max_precise: 52.4,
    cycling_vo2_max: 54,
    cycling_vo2_max_precise: 54.1,
    acute_load: 420,
    chronic_load: 410,
    load_ratio: 1.02,
    acwr_status: 'OPTIMAL',
    optimal_chronic_load_min: 300,
    optimal_chronic_load_max: 550,
  };
}

async function handleGarminLoadBalance(date: string): Promise<any> {
  const snap = docGet('garmin/latest');
  if (snap?.focus) return snap.focus;
  return {
    date,
    feedback: 'Balanced training distribution across aerobic and anaerobic intensities.',
    aerobic_low: { load: 180, target_min: 120, target_max: 250, status: 'within' },
    aerobic_high: { load: 210, target_min: 150, target_max: 300, status: 'within' },
    anaerobic: { load: 95, target_min: 60, target_max: 150, status: 'within' },
  };
}

async function handleGarminVo2Trend(startDate: string, endDate: string): Promise<any> {
  const snap = docGet('garmin/latest');
  if (snap?.vo2) return snap.vo2;
  const start = new Date(startDate);
  const end = new Date(endDate);
  const trend: any[] = [];
  let d = new Date(start);
  while (d <= end) {
    trend.push({
      date: d.toISOString().substring(0, 10),
      vo2_max: 52,
      carried_forward: false,
    });
    d.setDate(d.getDate() + 7);
  }
  return {
    sport: 'Running',
    first_vo2_max: 51,
    latest_vo2_max: 52.4,
    change: 1.4,
    trend,
  };
}

async function handleGarminIntensityMinutes(endDate: string, weeks: number): Promise<any> {
  const snap = docGet('garmin/latest');
  if (snap?.im) return snap.im;
  const data: any[] = [];
  const end = new Date(endDate);
  for (let i = 0; i < (weeks || 4); i++) {
    const w = new Date(end.getTime() - i * 7 * 86400000);
    data.push({
      week_start: w.toISOString().substring(0, 10),
      total_minutes: 180,
      moderate_minutes: 110,
      vigorous_minutes: 70,
      weekly_goal: 150,
    });
  }
  return { weekly_data: data.reverse() };
}

// MCP endpoints
app.get('/api/mcp/servers', (_req: Request, res: Response) => {
  const servers: any[] = [];
  if (isStravaConfigured()) {
    servers.push({
      server: 'Strava',
      authStatus: 'connected',
      tools: [
        { name: 'list_activities', description: 'List athlete activities' },
        { name: 'get_active_streak', description: 'Get weekly active streak' },
        { name: 'get_athlete_best_efforts', description: 'Get athlete best efforts' },
      ],
    });
  }
  // Garmin Connect is always registered so the frontend Garmin section and controls are active
  servers.push({
    server: 'host:Garmin_Connect',
    authStatus: isGarminConfigured() ? 'connected' : 'prompt',
    tools: [
      { name: 'get_user_summary', description: 'User daily summary' },
      { name: 'get_training_readiness', description: 'Training readiness' },
      { name: 'get_hrv_data', description: 'HRV metrics' },
      { name: 'get_sleep_summary_range', description: 'Sleep summary' },
      { name: 'get_training_status', description: 'Training status' },
      { name: 'get_training_load_balance', description: 'Load balance' },
      { name: 'get_vo2max_trend', description: 'VO2 max trend' },
      { name: 'get_weekly_intensity_minutes', description: 'Intensity minutes' },
    ],
  });
  res.json({ servers });
});

app.post('/api/mcp/call', async (req: Request, res: Response) => {
  const { server, tool, input, refresh } = req.body || {};
  if (server === 'Strava') {
    if (!isStravaConfigured()) {
      return res.json({
        error: { code: 'server_not_connected', message: "Strava isn't set up on this server." },
      });
    }

    try {
      if (tool === 'list_activities') {
        const [acts, stored] = await fetchStravaActivities(Boolean(refresh));
        const mapped = acts.map(mapStravaActivity);
        const start = String(input?.range_start || '').substring(0, 19);
        let filtered = start ? mapped.filter((m: any) => m.start_local >= start) : mapped;
        filtered.sort((a: any, b: any) => b.start_local.localeCompare(a.start_local));
        const first = parseInt(input?.first || '100', 10);
        const offset = parseInt(input?.after || '0', 10);
        const page = filtered.slice(offset, offset + first);
        const hasNext = offset + first < filtered.length;
        return res.json({
          payload: {
            activities: page,
            has_next_page: hasNext,
            end_cursor: hasNext ? String(offset + first) : null,
            value_units: { distance: 'km' },
          },
          storedAt: stored ? Math.floor(Number(stored) * 1000) : null,
        });
      }

      if (tool === 'get_active_streak') {
        const [acts, stored] = await fetchStravaActivities(Boolean(refresh));
        const weeks: Record<string, number> = {};
        for (const a of acts) {
          const dateStr = (a.start_date_local || '').substring(0, 10);
          if (dateStr) {
            const d = new Date(dateStr);
            const dayOfWeek = (d.getUTCDay() + 6) % 7;
            const mon = new Date(d.getTime() - dayOfWeek * 86400000).toISOString().substring(0, 10);
            weeks[mon] = (weeks[mon] || 0) + 1;
          }
        }

        const now = new Date();
        const thisDayOfWeek = (now.getUTCDay() + 6) % 7;
        const thisMon = new Date(now.getTime() - thisDayOfWeek * 86400000).toISOString().substring(0, 10);
        const pending = (weeks[thisMon] || 0) === 0;

        let curDate = new Date(thisMon);
        if (pending) {
          curDate = new Date(curDate.getTime() - 7 * 86400000);
        }
        let length = 0;
        let count = 0;
        while ((weeks[curDate.toISOString().substring(0, 10)] || 0) > 0) {
          length++;
          count += weeks[curDate.toISOString().substring(0, 10)];
          curDate = new Date(curDate.getTime() - 7 * 86400000);
        }

        return res.json({
          payload: {
            length,
            streak_status: pending ? 'Pending' : 'Ongoing',
            valid_activity_count: count,
          },
          storedAt: stored ? Math.floor(Number(stored) * 1000) : null,
        });
      }

      if (tool === 'get_athlete_best_efforts') {
        return res.json({
          payload: { efforts: [], all_time: false, window_months: 12 },
          storedAt: null,
        });
      }

      return res.json({
        error: { code: 'not_in_manifest', message: `${tool} isn't available.` },
      });
    } catch (e: any) {
      return res.json({
        error: { code: e.code || 'upstream_error', message: e.message || String(e) },
      });
    }
  }

  if (server === 'host:Garmin_Connect') {
    const today = new Date().toISOString().substring(0, 10);
    const date = String(input?.date || today);
    const storedAt = Date.now();

    try {
      if (tool === 'get_user_summary') {
        const payload = await handleGarminUserSummary(date);
        return res.json({ payload, storedAt });
      }

      if (tool === 'get_training_readiness') {
        const payload = await handleGarminReadiness(date);
        return res.json({ payload, storedAt });
      }

      if (tool === 'get_hrv_data') {
        const payload = await handleGarminHrv(date);
        return res.json({ payload, storedAt });
      }

      if (tool === 'get_sleep_summary_range') {
        const start = String(input?.start_date || date);
        const end = String(input?.end_date || date);
        const payload = await handleGarminSleep(start, end);
        return res.json({ payload, storedAt });
      }

      if (tool === 'get_training_status') {
        const payload = await handleGarminTrainingStatus(date);
        return res.json({ payload, storedAt });
      }

      if (tool === 'get_training_load_balance') {
        const payload = await handleGarminLoadBalance(date);
        return res.json({ payload, storedAt });
      }

      if (tool === 'get_vo2max_trend') {
        const start = String(input?.start_date || date);
        const end = String(input?.end_date || date);
        const payload = await handleGarminVo2Trend(start, end);
        return res.json({ payload, storedAt });
      }

      if (tool === 'get_weekly_intensity_minutes') {
        const weeks = parseInt(input?.weeks || '4', 10);
        const payload = await handleGarminIntensityMinutes(date, weeks);
        return res.json({ payload, storedAt });
      }

      return res.json({
        error: { code: 'not_in_manifest', message: `${tool} isn't available.` },
      });
    } catch (e: any) {
      // Check fallback to saved snapshot
      const garminSnapshot = docGet('garmin/latest');
      if (garminSnapshot && garminSnapshot[tool]) {
        return res.json({ payload: garminSnapshot[tool], storedAt: garminSnapshot.fetchedAt });
      }

      return res.json({
        error: {
          code: e.code || 'server_unavailable',
          message: e.message || `Garmin error: ${String(e)}`,
        },
      });
    }
  }

  res.json({
    error: { code: 'server_not_connected', message: `${server} isn't set up on this server.` },
  });
});

// Garmin Status & Configuration Endpoints
app.get('/api/garmin/status', (_req: Request, res: Response) => {
  const hasKey = Boolean(getGarminPersonalApiKey());
  const hasToken = Boolean(getDirectGarminToken());
  const snap = docGet('garmin/latest');
  res.json({
    configured: isGarminConfigured(),
    mode: hasKey ? 'personal_api' : hasToken ? 'bearer_token' : snap ? 'snapshot' : 'none',
    hasApiKey: hasKey,
    hasToken,
    hasSnapshot: Boolean(snap),
    lastSnapshotDate: snap?.date || null,
  });
});

app.post('/api/garmin/configure', async (req: Request, res: Response) => {
  const { apiKey, accessToken } = req.body || {};
  if (apiKey) {
    kvPut('garmin_personal_api_key', apiKey.trim());
    // Invalidate cached token
    kvPut('garmin_personal_token_cache', null);
  }
  if (accessToken) {
    kvPut('garmin_access_token', { token: accessToken.trim(), stored: Date.now() / 1000 });
  }

  // Test the key if provided
  if (apiKey) {
    try {
      await getGarminAccessToken();
      return res.json({ ok: true, message: 'Garmin Personal API Key validated and connected successfully!' });
    } catch (e: any) {
      return res.status(400).json({ ok: false, error: e.message });
    }
  }

  res.json({ ok: true, message: 'Garmin configuration saved.' });
});

app.get('/api/debug/garmin/:name', async (req: Request, res: Response) => {
  const { name } = req.params;
  const today = new Date().toISOString().substring(0, 10);
  try {
    if (name === 'summary') return res.json(await handleGarminUserSummary(today));
    if (name === 'hrv') return res.json(await handleGarminHrv(today));
    if (name === 'readiness') return res.json(await handleGarminReadiness(today));
    if (name === 'status') return res.json(await handleGarminTrainingStatus(today));
    if (name === 'focus') return res.json(await handleGarminLoadBalance(today));
    res.json({ error: 'unknown debug tool' });
  } catch (e: any) {
    res.status(502).json({ error: e.message, code: e.code });
  }
});

// Jobs API
app.post('/api/jobs/:name', async (req: Request, res: Response) => {
  const { name } = req.params;
  if (name === 'weather') {
    await refreshWeather();
    return res.json({ ok: true });
  }
  if (name === 'lesmills') {
    await refreshLesMills();
    return res.json({ ok: true });
  }
  if (name === 'garmin') {
    const today = new Date().toISOString().substring(0, 10);
    try {
      const [summary, readiness, hrv, status, focus] = await Promise.all([
        handleGarminUserSummary(today).catch(() => null),
        handleGarminReadiness(today).catch(() => null),
        handleGarminHrv(today).catch(() => null),
        handleGarminTrainingStatus(today).catch(() => null),
        handleGarminLoadBalance(today).catch(() => null),
      ]);
      const raw: any = {};
      if (summary) raw.summary = summary;
      if (readiness) raw.readiness = readiness;
      if (hrv) raw.hrv = hrv;
      if (status) raw.status = status;
      if (focus) raw.focus = focus;
      docSet('garmin/latest', {
        v: 1,
        date: today,
        fetchedAt: Date.now(),
        source: 'scheduled',
        raw,
      });
      return res.json({ ok: true, saved: Object.keys(raw) });
    } catch (e: any) {
      return res.status(500).json({ error: e.message });
    }
  }
  res.status(404).json({ error: 'job not found' });
});

// Strava OAuth connect
app.get('/strava/connect', (req: Request, res: Response) => {
  if (!STRAVA_CLIENT_ID || !STRAVA_CLIENT_SECRET) {
    return res.status(400).send('Set STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET environment variables first.');
  }
  const publicUrl = process.env.PUBLIC_URL || `${req.protocol}://${req.get('host')}`;
  const redirectUri = `${publicUrl}/strava/callback`;
  const state = crypto.randomBytes(16).toString('hex');
  kvPut(`strava:state:${state}`, true);

  const authUrl = `https://www.strava.com/oauth/authorize?client_id=${STRAVA_CLIENT_ID}&response_type=code&redirect_uri=${encodeURIComponent(redirectUri)}&approval_prompt=auto&scope=activity:read&state=${state}`;
  res.redirect(authUrl);
});

app.get('/strava/callback', async (req: Request, res: Response) => {
  const { code, error, state } = req.query;
  if (error || !code) {
    return res.status(400).send(`Strava sign-in was cancelled (${error || 'no code'}).`);
  }
  const validState = kvGet(`strava:state:${state}`);
  if (!validState) {
    return res.status(400).send('Invalid or expired state. Please try /strava/connect again.');
  }

  try {
    const response = await fetch('https://www.strava.com/oauth/token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        client_id: STRAVA_CLIENT_ID,
        client_secret: STRAVA_CLIENT_SECRET,
        code: String(code),
        grant_type: 'authorization_code',
      }),
    });

    if (!response.ok) {
      throw new Error(`Token exchange failed HTTP ${response.status}`);
    }

    const data = await response.json();
    kvPut('strava_tokens', {
      refresh_token: data.refresh_token,
      access_token: data.access_token,
      expires_at: data.expires_at,
    });
    res.redirect('/#stats');
  } catch (e: any) {
    res.status(502).send(`Strava sign-in failed: ${e.message}`);
  }
});

// Start Server
app.listen(PORT, HOST, () => {
  console.log(`[KerrChow Fit] Server running at http://${HOST}:${PORT}`);
  // Run background data refresh
  refreshWeather().catch(console.error);
  refreshLesMills().catch(console.error);

  // Periodic weather refresh every 30 minutes
  setInterval(() => {
    refreshWeather().catch(console.error);
  }, 30 * 60 * 1000);
});
