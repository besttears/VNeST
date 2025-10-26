(function () {
  const $ = (s) => document.querySelector(s);
  const $all = (s) => Array.from(document.querySelectorAll(s));
  const hide = (el) => el && el.classList.add("hidden");
  const show = (el) => el && el.classList.remove("hidden");

  // detect preview mode from URL (?preview=1)
  const params = new URLSearchParams(location.search);
  const isPreview = params.get("preview") === "1";
  if (isPreview) { const b = $("#preview-banner"); if (b) b.style.display = "block"; }

  const token = $("#btn-start")?.dataset.token || null;

  // ---------------- Azure Speech (TTS & ASR) ----------------
  let ttsEnabled = false;
  let azureReady = false;
  let speechConfig = null;
  let audioConfig = null;
  let speechSynth = null;

  async function initAzureSpeech() {
    if (!window.SPEECH_ENABLED || !window.SPEECH_REGION) return false;
    try {
      // get a short-lived token from server
      const res = await fetch("/api/speech/token");
      const data = await res.json();
      if (!data.token || !data.region) return false;

      const sdk = window.SpeechSDK;
      speechConfig = sdk.SpeechConfig.fromAuthorizationToken(data.token, data.region);
      if (window.SPEECH_VOICE) speechConfig.speechSynthesisVoiceName = window.SPEECH_VOICE;
      audioConfig = sdk.AudioConfig.fromDefaultMicrophoneInput();
      speechSynth = new sdk.SpeechSynthesizer(speechConfig);
      azureReady = true;
      return true;
    } catch {
      return false;
    }
  }

  function speak(text) {
    if (!ttsEnabled || !text) return;
    // Prefer Azure; fallback to browser SpeechSynthesis if Azure not ready
    if (azureReady && speechSynth) {
      speechSynth.speakTextAsync(text, () => {}, () => {});
    } else if (window.speechSynthesis) {
      const u = new SpeechSynthesisUtterance(text);
      const ar = speechSynthesis.getVoices().find(v => /ar/i.test(v.lang));
      if (ar) u.voice = ar;
      speechSynthesis.speak(u);
    }
  }

  async function asrOnceInto(inputSelector) {
    const input = document.querySelector(inputSelector);
    if (!input) return;
    // Prefer Azure Speech Recognizer
    if (azureReady && window.SpeechSDK) {
      const sdk = window.SpeechSDK;
      const recognizer = new sdk.SpeechRecognizer(speechConfig, audioConfig);
      return new Promise((resolve) => {
        recognizer.recognizeOnceAsync(result => {
          if (result && result.text) input.value = result.text.trim();
          recognizer.close(); resolve();
        }, err => { recognizer.close(); resolve(); });
      });
    }
    // Fallback to browser Web Speech API
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { alert("الإملاء الصوتي غير مدعوم في هذا المتصفح."); return; }
    const rec = new SR(); rec.lang = "ar-SA"; rec.interimResults = false; rec.maxAlternatives = 1;
    return new Promise((resolve) => {
      rec.onresult = (e) => { input.value = (e.results[0][0].transcript || "").trim(); resolve(); };
      rec.onerror = () => resolve(); rec.start();
    });
  }

  $("#btn-tts-toggle")?.addEventListener("click", async () => {
    if (!ttsEnabled) { await initAzureSpeech(); }
    ttsEnabled = !ttsEnabled;
    $("#btn-tts-toggle").textContent = ttsEnabled ? "🔊 إيقاف القراءة الآلية" : "🔊 تشغيل القراءة الآلية";
    if (ttsEnabled) speak("تم تشغيل القراءة الآلية. اضغط ابدأ لبدء التمرين.");
  });

  $all(".mic").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!azureReady && window.SPEECH_ENABLED) await initAzureSpeech();
      await asrOnceInto(btn.dataset.target);
    });
  });

  $("#btn-tts-read")?.addEventListener("click", () => {
    const s1 = $("#sent1-text")?.value || "";
    const s2 = $("#sent2-text")?.value || "";
    const text = [s1, s2].filter(Boolean).join(" . ");
    if (text) speak(text);
  });

  // Speak per step
  function stepTTS(id) {
    const verb = $(".verb")?.textContent || "أكل";
    if (id === "#step-verb") speak(`من الفاعل الذي يقوم بالفعل ${verb} ؟`);
    if (id === "#step-object") speak(`ماذا يمكن للفاعل أن ${verb} ؟`);
    if (id === "#step-place") speak("أين يحدث الفعل؟");
    if (id === "#step-dnd") speak("رتب الكلمات إلى جملتين صحيحتين.");
    if (id === "#step-typing") speak("اكتب الجملتين كاملة.");
    if (id === "#step-yn") speak($("#yn-stimulus")?.textContent || "");
    if (id === "#step-sem") speak($("#sem-stimulus")?.textContent || "");
  }

  // ---------------- App flow ----------------
  $("#btn-start")?.addEventListener("click", async () => {
    const form = new FormData();
    form.append("client_name", $("#client-name")?.value || "عميل");
    if (token) { try { await fetch(`/api/${token}/start`, { method: "POST", body: form }); } catch {} }
    hide($("#client-start")); show($("#step-verb")); stepTTS("#step-verb");
  });

  // Navigation between steps
  $all(".btn[data-next]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const current = btn.closest(".step"); const next = btn.getAttribute("data-next");
      hide(current); show($(next));
      if (next === "#step-object") {
        $("#subj-preview").textContent = $("#answer-subject").value || "—";
        $("#bubble-subject").textContent = $("#answer-subject").value || "—";
      }
      if (next === "#step-place") {
        const s = $("#answer-subject").value || "—";
        const o = $("#answer-object").value || "—";
        $("#subj2").textContent = s; $("#obj2").textContent = o;
        $("#bubble-subject2").textContent = s; $("#bubble-object2").textContent = o;
      }
      if (next === "#step-dnd") seedDND();
      stepTTS(next);
    });
  });

  // DnD seed
  function seedDND() {
    const bank = $("#bank"); bank.innerHTML = "";
    const pieces = [
      { text: $(".verb").textContent, role: "verb" },
      { text: $("#answer-subject").value || "—", role: "subject" },
      { text: $("#answer-object").value || "—", role: "object" },
      { text: $("#answer-place").value || "—", role: "place" },
      { text: $(".verb").textContent, role: "verb" },
      { text: "نورة", role: "subject" },
      { text: "كبسة", role: "object" },
      { text: "البيت", role: "place" }
    ];
    pieces.forEach((p, i) => {
      const span = document.createElement("span");
      span.className = "bubble draggable"; span.textContent = p.text;
      span.draggable = true; span.dataset.role = p.role; span.id = "token-" + i;
      bank.appendChild(span);
    });
    setupDragDrop();
  }

  function setupDragDrop() {
    $all(".draggable").forEach((el) => {
      el.addEventListener("dragstart", (ev) => ev.dataTransfer.setData("text/plain", ev.target.id));
    });
    $all(".dropzone").forEach((zone) => {
      zone.addEventListener("dragover", (ev) => ev.preventDefault());
      zone.addEventListener("drop", (ev) => {
        ev.preventDefault();
        const id = ev.dataTransfer.getData("text/plain");
        const el = document.getElementById(id); if (el) zone.appendChild(el);
      });
    });
  }

  // Order check
  $("#btn-check-order")?.addEventListener("click", () => {
    const evalZone = (zone) => {
      const roles = Array.from(zone.querySelectorAll(".draggable")).map(n => n.dataset.role);
      const ok1 = JSON.stringify(roles) === JSON.stringify(["subject","verb","object","place"]);
      const ok2 = JSON.stringify(roles) === JSON.stringify(["verb","subject","object","place"]);
      return (ok1 || ok2) ? "صحيح" : "تحقّق من ترتيب الكلمات.";
    };
    const f1 = evalZone($("#sent1"));
    const f2 = evalZone($("#sent2"));
    $("#order-feedback").textContent = `الجملة 1: ${f1} — الجملة 2: ${f2}`;
    show($("#order-feedback"));
    if (f1 === "صحيح" && f2 === "صحيح") show($("#to-typing"));
  });

  // --- AI grammar feedback (paragraph-level) ---
  async function fetchAIGrammarFeedback(sentences) {
    try {
      const res = await fetch("/api/ai/grammar", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ sentences })
      });
      const data = await res.json();
      if (data.ok && data.feedback) return data.feedback;
      if (data.error === "ai_not_configured") {
        return "ملاحظة: الذكاء الاصطناعي غير مفعّل بعد. أضف مفاتيح Azure في ملف .env لتفعيل التحقق الذكي.";
      }
      return data.feedback || "تعذّر الحصول على مخرجات الذكاء الاصطناعي.";
    } catch {
      return "تعذّر الاتصال بخدمة الذكاء الاصطناعي.";
    }
  }

  // Grammar check button (multi-sentence)
  $("#btn-check-grammar")?.addEventListener("click", async () => {
    const s1 = $("#sent1-text").value.trim();
    const s2 = $("#sent2-text").value.trim();

    const aiText = await fetchAIGrammarFeedback([s1, s2]);
    $("#grammar-feedback").textContent = aiText;
    show($("#grammar-feedback"));
    show($("#to-yn"));
  });

  // --- AI Y/N grammar correctness ---
  async function fetchAIYesNoGrammar(sentence, answer) {
    try {
      const res = await fetch("/api/ai/yn_grammar", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ sentence, answer })
      });
      return await res.json();
    } catch {
      return { ok: false };
    }
  }

  $all("#step-yn .yn-buttons .btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const userAns = btn.dataset.answer; // yes|no
      const stimulus = $("#yn-stimulus")?.textContent || "";
      const data = await fetchAIYesNoGrammar(stimulus, userAns);

      if (data.ok) {
        $("#yn-feedback").textContent = data.correct
          ? `إجابة صحيحة. ${data.reason || ""}`
          : `ليست صحيحة. التقييم المتوقع: ${data.expected}. ${data.reason || ""}`;
      } else {
        const correct = "yes";
        $("#yn-feedback").textContent = (userAns === correct)
          ? "إجابة صحيحة." : "ليست صحيحة. الجملة سليمة نحويًا هنا.";
      }
      show($("#yn-feedback"));
      show($("#to-sem"));
    });
  });

  // --- AI Y/N semantic plausibility ---
  async function fetchAIYesNoSemantics(sentence, answer) {
    try {
      const res = await fetch("/api/ai/yn_semantics", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ sentence, answer })
      });
      return await res.json();
    } catch {
      return { ok: false };
    }
  }

  $all("#step-sem .yn-buttons .btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const userAns = btn.dataset.answer; // yes|no
      const stimulus = $("#sem-stimulus")?.textContent || "";
      const data = await fetchAIYesNoSemantics(stimulus, userAns);

      if (data.ok) {
        $("#sem-feedback").textContent = data.correct
          ? `إجابة صحيحة. ${data.reason || ""}`
          : `ليست صحيحة. التقييم المتوقع: ${data.expected}. ${data.reason || ""}`;
      } else {
        const correct = "no";
        $("#sem-feedback").textContent = (userAns === correct)
          ? "صحيح: (سيأكل) لا تأتي مع (أمس)." : "تحقّق من الزمن: سيأكل/أمس متضادان.";
      }
      show($("#sem-feedback"));
      show($("#finish"));
    });
  });

  // Finish
  $("#finish")?.addEventListener("click", () => { hide($("#step-sem")); show($("#step-finish")); });

  $("#finish-ok")?.addEventListener("click", async () => {
    if (!$("#btn-start")) return;
    const name = $("#client-name")?.value || "عميل";
    const payload = { summary: "client finished", client_name: name, preview: isPreview };
    try {
      await fetch(`/api/${$("#btn-start").dataset.token}/submit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      alert(isPreview ? "تم الإرسال في وضع التجربة (لن يُحفظ)." : "تم الإرسال، شكرًا!");
    } catch {}
  });
})();
