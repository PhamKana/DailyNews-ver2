import defaults from "../../config/api.json" with { type: "json" };

// Both runtimes use config/api.json; deployed secrets stay in Worker bindings.
export async function callLLM(env, prompt) {
  const engine = env.LLM_ENGINE || defaults.engine;
  if (!["auto", "gemini", "deepseek"].includes(engine)) {
    return { ok: false, error: "LLM_ENGINE phải là auto, gemini hoặc deepseek." };
  }
  const engines = engine === "auto"
    ? ["gemini", "deepseek"].filter((name) => env[`${name.toUpperCase()}_API_KEY`])
    : [engine];
  if (!engines.length) {
    return { ok: false, error: "Worker thiếu GEMINI_API_KEY hoặc DEEPSEEK_API_KEY." };
  }
  const fallbackModels = env.GEMINI_FALLBACK_MODELS !== undefined
    ? env.GEMINI_FALLBACK_MODELS.split(",").map((m) => m.trim()).filter(Boolean)
    : env.GEMINI_MODEL ? [] : (defaults.providers.gemini.fallback_models || []);
  const attempts = engines.flatMap((name) => {
    const primary = env[`${name.toUpperCase()}_MODEL`] || defaults.providers[name].model;
    const models = name === "gemini" ? [primary, ...fallbackModels] : [primary];
    return [...new Set(models)].map((model) => ({ name, model }));
  });
  for (const { name, model } of attempts) {
    const prefix = name.toUpperCase();
    const key = env[`${prefix}_API_KEY`];
    if (!key) continue;
    const endpoint = env[`${prefix}_ENDPOINT`] || defaults.providers[name].endpoint;
    const temperature = Number(env.LLM_TEMPERATURE || defaults.temperature);
    let url = endpoint.replace("{model}", encodeURIComponent(model));
    const headers = { "Content-Type": "application/json" };
    let payload;
    if (name === "gemini") {
      headers["x-goog-api-key"] = key;
      payload = {
        contents: [{ role: "user", parts: [{ text: prompt }] }],
        generationConfig: { temperature },
      };
    } else {
      headers["x-api-key"] = key;
      headers["anthropic-version"] = "2023-06-01";
      payload = {
        model, temperature, max_tokens: defaults.max_tokens,
        messages: [{ role: "user", content: prompt }],
      };
    }
    try {
      const response = await fetch(url, {
        method: "POST", headers, body: JSON.stringify(payload),
        signal: AbortSignal.timeout(defaults.timeout_seconds * 1000),
      });
      if (!response.ok) continue;
      const data = await response.json();
      const text = name === "gemini"
        ? (data.candidates?.[0]?.content?.parts || [])
          .filter((part) => !part.thought).map((part) => part.text || "").join("")
        : (data.content || []).filter((part) => part.type === "text")
          .map((part) => part.text || "").join("");
      if (text.trim()) {
        console.info(`LLM model thành công: ${model}`);
        return { ok: true, text };
      }
    } catch {
      // Try the next configured provider; never echo credentials or response bodies.
    }
  }
  return { ok: false, error: "Không gọi được AI. Kiểm tra API key, model, endpoint và hạn mức của nhà cung cấp." };
}
