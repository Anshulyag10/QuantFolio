// Thin client for the FastAPI backend (server.py). All numbers in the UI come from here.

async function request(path, body) {
  let res;
  try {
    res = await fetch(path, body === undefined ? {} : {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (e) {
    throw new Error("Cannot reach the QuantFolio server. Is `python server.py` running?");
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try { detail = (await res.json()).detail || detail; } catch (e) { /* not JSON */ }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json();
}

export const api = {
  meta: () => request("/api/meta"),
  universe: (cfg) => request("/api/universe", cfg),
  analyze: (cfg) => request("/api/analyze", cfg),
  montecarlo: (cfg) => request("/api/montecarlo", cfg),
  experiments: () => request("/api/experiments"),
};
