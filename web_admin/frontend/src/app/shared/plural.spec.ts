import { FILE_FORMS, filesCount, pluralUk } from './plural';

describe('pluralUk', () => {
  it('picks the one/few/many form by the last digit', () => {
    expect(pluralUk(1, FILE_FORMS)).toBe('файл');
    expect(pluralUk(2, FILE_FORMS)).toBe('файли');
    expect(pluralUk(4, FILE_FORMS)).toBe('файли');
    expect(pluralUk(5, FILE_FORMS)).toBe('файлів');
    expect(pluralUk(20, FILE_FORMS)).toBe('файлів');
    expect(pluralUk(21, FILE_FORMS)).toBe('файл');
    expect(pluralUk(22, FILE_FORMS)).toBe('файли');
    expect(pluralUk(101, FILE_FORMS)).toBe('файл');
  });

  it('gives the «many» form to the 11-14 band despite the last digit', () => {
    expect(pluralUk(11, FILE_FORMS)).toBe('файлів');
    expect(pluralUk(12, FILE_FORMS)).toBe('файлів');
    expect(pluralUk(14, FILE_FORMS)).toBe('файлів');
    expect(pluralUk(111, FILE_FORMS)).toBe('файлів');
    expect(pluralUk(112, FILE_FORMS)).toBe('файлів');
  });

  it('handles zero and never breaks on a stray fraction or sign', () => {
    expect(pluralUk(0, FILE_FORMS)).toBe('файлів');
    expect(pluralUk(-1, FILE_FORMS)).toBe('файл');
    expect(pluralUk(1.7, FILE_FORMS)).toBe('файл');
  });

  it('renders the count together with its form', () => {
    expect(filesCount(1)).toBe('1 файл');
    expect(filesCount(3)).toBe('3 файли');
    expect(filesCount(12)).toBe('12 файлів');
  });
});
