import { readFileSync } from "node:fs";
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_LANG,
  LEGACY_STORAGE_KEY,
  readStoredLang,
  resolveLang,
  STORAGE_KEY,
} from "./langStorage.js";

const html = readFileSync(new URL("../../index.html", import.meta.url), "utf8");

function mem(initial = {}) {
  const data = { ...initial };
  return {
    data,
    getItem(key) {
      return Object.prototype.hasOwnProperty.call(data, key) ? data[key] : null;
    },
    setItem(key, value) {
      data[key] = String(value);
    },
    removeItem(key) {
      delete data[key];
    },
  };
}

describe("default language", () => {
  it("opens in English when nothing is stored", () => {
    const storage = mem();
    assert.equal(readStoredLang(storage), DEFAULT_LANG);
    assert.equal(DEFAULT_LANG, "en");
    assert.equal(resolveLang(undefined), "en");
    assert.equal(resolveLang(""), "en");
    assert.equal(resolveLang("de"), "en");
    assert.equal(storage.data[STORAGE_KEY], undefined);
  });

  it("respects a French choice already stored", () => {
    const storage = mem({ [STORAGE_KEY]: "fr" });
    assert.equal(readStoredLang(storage), "fr");
    assert.equal(storage.data[LEGACY_STORAGE_KEY], undefined);
  });

  it("respects an English choice already stored", () => {
    assert.equal(readStoredLang(mem({ [STORAGE_KEY]: "en" })), "en");
    assert.equal(resolveLang("en"), "en");
  });

  it("migrates a French choice from the previous key into the current one", () => {
    const storage = mem({ [LEGACY_STORAGE_KEY]: "fr" });
    assert.equal(readStoredLang(storage), "fr");
    assert.equal(storage.data[STORAGE_KEY], "fr");
    assert.equal(storage.data[LEGACY_STORAGE_KEY], undefined);
    assert.equal(readStoredLang(storage), "fr");
  });

  it("keeps the current key when both keys are present", () => {
    const storage = mem({ [STORAGE_KEY]: "fr", [LEGACY_STORAGE_KEY]: "en" });
    assert.equal(readStoredLang(storage), "fr");
    assert.equal(storage.data[LEGACY_STORAGE_KEY], "en");
  });

  it("the first page markup uses the same opening language and both keys", () => {
    assert.match(html, new RegExp(`<html lang="${DEFAULT_LANG}">`));
    assert.match(html, new RegExp(STORAGE_KEY));
    assert.match(html, new RegExp(LEGACY_STORAGE_KEY));
  });
});
