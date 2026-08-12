export function isArxivUrl(value: string): boolean {
  try {
    const hostname = new URL(value).hostname.toLowerCase().replace(/\.$/u, "");
    return hostname === "arxiv.org" || hostname.endsWith(".arxiv.org");
  } catch {
    return false;
  }
}
