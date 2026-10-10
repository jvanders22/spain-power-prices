export const fmt1 = (v: number): string => v.toFixed(1);

/** Percent with one decimal, dropping a trailing ".0" (56.0 -> "56%"). */
export const fmtPct = (v: number): string => {
  const s = v.toFixed(1);
  return `${s.endsWith('.0') ? s.slice(0, -2) : s}%`;
};

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** "2024-10-01" -> "Oct 2024" */
export const fmtMonth = (isoDate: string): string => {
  const [y, m] = isoDate.split('-');
  return `${MONTHS[Number(m) - 1]} ${y}`;
};
