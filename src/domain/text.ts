/** PostgreSQL char_length counts Unicode code points, not UTF-16 code units. */
export function countCodePoints(value: string): number {
  let count = 0;
  for (let index = 0; index < value.length; count += 1) {
    index += (value.codePointAt(index) ?? 0) > 0xffff ? 2 : 1;
  }
  return count;
}

export function limitCodePoints(value: string, limit: number): { value: string; length: number } {
  let length = 0;
  let end = 0;
  while (end < value.length && length !== limit) {
    length += 1;
    end += (value.codePointAt(end) ?? 0) > 0xffff ? 2 : 1;
  }
  return { value: value.slice(0, end), length };
}
