import type { AgAiEvent, AgAiOutputItem, AgLlmAdapter, AgLlmResponse } from "ag-studio";

/**
 * Posts Studio's own turn payload to a proxy. The proxy holds the provider key.
 * The browser sends no secret. The proxy returns an AgLlmResponse JSON body.
 */
export function proxyLlmAdapter(endpoint: string): AgLlmAdapter {
  return {
    executeTurn(request, options) {
      const complete = (async (): Promise<AgLlmResponse> => {
        const response = await fetch(endpoint, {
          method: "POST",
          headers: { "content-type": "application/json", accept: "application/json" },
          body: JSON.stringify({ request }),
          signal: options?.signal,
        });
        if (!response.ok) {
          return {
            id: "proxy-error",
            createdAt: Date.now(),
            status: "failed",
            output: [],
            error: { code: String(response.status), message: `LLM proxy HTTP ${response.status}` },
          };
        }
        return (await response.json()) as AgLlmResponse;
      })();
      const stream = (async function* (): AsyncGenerator<AgAiEvent> {
        yield* eventsFromLlmResponse(await complete);
      })();
      return { stream, complete };
    },
  };
}

export function* eventsFromLlmResponse(body: AgLlmResponse): Generator<AgAiEvent> {
  if (body.error) {
    const messageId = `${body.id}-error`;
    yield { type: "TEXT_MESSAGE_START", messageId, role: "assistant" };
    yield { type: "TEXT_MESSAGE_CONTENT", messageId, delta: body.error.message };
    yield { type: "TEXT_MESSAGE_END", messageId };
  }
  for (const item of body.output ?? []) {
    yield* eventsFromOutputItem(item);
  }
}

function* eventsFromOutputItem(item: AgAiOutputItem): Generator<AgAiEvent> {
  if (item.type === "message") {
    const text = item.content
      .map((part) => (part.type === "text" ? part.text : part.refusal))
      .join("");
    yield { type: "TEXT_MESSAGE_START", messageId: item.id, role: "assistant" };
    yield { type: "TEXT_MESSAGE_CONTENT", messageId: item.id, delta: text };
    yield { type: "TEXT_MESSAGE_END", messageId: item.id };
    return;
  }
  if (item.type === "function_call") {
    yield { type: "TOOL_CALL_START", toolCallId: item.callId, toolCallName: item.name };
    yield { type: "TOOL_CALL_ARGS", toolCallId: item.callId, delta: item.arguments };
    yield { type: "TOOL_CALL_END", toolCallId: item.callId };
  }
}
