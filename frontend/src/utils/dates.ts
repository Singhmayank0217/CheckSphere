// Calendar dates (e.g. Date of Birth) are stored as plain "YYYY-MM-DD" strings: no time and no timezone,
// so a date can never shift by a day when it is converted between IST, UTC and the device timezone.
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const ISO = /^(\d{4})-(\d{2})-(\d{2})$/;

export type YMD = { y: number; m: number; d: number }; // m = 1..12

export function parseIsoDate(v: unknown): YMD | null {
  const m = typeof v === "string" ? ISO.exec(v.trim()) : null;
  if (!m) return null;
  const y = Number(m[1]), mo = Number(m[2]), d = Number(m[3]);
  const probe = new Date(Date.UTC(y, mo - 1, d));
  if (probe.getUTCFullYear() !== y || probe.getUTCMonth() !== mo - 1 || probe.getUTCDate() !== d) return null; // 31-Feb etc.
  return { y, m: mo, d };
}

export function toIsoDate({ y, m, d }: YMD): string {
  return `${String(y).padStart(4, "0")}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

// Today's calendar date in India (the business timezone), independent of the phone's timezone setting.
export function todayIST(): YMD {
  const t = new Date(Date.now() + 330 * 60000);
  return { y: t.getUTCFullYear(), m: t.getUTCMonth() + 1, d: t.getUTCDate() };
}

export function isFuture(v: YMD): boolean {
  const t = todayIST();
  return toIsoDate(v) > toIsoDate(t);
}

// "1988-08-05" -> "05-Aug-1988". Anything else (historical free-text values) is shown exactly as stored.
export function fmtDob(v: unknown): string {
  const p = parseIsoDate(v);
  if (!p) return v == null || v === "" ? "—" : String(v);
  return `${String(p.d).padStart(2, "0")}-${MONTHS[p.m - 1]}-${p.y}`;
}

// Local-midnight Date for the native picker (it works in the device timezone); read back with getFullYear/... only.
export function ymdToLocalDate(v: YMD): Date {
  return new Date(v.y, v.m - 1, v.d, 12, 0, 0); // noon: immune to DST edges
}

export function localDateToYmd(dt: Date): YMD {
  return { y: dt.getFullYear(), m: dt.getMonth() + 1, d: dt.getDate() };
}
