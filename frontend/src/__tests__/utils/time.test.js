import { describe, expect, it } from 'vitest';
import { parseServerTimestamp } from '../../utils/time';

const EPOCH = Date.UTC(2026, 9, 1, 7, 3, 46);

describe('parseServerTimestamp', () => {
  it('reads a timestamp without an offset as UTC', () => {
    expect(parseServerTimestamp('2026-10-01T07:03:46')).toBe(EPOCH);
  });

  it('keeps fractional seconds on a timestamp without an offset', () => {
    expect(parseServerTimestamp('2026-10-01T07:03:46.074334')).toBe(EPOCH + 74);
  });

  it.each(['2026-10-01T07:03:46Z', '2026-10-01T07:03:46+00:00', '2026-10-01T00:03:46-07:00', '2026-10-01T12:33:46+05:30'])(
    'honors an explicit offset in %s', (value) => {
      expect(parseServerTimestamp(value)).toBe(EPOCH);
    },
  );

  it.each([null, undefined, '', 'not a date'])('returns NaN for %j', (value) => {
    expect(parseServerTimestamp(value)).toBeNaN();
  });
});
