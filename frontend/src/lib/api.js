const inferredApiBase =
  typeof window !== "undefined"
    ? `${window.location.protocol}//${window.location.hostname}:8002`
    : "http://localhost:8002";

export const API_BASE =
  import.meta.env.VITE_API_BASE ||
  import.meta.env.VITE_API_URL ||
  inferredApiBase;

export async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;

  if (!isFormData && !headers["Content-Type"] && !headers["content-type"]) {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : { message: await response.text() };

  if (!response.ok) {
    const message =
      payload?.error || payload?.message || `Request failed with status ${response.status}`;
    throw new Error(message);
  }

  return payload;
}
