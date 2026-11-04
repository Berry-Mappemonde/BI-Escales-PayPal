export const LOGBOOK_CHAT_TIMEOUT_MS = 45000;

const detailText = (detail) => {
  if (typeof detail === "string") return detail;
  if (detail == null) return "";
  try { return JSON.stringify(detail); } catch { return String(detail); }
};

function errorCode(status, detail) {
  const text = detailText(detail).toLowerCase();
  if (status === 413 || ((status === 400 || status === 422) && /trop long|too long|volumineux/.test(text))) return "tooLong";
  if ((status === 400 && /empty|vide/.test(text)) || (status === 422 && /empty|vide/.test(text))) return "empty";
  return "server";
}

export async function postLogbookChat({ url, body, fetchImpl = fetch, timeoutMs = LOGBOOK_CHAT_TIMEOUT_MS, signal }) {
  const controller = new AbortController();
  let timedOut = false;
  const timeoutError = Object.assign(new Error("Request timed out"), { code: "timeout", detail: null, status: null });
  const abortFromExternalSignal = () => controller.abort(signal?.reason);
  if (signal?.aborted) abortFromExternalSignal();
  else signal?.addEventListener("abort", abortFromExternalSignal, { once: true });
  let rejectAborted;
  const aborted = new Promise((_, reject) => { rejectAborted = reject; });
  const abortError = Object.assign(new Error("Request aborted"), { code: "aborted", detail: null, status: null });
  const rejectAbortedRequest = () => rejectAborted(abortError);
  if (signal?.aborted) rejectAbortedRequest();
  else signal?.addEventListener("abort", rejectAbortedRequest, { once: true });
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
    rejectTimeout(timeoutError);
  }, timeoutMs);
  let rejectTimeout;
  const timeout = new Promise((_, reject) => { rejectTimeout = reject; });

  try {
    const parseJson = async (response) => {
      try {
        const payload = await response.json();
        if (timedOut) throw Object.assign(new Error("Request timed out"), { code: "timeout", detail: null, status: null });
        if (signal?.aborted) throw Object.assign(new Error("Request aborted"), { code: "aborted", detail: null, status: null });
        return payload;
      } catch (err) {
        if (timedOut) throw Object.assign(new Error("Request timed out"), { code: "timeout", detail: null, status: null });
        if (signal?.aborted) throw Object.assign(new Error("Request aborted"), { code: "aborted", detail: null, status: null });
        throw err;
      }
    };
    const request = (async () => {
      let response;
      try {
        response = await fetchImpl(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: controller.signal });
      } catch (err) {
        if (timedOut) throw Object.assign(new Error("Request timed out"), { code: "timeout", detail: null, status: null });
        if (signal?.aborted) throw Object.assign(new Error("Request aborted"), { code: "aborted", detail: null, status: null });
        if (err instanceof TypeError || err?.name === "TypeError") throw Object.assign(new Error("Network request failed"), { code: "network", detail: err.message, status: null });
        throw err;
      }
      if (response.ok) return await parseJson(response);
      const payload = await parseJson(response).catch((err) => {
        if (err?.code === "timeout" || err?.code === "aborted") throw err;
        return {};
      });
      const detail = payload?.detail ?? null;
      const code = errorCode(response.status, detail);
      throw Object.assign(new Error(detailText(detail) || `HTTP ${response.status}`), { code, detail, status: response.status });
    })();
    return await Promise.race([request, timeout, aborted]);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abortFromExternalSignal);
    signal?.removeEventListener("abort", rejectAbortedRequest);
  }
}

export function chatErrorKey(code) {
  return ({
    timeout: "chatErrTimeout",
    network: "chatErrNetwork",
    empty: "chatErrEmpty",
    tooLong: "chatErrTooLong",
    server: "chatErrServer",
  })[code] || "chatErrServer";
}
