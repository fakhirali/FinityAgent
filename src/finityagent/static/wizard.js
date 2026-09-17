/* Wizard: prefill base URL + model when preset changes */
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

const preset = document.getElementById("preset");
const baseUrl = document.getElementById("base_url");
const model = document.getElementById("model");

function applyPreset() {
  const p = PRESETS[preset.value] || PRESETS.custom;
  if (!baseUrl.value.trim() || baseUrl.dataset.prefilled === "1") {
    baseUrl.value = p.base_url;
    baseUrl.dataset.prefilled = "1";
  }
  if (!model.value.trim() || model.dataset.prefilled === "1") {
    model.value = p.default_model;
    model.dataset.prefilled = "1";
  }
}
preset.addEventListener("change", () => {
  baseUrl.dataset.prefilled = "";
  model.dataset.prefilled = "";
  applyPreset();
});
applyPreset();
