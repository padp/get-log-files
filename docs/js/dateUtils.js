export function getDate(value) {
  if (!value) return new Date(0);

  if (typeof value === "string") return new Date(value);

  if (value.$date) return new Date(value.$date);

  return new Date(value);
}
