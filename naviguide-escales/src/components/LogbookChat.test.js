import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, "LogbookChat.jsx"), "utf8");
const hook = readFileSync(join(here, "..", "hooks", "useLogbookChat.js"), "utf8");
const sidebar = readFileSync(join(here, "Sidebar.jsx"), "utf8");

describe("LogbookChat contract", () => {
  it("announces new messages and errors, and labels the chat controls", () => {
    assert.match(src, /data-testid="logbook-chat-list"[^>]*role="log"[^>]*aria-live="polite"/);
    assert.match(src, /role="alert"[^>]*data-testid="logbook-chat-error"/);
    assert.match(src, /aria-label=\{t\("logbookChatInputLabel"\)\}/);
    assert.match(src, /aria-label=\{t\("logbookChatSend"\)\}/);
    const en = readFileSync(join(here, "..", "i18n", "en.js"), "utf8");
    const fr = readFileSync(join(here, "..", "i18n", "fr.js"), "utf8");
    assert.match(en, /logbookChatInputLabel: "Ask the logbook"/);
    assert.match(fr, /logbookChatInputLabel: "Votre question au carnet de bord"/);
  });

  it("affiche l’avis au premier échange et s’en souvient", () => {
    assert.match(src, /data-testid="logbook-chat-ai-notice"/);
    assert.match(src, /data-testid="logbook-chat-ai-notice-dismiss"/);
    assert.match(src, /aiActChatNotice/);
    assert.match(src, /naviguide-ai-act-chat-notice-v1/);
    assert.match(src, /onFocus=\{onChatFocus\}/);
    assert.match(src, /messages\.length > 0/);
    assert.match(src, /text-xs/);
    assert.doesNotMatch(src, /logbook-chat-ai-notice[\s\S]{0,400}text-\[9px\]/);
  });
  it("l’avis reste sous le cadre à hauteur fixe et ne comprime pas la liste", () => {
    const formEnd = src.indexOf("</form>");
    const boxEnd = src.indexOf("</div>", formEnd);
    const noticeAt = src.indexOf('data-testid="logbook-chat-ai-notice"');
    assert.ok(formEnd > 0 && noticeAt > boxEnd, "l’avis suit la fermeture du cadre sim-box-chat");
    assert.match(src, /<div data-tour="logbook" className="min-w-0">\s*<div data-testid="logbook-chat" className="sim-box-chat/);
  });
  it("lives in the left sidebar, in both views, and says whether exchanges are logged", () => {
    assert.match(sidebar, /<LogbookChat messages=\{chat\.messages\}/);
    assert.match(sidebar, /\{!drawingHidesBerry && chat \? \(/, "any view, not once a drawn point hides Berry");
    assert.match(src, /hasAdminSecret\(\)/);
    assert.match(src, /logbookChatSaved|logbookChatUnsaved/);
  });

  it("the hook posts one question at a time to /logbook/chat with the admin header and the client facts", () => {
    assert.match(hook, /postLogbookChat\(\{/);
    assert.match(hook, /url:\s*`\$\{API_URL\}\/logbook\/chat`/);
    assert.match(hook, /\.\.\.adminHeaders\(\)/);
    assert.match(hook, /inFlight\.current/);
    assert.match(hook, /contextFn\(\)/);
    assert.match(hook, /source: body\.source \|\| body\.engine \|\| null/);
    assert.match(hook, /reason/);
    assert.doesNotMatch(hook, /Nemotron|Tavily|Nebius/i);
    assert.match(hook, /signal:\s*controller\.signal/);
    assert.match(hook, /requestController\.current\?\.abort\(\)/);
    assert.match(hook, /err\?\.code === "aborted"/);
  });

  it("does not update hook state after unmount while an aborted request settles", () => {
    assert.match(hook, /mounted\.current = false;\s*requestController\.current\?\.abort\(\)/);
    assert.match(hook, /if \(mounted\.current\) setMessages\(\(prev\) => \[\.\.\.prev, reply\]/);
    assert.match(hook, /if \(mounted\.current\) setError\(/);
    assert.match(hook, /if \(mounted\.current\) setPending\(false\)/);
  });

  it("keeps the translator callable when recording the question timestamp", () => {
    assert.match(hook, /const \{ t: tr \} = useLang\(\)/);
    assert.match(hook, /setError\(tr\(chatErrorKey\(err\?\.code\)\)\)/);
    assert.doesNotMatch(hook, /const t\s*=/);
  });

  it("shows the cascade source under the answer and does not fetch on render", () => {
    assert.match(src, /testId="chat-source"/);
    assert.match(src, /LlmSourceBadge/);
    assert.doesNotMatch(src, /\/logbook\/chat/);
    const effects = src.match(/useEffect\(/g) || [];
    assert.equal(effects.length, 1, "only the scroll-to-bottom effect");
    assert.match(src, /el\.scrollTop = el\.scrollHeight/);
  });

  it("affiche les liens Tavily sous la réponse quand le serveur en envoie", () => {
    assert.match(hook, /webSources/);
    assert.match(src, /logbook-chat-web-sources/);
    assert.match(src, /logbookWebSourcesTitle/);
  });

  it("cadre de réponse sous la question", () => {
    assert.match(src, /data-testid="logbook-chat-reply"/);
    const replyAt = src.indexOf('data-testid="logbook-chat-reply"');
    const listAt = src.indexOf('data-testid="logbook-chat-list"');
    const inputAt = src.indexOf('data-testid="logbook-chat-input"');
    assert.ok(replyAt > 0 && listAt > replyAt, "la liste est dans le cadre");
    assert.ok(inputAt > listAt, "le champ reste sous le cadre");
    assert.doesNotMatch(src, /logbookChatHint/);
    assert.doesNotMatch(src, /logbook-chat-reason/);
    assert.doesNotMatch(src, /logbookChatReason/);
    assert.doesNotMatch(src, /Raisonnement|Reasoning/);
  });
});

describe("LogbookChat example questions (one click, three real paths)", () => {
  const en = readFileSync(join(here, "..", "i18n", "en.js"), "utf8");
  const fr = readFileSync(join(here, "..", "i18n", "fr.js"), "utf8");
  const keys = [
    "logbookExamplesTitle",
    "logbookExampleDeepQ", "logbookExampleDeepLabel", "logbookExampleDeepHint",
    "logbookExampleWebQ", "logbookExampleWebLabel", "logbookExampleWebHint",
    "logbookExampleFastQ", "logbookExampleFastLabel", "logbookExampleFastHint",
  ];
  const val = (file, key) => (file.match(new RegExp(`\\n\\s*${key}:\\s*"([^"]+)"`)) || [])[1];

  it("three buttons, deep / web / fast, each with a test id", () => {
    for (const id of ["deep", "web", "fast"]) {
      assert.match(src, new RegExp(`id: "${id}"`));
    }
    assert.match(src, /data-testid=\{`logbook-chat-example-\$\{ex\.id\}`\}/);
    assert.match(src, /data-testid="logbook-chat-examples"/);
    assert.match(src, /title=\{`\$\{t\(ex\.q\)\} — \$\{t\(ex\.hint\)\}`\}/, "full question in the tooltip");
    assert.match(src, /h-5 whitespace-nowrap rounded-full/, "small chips: the reply and the input keep their room");
    // Une seule rangée : sur deux lignes (281 px en FR), le cadre de réponse tombe sous 40 px (ra6).
    assert.match(src, /data-testid="logbook-chat-examples"\s+className="[^"]*\bflex-nowrap\b[^"]*\boverflow-x-auto\b/);
    assert.doesNotMatch(src, /data-testid="logbook-chat-examples"\s+className="[^"]*\bflex-wrap\b/);
  });

  it("a click sends the translated question through the existing onAsk flow, no new endpoint", () => {
    assert.match(src, /const askExample = \(key\) =>/);
    assert.match(src, /onAsk\?\.\(q\)/);
    assert.match(src, /onClick=\{\(\) => askExample\(ex\.q\)\}/);
    assert.match(src, /disabled=\{pending\}/);
    assert.doesNotMatch(src, /fetch\(/);
  });

  it("every example key exists in FR and EN, and the texts differ", () => {
    for (const key of keys) {
      assert.ok(val(en, key), `en.${key}`);
      assert.ok(val(fr, key), `fr.${key}`);
      assert.notEqual(val(en, key), val(fr, key), key);
    }
  });

  it("the wording matches the server routing (why/how → Ultra, short fact → Lightning)", () => {
    assert.match(val(en, "logbookExampleDeepQ"), /^Why\b/);
    assert.match(val(fr, "logbookExampleDeepQ"), /^Pourquoi\b/);
    assert.match(val(en, "logbookExampleWebQ"), /^How\b/);
    assert.match(val(fr, "logbookExampleWebQ"), /^Comment\b/);
    for (const file of [en, fr]) {
      const fast = val(file, "logbookExampleFastQ");
      assert.ok(fast.length < 80, "FAST_QUESTION_MAX");
      assert.doesNotMatch(fast, /why|how|pourquoi|comment|route|leg|course/i);
      assert.match(val(file, "logbookExampleFastHint"), /Lightning/);
      assert.match(val(file, "logbookExampleDeepHint"), /Ultra/);
      assert.match(val(file, "logbookExampleWebHint"), /Tavily/);
      assert.match(val(file, "logbookExampleDeepLabel"), /Ultra$/);
      assert.match(val(file, "logbookExampleWebLabel"), /Tavily$/);
      assert.match(val(file, "logbookExampleFastLabel"), /Lightning$/);
    }
  });
});

describe("R44 : accessibilité du chat et de la notice AI Act", () => {
  it("la notice est une région live (role=status, aria-live=polite) autour du texte seul", () => {
    assert.match(src, /<p role="status" aria-live="polite" data-testid="logbook-chat-ai-notice-text">\{t\("aiActChatNotice"\)\}<\/p>/);
    assert.doesNotMatch(src, /role="note"/);
  });
  it("champ et bouton Envoyer ont un nom accessible i18n ; le focus revient au champ", () => {
    assert.match(src, /aria-label=\{t\("logbookChatInputLabel"\)\}/);
    assert.match(src, /aria-label=\{t\("logbookChatSend"\)\}/);
    assert.match(src, /ref=\{inputRef\}/);
    assert.match(src, /dismissAiNotice = useCallback\(\(\) => \{[\s\S]{0,200}inputRef\.current\?\.focus\(\)/);
  });
  it("libellés FR et EN présents et distincts", async () => {
    const fr = (await import("../i18n/fr.js")).default;
    const en = (await import("../i18n/en.js")).default;
    assert.ok(fr.logbookChatInputLabel && en.logbookChatInputLabel);
    assert.notEqual(fr.logbookChatInputLabel, en.logbookChatInputLabel);
  });
});
