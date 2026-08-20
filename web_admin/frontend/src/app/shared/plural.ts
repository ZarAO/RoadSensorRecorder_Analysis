/**
 * Ukrainian plural forms for UI copy: «1 файл», «2 файли», «5 файлів».
 * A hardcoded «N файлів» reads wrong for every N ending in 1-4, which the
 * confirm/reanalyze counts hit constantly (1 file is the common case).
 */

/** [one, few, many] — the three forms Ukrainian needs for a counted noun. */
export type PluralForms = [string, string, string];

export const FILE_FORMS: PluralForms = ['файл', 'файли', 'файлів'];

/**
 * The form for `count`: 1/21/101 -> one, 2-4/22-24 -> few, 5-20/11-14 -> many.
 * The 11-14 band takes the «many» form even though it ends in 1-4, so the
 * modulo-100 test has to come first.
 */
export function pluralUk(count: number, forms: PluralForms): string {
  const n = Math.abs(Math.trunc(count));
  const withinHundred = n % 100;
  if (withinHundred >= 11 && withinHundred <= 14) return forms[2];
  const lastDigit = n % 10;
  if (lastDigit === 1) return forms[0];
  if (lastDigit >= 2 && lastDigit <= 4) return forms[1];
  return forms[2];
}

/** «1 файл» / «3 файли» / «11 файлів» — the count with its plural form. */
export function filesCount(count: number): string {
  return `${count} ${pluralUk(count, FILE_FORMS)}`;
}
