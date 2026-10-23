type DateInput = string | number | Date | null | undefined;

const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;

function toDate(value: DateInput): Date | null {
  if (value === null || value === undefined || value === '') return null;
  const day = typeof value === 'string' ? DATE_ONLY.exec(value) : null;
  // A calendar date ("2026-11-30") means that day wherever the operator is, not UTC midnight.
  const date = day ? new Date(Number(day[1]), Number(day[2]) - 1, Number(day[3])) : value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

const dateFormat = new Intl.DateTimeFormat('en-US', {month: 'short', day: 'numeric', year: 'numeric'});
const shortDateFormat = new Intl.DateTimeFormat('en-US', {month: 'short', day: 'numeric'});
const timeFormat = new Intl.DateTimeFormat('en-US', {hour: 'numeric', minute: '2-digit', hour12: true});
const numberFormat = new Intl.NumberFormat('en-US');

/** "Oct 23, 2026" */
export function formatDate(value: DateInput, fallback = '—') {
  const date = toDate(value);
  return date ? dateFormat.format(date) : fallback;
}

/** "Oct 23" */
export function formatShortDate(value: DateInput, fallback = '—') {
  const date = toDate(value);
  return date ? shortDateFormat.format(date) : fallback;
}

/** "9:00 AM" — Intl may emit a narrow no-break space before AM/PM. */
export function formatTime(value: DateInput, fallback = '—') {
  const date = toDate(value);
  return date ? timeFormat.format(date).replace(/[\u202f\u00a0]/g, ' ') : fallback;
}

/** "Oct 23, 2026 at 9:00 AM" */
export function formatDateTime(value: DateInput, fallback = '—') {
  const date = toDate(value);
  return date ? `${formatDate(date)} at ${formatTime(date)}` : fallback;
}

/** "Oct 23, 2026 at 9:00 AM, by Priya Patel" */
export function formatAttribution(value: DateInput, actor: string | null | undefined) {
  const when = formatDateTime(value);
  return actor ? `${when}, by ${actor}` : when;
}

/** "25,000" */
export function formatNumber(value: number | null | undefined, fallback = '—') {
  return typeof value === 'number' && Number.isFinite(value) ? numberFormat.format(value) : fallback;
}

/** Local calendar date as YYYY-MM-DD for <input type="date"> values. */
export function toDateInput(date: Date) {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function addDays(date: Date, days: number) {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

export function addMonths(date: Date, months: number) {
  const next = new Date(date);
  next.setMonth(next.getMonth() + months);
  return next;
}

/** The UTC calendar day ("2026-11-30") of a billing timestamp, or the value itself when it's already a date. */
export function billingDay(value: string | null | undefined) {
  if (!value) return '';
  return /^\d{4}-\d{2}-\d{2}/.test(value) ? value.slice(0, 10) : '';
}

/** Billing period boundaries are stored as UTC midnight of the chosen day. */
export function dayToTimestamp(day: string) {
  return `${day}T00:00:00Z`;
}

/** "Oct 23, 2026" for a billing timestamp or date, using its UTC calendar day. */
export function formatBillingDate(value: string | null | undefined, fallback = '—') {
  return formatDate(billingDay(value) || null, fallback);
}

/** "Oct 1 – Nov 30, 2026", or "Dec 1, 2026 – Jan 31, 2027" across years. */
export function formatPeriod(start: string | null | undefined, end: string | null | undefined, fallback = '—') {
  const from = toDate(billingDay(start) || null);
  const to = toDate(billingDay(end) || null);
  if (!from || !to) return fallback;
  return from.getFullYear() === to.getFullYear() ? `${formatShortDate(from)} – ${formatDate(to)}` : `${formatDate(from)} – ${formatDate(to)}`;
}

/** Minor-unit digits for an ISO 4217 currency (2 for USD, 0 for JPY). */
export function currencyDigits(currency: string) {
  try {
    return new Intl.NumberFormat('en-US', {style: 'currency', currency}).resolvedOptions().maximumFractionDigits ?? 2;
  } catch {
    return 2;
  }
}

export function isCurrencyCode(value: string) {
  if (!/^[A-Z]{3}$/.test(value)) return false;
  try {new Intl.NumberFormat('en-US', {style: 'currency', currency: value}); return true;} catch {return false;}
}

/** "$1,200.00", "-$500.00", or "USD 1,200.00" with `code` for multi-currency lists. */
export function formatMoney(amountMinor: number | null | undefined, currency: string | null | undefined, options: {code?: boolean} = {}, fallback = '—') {
  if (typeof amountMinor !== 'number' || !Number.isFinite(amountMinor) || !currency) return fallback;
  try {
    const format = new Intl.NumberFormat('en-US', {style: 'currency', currency, currencyDisplay: options.code ? 'code' : 'symbol'});
    const digits = format.resolvedOptions().maximumFractionDigits ?? 2;
    return format.format(amountMinor / 10 ** digits).replace(/[\u202f\u00a0]/g, ' ');
  } catch {
    return `${currency} ${formatNumber(amountMinor)}`;
  }
}

/** Parses an amount typed in major units ("1,200.50") into minor units, or null when it isn't a valid amount. */
export function parseMoney(text: string, currency: string): number | null {
  const match = /^(\d{1,13})(?:\.(\d*))?$/.exec(text.trim().replace(/,/g, ''));
  if (!match) return null;
  const digits = currencyDigits(currency);
  const fraction = match[2] || '';
  if (fraction.length > digits) return null;
  return Number(match[1]) * 10 ** digits + Number(fraction.padEnd(digits, '0') || '0');
}

/** Minor units as an editable major-unit string ("1200.00"). */
export function moneyInput(amountMinor: number | null | undefined, currency: string) {
  if (typeof amountMinor !== 'number') return '';
  const digits = currencyDigits(currency);
  return digits ? (amountMinor / 10 ** digits).toFixed(digits) : String(amountMinor);
}

/** True when the text contains a 13–19 digit sequence that passes the Luhn check. */
export function containsCardNumber(text: string) {
  for (const match of text.matchAll(/\d(?:[ -]?\d){12,}/g)) {
    const digits = match[0].replace(/\D/g, '');
    if (digits.length <= 19 && luhn(digits)) return true;
  }
  return false;
}

function luhn(digits: string) {
  let sum = 0;
  for (let index = 0; index < digits.length; index++) {
    let digit = Number(digits[digits.length - 1 - index]);
    if (index % 2 === 1) {digit *= 2; if (digit > 9) digit -= 9;}
    sum += digit;
  }
  return sum % 10 === 0;
}

/** "https://billing.example.com/acme" with no credentials, query or fragment; returns an error message or ''. */
export function httpsUrlError(value: string) {
  if (!value.trim()) return '';
  let url: URL;
  try {url = new URL(value.trim());} catch {return 'Enter a full link that starts with https://.';}
  if (url.protocol !== 'https:') return 'Enter a link that starts with https://.';
  if (url.username || url.password || url.search || url.hash) return 'Remove any sign-in details, query string or # fragment from the link.';
  return '';
}
