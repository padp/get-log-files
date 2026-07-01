export function getId(value) {
  if (!value) return null;
  if (typeof value === "string") return value;
  if (value.$oid) return value.$oid;
  return String(value);
}
