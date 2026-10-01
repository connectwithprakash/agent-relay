const HAS_OFFSET = /(?:Z|[+-]\d{2}:?\d{2})$/i;

// The backend stores naive UTC datetimes and serializes them without an offset.
// Date.parse reads an offset-less ISO string as local time, so pin those to UTC.
export function parseServerTimestamp(value) {
  if (typeof value !== 'string' || !value) return Number.NaN;
  return Date.parse(HAS_OFFSET.test(value) ? value : `${value}Z`);
}
