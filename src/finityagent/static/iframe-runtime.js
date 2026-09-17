/* Injected into every agent HTML frame. Bridges data-send elements back to
   the chat and auto-resizes the frame. */
(function () {
  "use strict";

  function send(payload) {
    try {
      parent.postMessage({ type: "finity:send", payload: payload }, "*");
    } catch (e) { /* opaque origin restrictions */ }
  }

  function init() {
    document.querySelectorAll("form[data-send]").forEach(function (form) {
      form.addEventListener("submit", function (ev) {
        ev.preventDefault();
        var payload = {};
        new FormData(form).forEach(function (value, key) {
          payload[key] = value;
        });
        send(payload);
      });
    });

    document.querySelectorAll("button[data-send]").forEach(function (btn) {
      btn.addEventListener("click", function (ev) {
        ev.preventDefault();
        var payload = {};
        var raw = btn.getAttribute("data-send");
        if (raw) {
          try { payload = JSON.parse(raw); }
          catch (e) { payload = { value: raw }; }
        }
        send(payload);
      });
    });

    reportHeight();
  }

  function reportHeight() {
    try {
      parent.postMessage({
        type: "finity:resize",
        fid: window.frameElement ? window.frameElement.dataset.fid : null,
        height: document.documentElement.scrollHeight,
      }, "*");
    } catch (e) { /* ignore */ }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.addEventListener("load", reportHeight);
  window.addEventListener("resize", reportHeight);
})();
