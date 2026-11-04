import assert from "node:assert/strict";
import test from "node:test";
import { nextFilmWebContext, normalizeFilmWebSourceUrl, normalizeSourceUrl, publicFilmWebContext } from "./filmWebSources.js";
import { resolveServedFilm } from "../hooks/useReplay.js";
import fr from "../i18n/fr.js";
import en from "../i18n/en.js";

const CTX = {
  basis: "tavily",
  port: "Papeete",
  fetchedAt: "2026-10-29T07:40:00Z",
  sources: [
    { title: "Papeete — Noonsite", url: "https://www.noonsite.com/place/french-polynesia/papeete/", domain: "noonsite.com" },
    { title: "", url: "https://example.org/marina" },
    { title: "x", url: "javascript:alert(1)" },
  ],
};

test("publicFilmWebContext garde port, domaines et liens http(s)", () => {
  const out = publicFilmWebContext({ webContext: CTX });
  assert.equal(out.port, "Papeete");
  assert.deepEqual(out.sources.map((s) => s.domain), ["noonsite.com", "example.org"]);
  assert.equal(out.sources[1].title, "example.org");
});

test("publicFilmWebContext déduplique avant de limiter les sources affichées", () => {
  const duplicate = CTX.sources[0];
  const out = publicFilmWebContext({
    webContext: {
      ...CTX,
      sources: [duplicate, duplicate, ...CTX.sources.slice(1)],
    },
  });
  assert.deepEqual(out.sources.map((s) => s.url), [duplicate.url, CTX.sources[1].url]);
});

test("publicFilmWebContext : rien sans provenance Tavily réelle", () => {
  assert.equal(publicFilmWebContext(null), null);
  assert.equal(publicFilmWebContext({}), null);
  assert.equal(publicFilmWebContext({ webContext: { ...CTX, basis: "llm" } }), null);
  assert.equal(publicFilmWebContext({ webContext: { ...CTX, sources: [] } }), null);
  assert.equal(publicFilmWebContext({ webContext: { ...CTX, port: "" } }), null);
});

test("resolveServedFilm transmet la provenance Tavily (rédigé et brut)", () => {
  const written = resolveServedFilm({ hasWritten: true, source: "nemotron-super", webContext: CTX }, "written");
  assert.equal(written.webContext?.port, "Papeete");
  const raw = resolveServedFilm({ webContext: CTX }, "raw");
  assert.equal(raw.webContext?.port, "Papeete");
  const none = resolveServedFilm({ hasWritten: true, source: "nemotron-super" }, "written");
  assert.equal(none.webContext, null);
});

test("publicFilmWebContext dédoublonne les URL normalisées", () => {
  const out = publicFilmWebContext({
    webContext: {
      basis: "tavily",
      port: "Ajaccio",
      sources: [
        { title: "A", url: "https://WWW.Example.COM/path/" },
        { title: "B", url: "https://example.com/path" },
        { title: "C", url: "https://other.org/" },
      ],
    },
  });
  assert.equal(out.sources.length, 2);
  assert.deepEqual(out.sources.map((s) => s.domain), ["example.com", "other.org"]);
});

test("normalisation garde la requête et le port", () => {
  assert.equal(normalizeFilmWebSourceUrl("https://WWW.Example.COM:8443/path/?q=1#x"), "https://example.com:8443/path?q=1");
  assert.notEqual(normalizeFilmWebSourceUrl("https://example.com/path?q=1"), "https://example.com/path?q=2");
});

test("publicFilmWebContext rejette https:// sans hôte", () => {
  const out = publicFilmWebContext({
    webContext: {
      basis: "tavily",
      port: "Ajaccio",
      sources: [{ title: "x", url: "https://", domain: "x.org" }],
    },
  });
  assert.equal(out, null);
});

test("libellé du film : Tavily nommé en FR et EN", () => {
  assert.match(fr.filmWebSourcesTitle, /Tavily/);
  assert.match(en.filmWebSourcesTitle, /Tavily/);
  assert.match(fr.filmWebSourcesTitle, /\{port\}/);
  assert.match(en.filmWebSourcesTitle, /\{port\}/);
});

test("R45 : publicFilmWebContext dédoublonne par URL normalisée (www, casse, / final, fragment)", () => {
  const out = publicFilmWebContext({
    webContext: {
      basis: "tavily",
      port: "Papeete",
      sources: [
        { url: "https://www.noonsite.com/place/papeete/" },
        { url: "https://NOONSITE.com/place/papeete#top" },
        { url: "https://www.noonsite.com/place/papeete/" },
        { url: "https://example.org/a" },
        { url: "https://example.org/b" },
        { url: "https://example.org/c" },
      ],
    },
  });
  const urls = out.sources.map((s) => s.url);
  assert.equal(new Set(urls).size, urls.length, "aucune clé React en double");
  assert.deepEqual(urls, ["https://www.noonsite.com/place/papeete/", "https://example.org/a", "https://example.org/b"]);
});

test("R45 : normalizeSourceUrl garde la requête, ignore le fragment", () => {
  assert.equal(normalizeSourceUrl("https://www.A.com/x/?q=1#f"), "https://a.com/x?q=1");
  assert.notEqual(normalizeSourceUrl("https://a.com/x?q=1"), normalizeSourceUrl("https://a.com/x?q=2"));
});

test("transition film A (Tavily) → film B (sans webContext) : le contexte web est effacé", () => {
  const a = resolveServedFilm({
    status: "ready", style: "written", hasWritten: true, source: "nemotron-super",
    chapters: [{ text: "A" }],
    webContext: { basis: "tavily", port: "Papeete", sources: [{ url: "https://tahiti.example/news", title: "News" }] },
  }, "written");
  const b = resolveServedFilm({
    status: "ready", style: "written", hasWritten: true, source: "nemotron-super", chapters: [{ text: "B" }],
  }, "written");
  const afterA = nextFilmWebContext(null, a);
  assert.equal(afterA?.port, "Papeete");
  assert.equal(nextFilmWebContext(afterA, b), null);
  assert.equal(nextFilmWebContext(afterA, a)?.port, "Papeete");
});

test("normalizeSourceUrl : « / » racine n'est qu'une clé de dédoublonnage, le lien affiché reste intact", () => {
  assert.equal(normalizeSourceUrl("https://www.Example.com/"), "https://example.com");
  assert.equal(normalizeSourceUrl("https://example.com/"), normalizeSourceUrl("https://example.com"));
  const ctx = publicFilmWebContext({
    webContext: { basis: "tavily", port: "Nouméa", sources: [
      { url: "https://example.com/" }, { url: "https://example.com" }, { url: "https://example.com/a/" },
    ] },
  });
  assert.deepEqual(ctx.sources.map((s) => s.url), ["https://example.com/", "https://example.com/a/"]);
});
