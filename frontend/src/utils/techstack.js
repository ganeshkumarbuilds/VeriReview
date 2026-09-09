const STACK_KEYWORDS = [
  { name: "Spring Boot", pattern: /spring boot|spring\b/ },
  { name: "React", pattern: /react/ },
  { name: "Angular", pattern: /angular/ },
  { name: "Vue", pattern: /\bvue\b/ },
  { name: "Django", pattern: /django/ },
  { name: "Flask", pattern: /flask/ },
  { name: "FastAPI", pattern: /fastapi/ },
  { name: "Node.js", pattern: /node\.?js|\bnode\b|express|nestjs|nest\.js/ },
  { name: ".NET", pattern: /\.net\b|dotnet|asp\.net/ },
  { name: "Laravel", pattern: /laravel/ },
  { name: "PostgreSQL", pattern: /postgres/ },
  { name: "MySQL", pattern: /mysql/ },
  { name: "MongoDB", pattern: /mongo/ },
  { name: "JWT", pattern: /\bjwt\b/ },
  { name: "Docker", pattern: /docker/ },
  { name: "TypeScript", pattern: /typescript/ },
  { name: "Python", pattern: /python/ },
  { name: "Java", pattern: /\bjava\b/ },
];

export function detectTechStack(text) {
  const lower = (text || "").toLowerCase();
  if (!lower.trim()) return [];
  const found = [];
  for (const { name, pattern } of STACK_KEYWORDS) {
    if (pattern.test(lower) && !found.includes(name)) found.push(name);
  }
  return found;
}

export function parseApiKeys(text) {
  const out = {};
  for (const rawLine of (text || "").split("\n")) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq <= 0) continue;
    const key = line.slice(0, eq).trim();
    const value = line.slice(eq + 1).trim();
    if (key && value) out[key] = value;
  }
  return out;
}

const QUOTA_RE = /rate limit exceeded|free-models-per-day|daily reset/i;
const AUTH_RE = /api key rejected|OPENROUTER_API_KEY|unauthorized|401/i;

export function humanizeReport(text) {
  const s = String(text || "");
  if (!s.trim()) return "—";
  if (QUOTA_RE.test(s)) {
    return "AI models unavailable: the OpenRouter free-tier daily quota is exhausted (50 calls/day, resets midnight UTC). Add $10 credits for 1000/day, or wait for reset and run again.";
  }
  if (AUTH_RE.test(s)) {
    return "AI models unavailable: the backend API key was rejected. Check OPENROUTER_API_KEY and run again.";
  }
  // Never show raw provider JSON blobs (they leak user ids) — keep first line.
  if (s.includes("'user_id'") || s.includes("user_id")) {
    return s.split("\n")[0].slice(0, 220);
  }
  return s;
}
