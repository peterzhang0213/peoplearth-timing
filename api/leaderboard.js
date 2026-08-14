const UPSTREAM_URL = "https://lfzvkqwpekgtkcnpzbqj.supabase.co/functions/v1/timing-api/leaderboard";
const RACE_ID_PATTERN = /^[A-Za-z0-9_-]{1,80}$/;
const UPSTREAM_TIMEOUT_MS = 8000;

function setCorsHeaders(response) {
  response.setHeader("Access-Control-Allow-Origin", "*");
  response.setHeader("Access-Control-Allow-Methods", "GET, OPTIONS");
  response.setHeader("Access-Control-Allow-Headers", "Content-Type, apikey");
}

module.exports = async function leaderboard(request, response) {
  setCorsHeaders(response);

  if (request.method === "OPTIONS") {
    response.statusCode = 204;
    response.setHeader("Cache-Control", "no-store");
    response.end();
    return;
  }
  if (request.method !== "GET") {
    response.statusCode = 405;
    response.setHeader("Allow", "GET, OPTIONS");
    response.setHeader("Cache-Control", "no-store");
    response.end(JSON.stringify({ ok: false, error: "Method not allowed" }));
    return;
  }

  const rawRaceId = Array.isArray(request.query?.raceId)
    ? request.query.raceId[0]
    : request.query?.raceId;
  const raceId = String(rawRaceId || "").trim();
  const apiKey = String(request.headers.apikey || "").trim();
  if (!RACE_ID_PATTERN.test(raceId) || !apiKey) {
    response.statusCode = 400;
    response.setHeader("Content-Type", "application/json; charset=utf-8");
    response.setHeader("Cache-Control", "no-store");
    response.end(JSON.stringify({ ok: false, error: "Valid raceId and apikey are required" }));
    return;
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), UPSTREAM_TIMEOUT_MS);
  try {
    const upstream = await fetch(`${UPSTREAM_URL}?raceId=${encodeURIComponent(raceId)}`, {
      headers: { apikey: apiKey },
      signal: controller.signal,
    });
    const body = await upstream.text();
    response.statusCode = upstream.status;
    response.setHeader("Content-Type", upstream.headers.get("content-type") || "application/json; charset=utf-8");
    if (upstream.ok) {
      response.setHeader("Cache-Control", "public, max-age=0, s-maxage=2, stale-while-revalidate=15");
    } else {
      response.setHeader("Cache-Control", "no-store");
    }
    response.end(body);
  } catch (error) {
    response.statusCode = 502;
    response.setHeader("Content-Type", "application/json; charset=utf-8");
    response.setHeader("Cache-Control", "no-store");
    response.end(JSON.stringify({
      ok: false,
      error: error?.name === "AbortError" ? "Leaderboard upstream timed out" : "Leaderboard upstream unavailable",
    }));
  } finally {
    clearTimeout(timeoutId);
  }
};
