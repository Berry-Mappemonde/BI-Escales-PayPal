import type { AgAiEvent, AgAiHarnessSetup, AgAiMessage, AgAiRunInput, AgLlmAdapter } from "ag-studio";
import {
  AgStudioAiModule,
  clientToolRunner,
  createAiHarness,
  directLlmRunner,
} from "ag-studio";
import {
  nextDataAgentAction,
  nextTreasurerAction,
  VALIDATION_NOTE_ID,
  VALIDATION_WIDGET_TYPE,
} from "./agentPlan";
import { studioT } from "./locale";
import { proxyLlmAdapter } from "./llmAdapter";

export { AgStudioAiModule };

function toolMessageCount(messages: AgAiMessage[]): number {
  return messages.filter((message) => message.role === "tool").length;
}

function lastToolText(messages: AgAiMessage[]): string {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message.role === "tool") return message.content;
  }
  return "";
}

function lastUserText(messages: AgAiMessage[]): string {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message.role === "user") return message.content;
  }
  return "";
}

function* say(messageId: string, text: string): Generator<AgAiEvent> {
  yield { type: "TEXT_MESSAGE_START", messageId, role: "assistant" };
  yield { type: "TEXT_MESSAGE_CONTENT", messageId, delta: text };
  yield { type: "TEXT_MESSAGE_END", messageId };
}

function* callTool(toolCallId: string, name: string, args: unknown): Generator<AgAiEvent> {
  yield { type: "TOOL_CALL_START", toolCallId, toolCallName: name };
  yield { type: "TOOL_CALL_ARGS", toolCallId, delta: JSON.stringify(args) };
  yield { type: "TOOL_CALL_END", toolCallId };
}

export function treasurerSpeech(userText: string, toolMessageCount: number, language?: string): string {
  const t = studioT(language);
  const action = nextTreasurerAction(userText, toolMessageCount, language);
  if (action.kind === "delegate-data") return t("studio.agentDelegating");
  if (action.kind === "add-validation-widget") return t("studio.agentAdding");
  const added = userText.length > 0 && toolMessageCount > 1;
  return added ? t("studio.agentReplyAdded") : t("studio.agentReply");
}

export function treasurerPromptStarters(language?: string) {
  const t = studioT(language);
  return [
    { label: t("studio.promptTotals"), prompt: t("studio.promptTotalsText") },
    { label: t("studio.promptWidget"), prompt: t("studio.promptWidgetText") },
  ];
}

export function treasurerAgentProfile(language?: string) {
  const t = studioT(language);
  return {
    id: "tresorier",
    name: t("studio.agentName"),
    description: t("studio.agentDescription"),
  };
}

async function* runTreasurer(input: AgAiRunInput): AsyncGenerator<AgAiEvent> {
  const userText = lastUserText(input.messages);
  const toolCount = toolMessageCount(input.messages);
  const action = nextTreasurerAction(userText, toolCount);
  const stamp = `${input.runId}-${input.messages.length}`;
  if (action.kind === "delegate-data") {
    yield* say(stamp, treasurerSpeech(userText, toolCount));
    yield* callTool(`delegate-${stamp}`, "delegate_to", {
      type: { id: "data" },
      instructions: action.instructions,
    });
    return;
  }
  if (action.kind === "add-validation-widget") {
    yield* say(stamp, treasurerSpeech(userText, toolCount));
    yield* callTool(`add-${stamp}`, "add_widget", {
      widgetId: VALIDATION_NOTE_ID,
      type: VALIDATION_WIDGET_TYPE,
      xTrack: 0,
      yTrack: 22,
      xSpan: 24,
      ySpan: 8,
    });
    return;
  }
  yield* say(stamp, treasurerSpeech(userText, toolCount));
}

/** Runs one treasurer turn and returns the text the reader sees. */
export async function spokenTreasurerReply(userText: string, priorToolMessages = 0): Promise<string> {
  const messages = [
    ...(userText ? [{ role: "user" as const, content: userText }] : []),
    ...Array.from({ length: priorToolMessages }, () => ({ role: "tool" as const, content: "schema" })),
  ];
  const input = { runId: "preview", messages } as AgAiRunInput;
  let text = "";
  for await (const event of runTreasurer(input)) {
    if (event.type === "TEXT_MESSAGE_CONTENT") text += event.delta;
  }
  return text;
}

async function* runBuiltInData(input: AgAiRunInput): AsyncGenerator<AgAiEvent> {
  const action = nextDataAgentAction(toolMessageCount(input.messages), lastToolText(input.messages));
  const stamp = `${input.runId}-${input.messages.length}`;
  if (action.kind === "view-schema") {
    yield* callTool(`schema-${stamp}`, "view_schema", {});
    return;
  }
  yield* callTool(`done-${stamp}`, "complete_task", { summary: action.summary, artifacts: [] });
}

export function createTreasurerHarness(endpoint: string | undefined, language?: string): AgAiHarnessSetup {
  const adapter: AgLlmAdapter | undefined = endpoint ? proxyLlmAdapter(endpoint) : undefined;
  return ({ api }) =>
    createAiHarness(api, ({ builtIn, tools }) => {
      const dataAgent = adapter
        ? directLlmRunner({ ...builtIn.data, adapter, schema: (shape) => shape.undefined() })
        : clientToolRunner({
            ...builtIn.data,
            schema: (shape) => shape.undefined(),
            maxTurns: 4,
            run: runBuiltInData,
          });
      const llmSpecialists = adapter
        ? (["page", "planning", "widget"] as const).map((id) =>
            directLlmRunner({ ...builtIn[id], adapter }),
          )
        : [];
      const profile = treasurerAgentProfile(language);
      const tresorier = clientToolRunner({
        id: profile.id,
        name: profile.name,
        description: profile.description,
        schema: (shape) => shape.undefined(),
        maxTurns: 6,
        tools: () => [
          tools.studio.viewSchema(),
          tools.studio.viewPage(),
          tools.studio.addWidget(),
          tools.delegateTo(["data"]),
        ],
        run: runTreasurer,
      });
      return {
        agents: [tresorier, dataAgent, ...llmSpecialists],
        primary: "tresorier",
        promptStarters: treasurerPromptStarters(language),
      };
    });
}
