export async function api<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: body ? { Accept: 'application/json', 'Content-Type': 'application/json' } : { Accept: 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (!response.ok) {
    let detail = 'Request failed';
    try {
      const errorData = await response.json();
      detail = errorData.detail ?? detail;
    } catch {
      // Ignore JSON parse failures and keep fallback detail.
    }
    throw new Error(detail);
  }

  return (await response.json()) as T;
}
