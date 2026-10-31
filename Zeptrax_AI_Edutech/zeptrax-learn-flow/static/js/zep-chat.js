/*
 * Zep AI chat widget - embeddable on any site with one line:
 *   <script src="https://zeptrax-ai-edutec.vercel.app/static/js/zep-chat.js" defer></script>
 * Talks to the Edutech AI backend (same origin as this script unless data-api-base is set).
 * Optional: data-hide-selector="<css selector>" hides an existing chat launcher on the host page.
 */
(function () {
  if (window.__zepChatLoaded) return;
  window.__zepChatLoaded = true;

  var script = document.currentScript;
  var API_BASE = (script && script.getAttribute("data-api-base")) ||
    (script && script.src ? new URL(script.src).origin : "https://zeptrax-ai-edutec.vercel.app");
  var HIDE_SELECTOR = script && script.getAttribute("data-hide-selector");
  var ENDPOINT = API_BASE + "/api/apps/6a58811b763e4b993e2b1bed/integration-endpoints/Core/InvokeLLM";
  var WHATSAPP = "918368544821";
  var GREETING = "Hi am Zep AI , How can i help u ?";
  var MAX_HISTORY = 12;
  var REQUEST_TIMEOUT_MS = 45000;

  var QUICK_PROMPTS = [
    { label: "Enrollment", prompt: "I want to enroll in a course. Can you help me with the enrollment process and available AI programs?" },
    { label: "Queries", prompt: "I have some questions about ZeptraAI programs, certifications, and pricing." },
    { label: "Partnership", prompt: "I'm interested in a partnership with ZeptraAI. What options are available?" }
  ];

  var ICONS = {
    bot: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/></svg>',
    close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>',
    phone: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/></svg>',
    mic: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" x2="12" y1="19" y2="22"/></svg>',
    send: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/></svg>',
    sparkles: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z"/></svg>'
  };

  var CSS = [
    ":host{all:initial}",
    "*{box-sizing:border-box;font-family:Inter,ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,Arial,sans-serif}",
    "svg{width:100%;height:100%;display:block}",
    ".fab{position:fixed;bottom:24px;right:24px;z-index:2147483646;width:56px;height:56px;border-radius:9999px;border:0;cursor:pointer;color:#fff;",
    "background:linear-gradient(135deg,#3b82f6,#06b6d4);box-shadow:0 0 24px rgba(6,182,212,.45),0 10px 25px rgba(0,0,0,.35);display:flex;align-items:center;justify-content:center;transition:transform .15s}",
    ".fab:hover{transform:scale(1.05)}.fab .i{width:24px;height:24px}",
    ".panel{position:fixed;bottom:96px;right:24px;z-index:2147483647;width:384px;max-width:calc(100vw - 32px);height:500px;max-height:calc(100vh - 120px);",
    "background:#0f1626;color:#e5e7eb;border:1px solid #1f2a3d;border-radius:16px;box-shadow:0 25px 50px rgba(0,0,0,.5);display:flex;flex-direction:column;overflow:hidden;",
    "opacity:0;transform:translateY(20px) scale(.95);pointer-events:none;transition:opacity .18s,transform .18s}",
    ".panel.open{opacity:1;transform:none;pointer-events:auto}",
    ".head{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;border-bottom:1px solid #1f2a3d;background:rgba(30,41,59,.35)}",
    ".who{display:flex;align-items:center;gap:8px}",
    ".avatar{width:32px;height:32px;border-radius:9999px;background:linear-gradient(135deg,#3b82f6,#06b6d4);color:#fff;display:flex;align-items:center;justify-content:center}",
    ".avatar .i{width:16px;height:16px}",
    ".title{font-size:14px;font-weight:700;display:flex;align-items:center;gap:4px;margin:0;color:#f3f4f6}",
    ".title .i{width:12px;height:12px;color:#3b82f6}",
    ".sub{font-size:12px;color:#8b95a7;margin:2px 0 0}",
    ".wa{width:32px;height:32px;border-radius:9999px;background:rgba(34,197,94,.1);color:#4ade80;display:flex;align-items:center;justify-content:center;text-decoration:none}",
    ".wa:hover{background:rgba(34,197,94,.2)}.wa .i{width:16px;height:16px}",
    ".msgs{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:12px}",
    ".row{display:flex}.row.user{justify-content:flex-end}",
    ".bubble{max-width:85%;padding:9px 14px;border-radius:16px;font-size:14px;line-height:1.45;white-space:pre-wrap;word-wrap:break-word}",
    ".row.assistant .bubble{background:#1c2536;color:#e5e7eb;border-bottom-left-radius:6px}",
    ".row.user .bubble{background:#3b82f6;color:#fff;border-bottom-right-radius:6px}",
    ".typing{display:flex;gap:5px;padding:14px 16px}",
    ".typing span{width:8px;height:8px;border-radius:9999px;background:#8b95a7;animation:zb 1s infinite ease-in-out}",
    ".typing span:nth-child(2){animation-delay:.15s}.typing span:nth-child(3){animation-delay:.3s}",
    "@keyframes zb{0%,80%,100%{opacity:.35;transform:translateY(0)}40%{opacity:1;transform:translateY(-3px)}}",
    ".quick{display:flex;flex-wrap:wrap;gap:6px;padding:0 16px 10px}",
    ".chip{font-size:12px;padding:6px 10px;border-radius:9999px;border:1px solid #27324a;background:#141c2c;color:#cbd5e1;cursor:pointer}",
    ".chip:hover{border-color:#3b82f6;color:#fff}",
    ".bar{display:flex;align-items:center;gap:8px;padding:12px;border-top:1px solid #1f2a3d}",
    ".input{flex:1;min-width:0;height:44px;padding:0 16px;border-radius:9999px;border:1px solid #27324a;background:#141c2c;color:#f3f4f6;font-size:14px;outline:none}",
    ".input:focus{border-color:#3b82f6}.input::placeholder{color:#7b8698}",
    ".btn{width:44px;height:44px;flex:none;border-radius:9999px;border:0;cursor:pointer;display:flex;align-items:center;justify-content:center}",
    ".btn .i{width:18px;height:18px}",
    ".mic{background:#1c2536;color:#60a5fa}.mic.on{background:#ef4444;color:#fff;animation:zp 1.2s infinite}",
    "@keyframes zp{50%{box-shadow:0 0 0 6px rgba(239,68,68,.25)}}",
    ".send{background:#3b82f6;color:#fff}.send:disabled{opacity:.45;cursor:default}",
    "@media (max-width:480px){.panel{right:16px;bottom:88px}.fab{right:16px;bottom:16px}}"
  ].join("");

  function icon(name) {
    return '<span class="i">' + ICONS[name] + "</span>";
  }

  var host = document.createElement("div");
  host.id = "zep-ai-chat";
  var root = host.attachShadow({ mode: "open" });
  root.innerHTML =
    "<style>" + CSS + "</style>" +
    '<div class="panel" role="dialog" aria-label="Zep AI Voice Agent">' +
      '<div class="head"><div class="who"><div class="avatar">' + icon("bot") + "</div><div>" +
        '<p class="title">Zep AI Voice Agent ' + icon("sparkles") + "</p>" +
        '<p class="sub">Enrollment • Queries • Partnership</p></div></div>' +
        '<a class="wa" target="_blank" rel="noreferrer" href="https://wa.me/' + WHATSAPP + '" aria-label="Chat on WhatsApp">' + icon("phone") + "</a></div>" +
      '<div class="msgs"></div>' +
      '<div class="quick"></div>' +
      '<form class="bar"><input class="input" placeholder="Ask or use voice..." aria-label="Message" />' +
        '<button type="button" class="btn mic" aria-label="Voice input">' + icon("mic") + "</button>" +
        '<button type="submit" class="btn send" aria-label="Send">' + icon("send") + "</button></form>" +
    "</div>" +
    '<button class="fab" aria-label="Zep AI Voice Agent">' + icon("bot") + "</button>";

  var panel = root.querySelector(".panel");
  var msgsEl = root.querySelector(".msgs");
  var quickEl = root.querySelector(".quick");
  var form = root.querySelector(".bar");
  var input = root.querySelector(".input");
  var micBtn = root.querySelector(".mic");
  var sendBtn = root.querySelector(".send");
  var fab = root.querySelector(".fab");

  var messages = [{ role: "assistant", content: GREETING }];
  var loading = false;
  var isOpen = false;
  var recognition = null;

  function speak(text) {
    if (!("speechSynthesis" in window)) return;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
  }

  function render() {
    msgsEl.textContent = "";
    messages.forEach(function (m) {
      var row = document.createElement("div");
      row.className = "row " + m.role;
      var bubble = document.createElement("div");
      bubble.className = "bubble";
      bubble.textContent = m.content;
      row.appendChild(bubble);
      msgsEl.appendChild(row);
    });
    if (loading) {
      var row = document.createElement("div");
      row.className = "row assistant";
      row.innerHTML = '<div class="bubble typing"><span></span><span></span><span></span></div>';
      msgsEl.appendChild(row);
    }
    // Quick topics only until the visitor starts chatting
    quickEl.style.display = messages.length > 1 ? "none" : "flex";
    sendBtn.disabled = loading;
    msgsEl.scrollTop = msgsEl.scrollHeight;
  }

  QUICK_PROMPTS.forEach(function (q) {
    var chip = document.createElement("button");
    chip.type = "button";
    chip.className = "chip";
    chip.textContent = q.label;
    chip.addEventListener("click", function () { send(q.prompt); });
    quickEl.appendChild(chip);
  });

  function buildPrompt(history) {
    var convo = history.slice(-MAX_HISTORY).map(function (m) {
      return (m.role === "user" ? "User" : "Zep AI") + ": " + m.content;
    }).join("\n\n");
    return "You are Zep AI Voice Agent for Zeptrax AI (www.zeptraxai.com, WhatsApp: +91-8368544821). " +
      "Zeptrax AI provides AI, Cloud, Blockchain and Cybersecurity solutions for businesses, and runs " +
      "ZeptraAI Edutech, which offers AI programs that are all 4 months long. " +
      "Help with: 1) Course Enrollment 2) General Queries about services and programs 3) Partnership. " +
      "Be concise and friendly. Do not invent prices or details you don't know; " +
      "share WhatsApp +91-8368544821 for human contact.\n\n" + convo + "\n\nZep AI:";
  }

  function send(text) {
    var content = (text || "").trim();
    if (!content || loading) return;
    messages.push({ role: "user", content: content });
    input.value = "";
    loading = true;
    render();

    var controller = "AbortController" in window ? new AbortController() : null;
    var timer = setTimeout(function () { if (controller) controller.abort(); }, REQUEST_TIMEOUT_MS);

    fetch(ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt: buildPrompt(messages),
        response_json_schema: { type: "object", properties: { response: { type: "string" } } }
      }),
      signal: controller ? controller.signal : undefined
    })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (data) {
        var reply = (data && data.response) || "Could you rephrase?";
        messages.push({ role: "assistant", content: reply });
        speak(reply);
      })
      .catch(function () {
        messages.push({ role: "assistant", content: "Connection issue. Try again or WhatsApp +91-8368544821." });
      })
      .then(function () {
        clearTimeout(timer);
        loading = false;
        render();
        input.focus();
      });
  }

  function toggle() {
    isOpen = !isOpen;
    panel.classList.toggle("open", isOpen);
    fab.innerHTML = icon(isOpen ? "close" : "bot");
    if (isOpen) {
      speak(GREETING);
      setTimeout(function () { input.focus(); }, 50);
    } else if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
  }

  function toggleVoice() {
    if (recognition) {
      recognition.stop();
      return;
    }
    var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      alert("Voice input is not supported in your browser. Please try Chrome or Edge.");
      return;
    }
    recognition = new SR();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = "en-US";
    recognition.onstart = function () { micBtn.classList.add("on"); };
    recognition.onend = function () { micBtn.classList.remove("on"); recognition = null; };
    recognition.onresult = function (e) {
      var transcript = e.results[0][0].transcript;
      input.value = transcript;
      send(transcript);
    };
    recognition.start();
  }

  fab.addEventListener("click", toggle);
  micBtn.addEventListener("click", toggleVoice);
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    send(input.value);
  });

  render();

  if (HIDE_SELECTOR) {
    var hideStyle = document.createElement("style");
    hideStyle.textContent = HIDE_SELECTOR + "{display:none !important}";
    document.head.appendChild(hideStyle);
  }

  function mount() { document.body.appendChild(host); }
  if (document.body) mount();
  else document.addEventListener("DOMContentLoaded", mount);
})();
