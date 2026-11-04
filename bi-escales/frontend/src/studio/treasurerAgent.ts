import type { AgAiEvent, AgAiHarnessSetup, AgAiMessage, AgAiRunInput, AgLlmAdapter } from "ag-studio";
import {
  AgStudioAiModule,
  clientToolRunner,
  createAiHarness,
  directLlmRunner,
} from "ag-studio";
import i18n from "../i18n";
import {
  nextDataAgentAction,
  nextTreasurerAction,
  VALIDATION_NOTE_ID,
  VALIDATION_WIDGET_TYPE,
} from "./agentPlan";
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

async function* runTreasurer(input: AgAiRunInput): AsyncGenerator<AgAiEvent> {
  const userText = lastUserText(input.messages);
  const action = nextTreasurerAction(userText, toolMessageCount(input.messages));
  const stamp = `${input.runId}-${input.messages.length}`;
  if (action.kind === "delegate-data") {
    yield* say(stamp, i18n.t("studio.agentDelegating"));
    yield* callTool(`delegate-${stamp}`, "delegate_to", {
      type: { id: "data" },
      instructions: action.instructions,
    });
    return;
  }
  if (action.kind === "add-validation-widget") {
    yield* say(stamp, i18n.t("studio.agentAdding"));
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
  const added = userText.length > 0 && action.kind === "reply" && toolMessageCount(input.messages) > 1;
  yield* say(stamp, added ? i18n.t("studio.agentReplyAdded") : i18n.t("studio.agentReply"));
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

export function createTreasurerHarness(endpoint: string | undefined): AgAiHarnessSetup {
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
      const tresorier = clientToolRunner({
        id: "tresorier",
        name: "Trésorier",
        description:
          "BI Escales treasurer. Delegates data questions to Studio's data agent and never captures a pledge.",
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
        promptStarters: [
          { label: i18n.t("studio.promptTotals"), prompt: i18n.t("studio.promptTotalsText") },
          { label: i18n.t("studio.promptWidget"), prompt: i18n.t("studio.promptWidgetText") },
        ],
      };
    });
}
