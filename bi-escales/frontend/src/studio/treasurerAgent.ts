import type { AgAiEvent, AgAiHarnessSetup, AgAiMessage, AgAiRunInput } from "ag-studio";
import {
  AgStudioAiModule,
  clientToolRunner,
  createAiHarness,
} from "ag-studio";
import {
  FUNDING_WIDGET_ID,
  FUNDING_WIDGET_TYPE,
  nextDataAgentAction,
  nextTreasurerAction,
  VALIDATION_NOTE_ID,
  VALIDATION_WIDGET_TYPE,
} from "./agentPlan";
import { dashboardCopy } from "./dashboardLocale";
import { studioLanguage, studioT } from "./locale";
import { askLedgerModel, type LedgerSummary } from "./llmAdapter";

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
  const copy = dashboardCopy(studioLanguage(language));
  if (action.kind === "add-funding-widget") return copy.agentAdding;
  if (toolMessageCount > 1) {
    const placed = nextTreasurerAction(userText, 1, language);
    if (placed.kind === "add-funding-widget") return copy.agentAdded;
    if (placed.kind === "add-validation-widget") return t("studio.agentReplyAdded");
  }
  return t("studio.agentReply");
}

export function treasurerPromptStarters(language?: string) {
  const t = studioT(language);
  const copy = dashboardCopy(studioLanguage(language));
  return [
    { label: t("studio.promptTotals"), prompt: t("studio.promptTotalsText") },
    { label: t("studio.promptWidget"), prompt: t("studio.promptWidgetText") },
    { label: copy.promptFunding, prompt: copy.promptFundingText },
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

async function* runTreasurer(
  input: AgAiRunInput,
  language?: string,
  summarize?: (question: string) => Promise<string | undefined>,
  signal?: AbortSignal,
): AsyncGenerator<AgAiEvent> {
  const userText = lastUserText(input.messages);
  const lastUser = input.messages.map((message) => message.role).lastIndexOf("user");
  const toolCount = toolMessageCount(input.messages.slice(lastUser + 1));
  const action = nextTreasurerAction(userText, toolCount, language);
  const stamp = `${input.runId}-${input.messages.length}`;
  if (action.kind === "delegate-data") {
    if (summarize && nextTreasurerAction(userText, 1, language).kind === "reply") {
      const summary = await summarize(userText);
      if (signal?.aborted) return;
      if (summary) {
        yield* say(stamp, summary);
        return;
      }
    }
    yield* say(stamp, treasurerSpeech(userText, toolCount, language));
    yield* callTool(`delegate-${stamp}`, "delegate_to", {
      type: { id: "data" },
      instructions: action.instructions,
    });
    return;
  }
  if (action.kind === "add-validation-widget" || action.kind === "add-funding-widget") {
    const funding = action.kind === "add-funding-widget";
    yield* say(stamp, treasurerSpeech(userText, toolCount, language));
    yield* callTool(`add-${stamp}`, "add_widget", {
      widgetId: funding ? FUNDING_WIDGET_ID : VALIDATION_NOTE_ID,
      type: funding ? FUNDING_WIDGET_TYPE : VALIDATION_WIDGET_TYPE,
      xTrack: 0,
      yTrack: funding ? 38 : 27,
      xSpan: 24,
      ySpan: funding ? 14 : 11,
    });
    return;
  }
  yield* say(stamp, treasurerSpeech(userText, toolCount, language));
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

async function* runBuiltInData(input: AgAiRunInput, language?: string): AsyncGenerator<AgAiEvent> {
  const action = nextDataAgentAction(toolMessageCount(input.messages), lastToolText(input.messages), language);
  const stamp = `${input.runId}-${input.messages.length}`;
  if (action.kind === "view-schema") {
    yield* callTool(`schema-${stamp}`, "view_schema", {});
    return;
  }
  yield* callTool(`done-${stamp}`, "complete_task", { summary: action.summary, artifacts: [] });
}

export function createTreasurerHarness(
  endpoint: string | undefined, language: string, ledger: LedgerSummary,
): AgAiHarnessSetup {
  return ({ api }) =>
    createAiHarness(api, ({ builtIn, tools }) => {
      const dataAgent = clientToolRunner({
        ...builtIn.data,
        schema: (shape) => shape.undefined(),
        maxTurns: 4,
        run: (input) => runBuiltInData(input, language),
      });
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
        run: (input, { signal }) => runTreasurer(
          input, language,
          endpoint ? (question) => askLedgerModel(endpoint, ledger, question, language, signal) : undefined,
          signal,
        ),
      });
      return {
        agents: [tresorier, dataAgent],
        primary: "tresorier",
        promptStarters: treasurerPromptStarters(language),
      };
    });
}
