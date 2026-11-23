import http from 'k6/http';
import { check } from 'k6';
import { Rate } from 'k6/metrics';
import exec from 'k6/execution';

function integer(name, minimum, maximum) {
  const raw = __ENV[name];
  if (!raw || !/^\d+$/.test(raw)) throw new Error(`${name} must be explicitly provided`);
  const n = Number(raw);
  if (n < minimum || n > maximum) throw new Error(`${name} out of bounds`);
  return n;
}
const rate = integer('RATE', 1, 1000);
const work = integer('WORK_ITERATIONS', 1, 2000000);
const preVUs = integer('PRE_VUS', 1, 64);
const maxVUs = integer('MAX_VUS', preVUs, 128);
const duration = __ENV.DURATION || '240s';
const warmup = Number(__ENV.WARMUP_SECONDS || '0');
if (!Number.isInteger(warmup) || warmup < 0 || warmup > 120) throw new Error('invalid warmup');
if (!/^[1-9]\d*s$/.test(duration) || Number(duration.slice(0, -1)) > 480) {
  throw new Error('DURATION must be 1..480 seconds');
}
const base = __ENV.BASE_URL;
const endpoint = __ENV.ENDPOINT || 'cpu';
if (!['cpu', 'info'].includes(endpoint)) throw new Error('ENDPOINT must be cpu or info');
if (!base || !/^http:\/\/(api\.aegis-step08\.svc\.cluster\.local|127\.0\.0\.1)(:\d+)?$/.test(base)) {
  throw new Error('BASE_URL must name the experiment ClusterIP DNS or loopback');
}
const apiErrors = new Rate('api_errors');
export const options = {
  scenarios: { cpu: { executor: 'constant-arrival-rate', rate, timeUnit: '1s',
    duration: String(Number(duration.slice(0, -1)) + warmup) + 's',
    preAllocatedVUs: preVUs, maxVUs } },
  summaryTrendStats: ['avg', 'min', 'med', 'p(95)', 'p(99)', 'max'],
  thresholds: { dropped_iterations: ['count==0'],
    'http_req_duration{phase:measure}': [], 'http_reqs{phase:measure}': [],
    'api_errors{phase:measure}': [] },
  // HTTP/1.0 server closes connections. Keep the same policy in every trial.
  noConnectionReuse: true,
  discardResponseBodies: false,
};
export default function () {
  const path = endpoint === 'cpu' ? `/api/cpu-load?iterations=${work}` : '/api/info';
  const phase = exec.instance.currentTestRunDuration < warmup * 1000 ? 'warmup' : 'measure';
  const response = http.get(`${base}${path}`, {
    timeout: '5s', tags: { name: endpoint, phase },
  });
  let body;
  try { body = response.json(); } catch (_) { body = null; }
  const ok = check(response, {
    'HTTP 200 and complete work': r => r.status === 200 && body !== null &&
      (endpoint === 'cpu' ? body.iterations === work && Number.isInteger(body.checksum) :
        body.service === 'aegis-step08-api'),
  });
  apiErrors.add(!ok, { phase });
}
export function handleSummary(data) {
  const measureRequests = data.metrics['http_reqs{phase:measure}'];
  const count = measureRequests ? measureRequests.values.count : 0;
  const result = { config: { rate, work, duration, warmup, preVUs, maxVUs, base, endpoint },
    measurement: { completedRequests: count, plannedWindowSeconds: Number(duration.slice(0, -1)),
      normalizedRps: count / Number(duration.slice(0, -1)),
      notice: 'Filtered counter rate uses whole-run time. Use raw timestamps for interrupted runs and steady-state windows.' },
    ...data };
  return { '/results/summary.json': JSON.stringify(result, null, 2),
    stdout: `STEP08_SUMMARY ${JSON.stringify(result)}\n` };
}
