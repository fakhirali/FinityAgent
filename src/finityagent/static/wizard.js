// Wizard: preset prefill + model dropdown from /v1/models
const PRESETS = {
  "opencode-go": {
    base_url: "https://opencode.ai/zen/go/v1",
    default_model: "kimi-k3",
  },
  openai: {
    base_url: "https://api.openai.com/v1",
    default_model: "gpt-4.1",
  },
  custom: { base_url: "", default_model: "" },
};

const $ = (id) => document.getElementById(id);
const preset = $("preset");
const baseUrl = $("base_url");
const apiKey = $("api_key");
const modelSelect = $("model");

async function loadModels() {
  const base = baseUrl.value.trim();
  if (!base) return;
  const key = apiKey.value.trim();
  const url = `/api/wizard-models?base_url=${encodeURIComponent(base)}` +
    (key ? `&api_key=${encodeURIComponent(key)}` : "");
  const data = await fetch(url).then((r) => r.json()).catch(() => ({}));
  const models = data.models || [];
  modelSelect.innerHTML = "";
  if (!models.length) models.push("(no models found — check base URL/key)");
  for (const m of models) {
    const opt = document.createElement("option");
    opt.value = m;
    opt.textContent = m;
    modelSelect.appendChild(opt);
  }
  const def = PRESETS[preset.value]?.default_model;
  if (def && models.includes(def)) modelSelect.value = def;
}

function applyPreset() {
  const p = PRESETS[preset.value] || PRESETS.custom;
  if (!baseUrl.value.trim()) baseUrl.value = p.base_url;
  loadModels();
}

preset.addEventListener("change", applyPreset);
baseUrl.addEventListener("change", loadModels);
apiKey.addEventListener("change", loadModels);
applyPreset();
