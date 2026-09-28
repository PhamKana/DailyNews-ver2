import test from "node:test";
import assert from "node:assert/strict";
import { callLLM } from "../src/llm.js";
import worker from "../src/index.js";

test("missing keys make no external request", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", () => { throw new Error("unexpected request"); });
  assert.equal((await callLLM({}, "hello")).ok, false);
  assert.equal(fetch.mock.callCount(), 0);
});

test("configured Gemini endpoint, model and temperature are used", async (t) => {
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(url, "https://example.test/custom");
    assert.equal(options.headers["x-goog-api-key"], "fake");
    assert.equal(JSON.parse(options.body).generationConfig.temperature, 0);
    return Response.json({ candidates: [{ content: { parts: [{ text: "ok" }] } }] });
  });
  const result = await callLLM({ GEMINI_API_KEY: "fake", GEMINI_MODEL: "custom",
    GEMINI_ENDPOINT: "https://example.test/{model}", LLM_TEMPERATURE: "0" }, "hello");
  assert.deepEqual(result, { ok: true, text: "ok" });
});

test("auto falls back to configured Anthropic-compatible API", async (t) => {
  let calls = 0;
  t.mock.method(globalThis, "fetch", async (url, options) => {
    if (++calls === 1) return new Response("limited", { status: 429 });
    assert.equal(url, "https://example.test/messages");
    assert.equal(options.headers["x-api-key"], "fake-d");
    assert.equal(JSON.parse(options.body).model, "custom-d");
    return Response.json({ content: [{ type: "text", text: "fallback" }] });
  });
  const result = await callLLM({ LLM_ENGINE: "auto", GEMINI_FALLBACK_MODELS: "", GEMINI_API_KEY: "fake-g", DEEPSEEK_API_KEY: "fake-d",
    DEEPSEEK_ENDPOINT: "https://example.test/messages", DEEPSEEK_MODEL: "custom-d" }, "hello");
  assert.equal(result.text, "fallback");
  assert.equal(calls, 2);
});

test("forced engine does not call another provider", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", () => { throw new Error("unexpected request"); });
  assert.equal((await callLLM({ LLM_ENGINE: "deepseek", GEMINI_API_KEY: "fake" }, "hello")).ok, false);
  assert.equal(fetch.mock.callCount(), 0);
});

test("invalid engine and failed API return safe errors", async (t) => {
  assert.equal((await callLLM({ LLM_ENGINE: "typo" }, "hello")).ok, false);
  t.mock.method(globalThis, "fetch", async () => new Response("SECRET", { status: 500 }));
  const result = await callLLM({ GEMINI_API_KEY: "SECRET" }, "hello");
  assert.equal(result.ok, false);
  assert.ok(!result.error.includes("SECRET"));
});

test("webhook imports and handles health requests", async () => {
  const result = await worker.fetch(new Request("https://example.test"), {}, {});
  assert.equal(result.status, 200);
});


test("default never falls back to paid DeepSeek", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () => new Response("limited", { status: 429 }));
  const result = await callLLM({ GEMINI_API_KEY: "fake-g", DEEPSEEK_API_KEY: "fake-d" }, "hello");
  assert.equal(result.ok, false);
  assert.equal(fetch.mock.callCount(), 3);
  assert.ok(fetch.mock.calls.every((call) => call.arguments[0].includes("generativelanguage.googleapis.com")));
});


for (const failures of [0, 1, 2]) {
  test(`Gemini fallback order stops after ${failures} failures`, async (t) => {
    const models = ["gemini-3-flash-preview", "gemini-2.5-flash", "gemini-2.5-flash-lite"];
    let calls = 0;
    t.mock.method(globalThis, "fetch", async (url) => {
      assert.ok(url.includes(`/${models[calls]}:generateContent`));
      if (calls++ < failures) return new Response("unavailable", { status: 503 });
      return Response.json({ candidates: [{ content: { parts: [{ text: "ok" }] } }] });
    });
    assert.equal((await callLLM({ GEMINI_API_KEY: "fake" }, "hello")).text, "ok");
    assert.equal(calls, failures + 1);
  });
}

test("custom fallback list is trimmed and deduplicated", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url) => {
    calls.push(url);
    return new Response("unavailable", { status: 404 });
  });
  await callLLM({ GEMINI_API_KEY: "fake", GEMINI_MODEL: "custom",
    GEMINI_FALLBACK_MODELS: " backup,custom,backup,last " }, "hello");
  assert.deepEqual(calls.map((url) => url.split("/models/")[1].split(":")[0]), ["custom", "backup", "last"]);
});
