from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, jsonify, session
)
import uuid
import datetime
import os
from dotenv import load_dotenv

# ---------- Load environment (.env) ----------
load_dotenv()
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY", "").strip()
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "").strip()

AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY", "").strip()
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION", "").strip()  # e.g., eastus
AZURE_SPEECH_VOICE = os.getenv("AZURE_SPEECH_VOICE", "ar-SA-HamedNeural").strip()

# Azure OpenAI client (optional)
client = None
if AZURE_OPENAI_KEY and AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_DEPLOYMENT:
    try:
        from openai import AzureOpenAI
        client = AzureOpenAI(
            api_key=AZURE_OPENAI_KEY,
            api_version="2024-05-01-preview",
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
        )
    except Exception:
        client = None  # keep app running without AI

app = Flask(__name__)
app.secret_key = "replace-with-a-strong-secret-key"  # used only for flash messages

# ----------------------------
# In-memory data (demo)
# ----------------------------
PLAYGROUNDS = {}
# PLAYGROUNDS[token] = {
#   "created_at": datetime,
#   "title": str,
#   "verb": str,
#   "notes": str,
#   "dialects": [str,...],
#   "client_runs": [
#       {"client_name": str, "date": iso, "answers": dict}
#   ]
# }

# ----------------------------
# Home → SLP dashboard (no login)
# ----------------------------
@app.route("/")
def home():
    return redirect(url_for("slp_dashboard"))

@app.route("/health")
def health():
    return "OK", 200

# ----------------------------
# SLP side (PDF 1)
# ----------------------------
@app.route("/slp/dashboard")
def slp_dashboard():
    rows = []
    for pid, pg in PLAYGROUNDS.items():
        rows.append({
            "id": pid,
            "title": pg.get("title", f"ملعب ({pid[:6]})"),
            "created_at": pg["created_at"],
            "client_runs": pg.get("client_runs", [])[-4:] if pg.get("client_runs") else [],
        })
    rows.sort(key=lambda r: r["created_at"], reverse=True)
    return render_template("slp_dashboard.html", rows=rows)

@app.route("/slp/new", methods=["GET", "POST"])
def slp_new_playground():
    if request.method == "POST":
        title = request.form.get("title", "ملعب لفظي").strip()
        verb = request.form.get("verb", "أكل").strip()
        notes = request.form.get("notes", "").strip()
        dialects = request.form.getlist("dialects")

        pid = uuid.uuid4().hex
        PLAYGROUNDS[pid] = {
            "created_at": datetime.datetime.now(),
            "title": title or "ملعب لفظي",
            "verb": verb or "أكل",
            "notes": notes,
            "dialects": dialects,
            "client_runs": []
        }
        flash("تم إنشاء الملعب. انسخ الرابط أو جرّبه كعميل.", "success")
        return redirect(url_for("slp_playground_results", playground_id=pid))

    return render_template("slp_playground_form.html")

@app.route("/slp/playground/<playground_id>")
def slp_playground_results(playground_id):
    pg = PLAYGROUNDS.get(playground_id)
    if not pg:
        flash("الملعب غير موجود.", "error")
        return redirect(url_for("slp_dashboard"))
        
    # Fix: Use playground_id instead of token in preview_url
    share_url = url_for("client_playground", token=playground_id, _external=True)
    preview_url = url_for("client_playground", token=playground_id, _external=True) + "?preview=1"
    
    return render_template("slp_playground_results.html",
                           pg=pg,
                           playground_id=playground_id,
                           share_url=share_url,
                           preview_url=preview_url)

# ----------------------------
# Client side (PDF 2)
# ----------------------------
@app.route("/c/<token>")
def client_playground(token):
    pg = PLAYGROUNDS.get(token)
    if not pg:
        flash("الرابط غير صحيح أو انتهت صلاحيته.", "error")
        return redirect(url_for("slp_dashboard"))
    
    # Get verb prompt
    verb = pg.get("verb", "")
    try:
        prompt_response = generate_object_prompt().get_json()
        verb_prompt = prompt_response.get("prompt", "من هو الفاعل المناسب؟")
    except:
        verb_prompt = "من هو الفاعل المناسب؟"
    
    return render_template(
        "client_playground.html",
        token=token,
        verb=verb,
        Verb_Prompt=verb_prompt,
        speech_region=AZURE_SPEECH_REGION,
        speech_voice=AZURE_SPEECH_VOICE,
        speech_enabled=bool(AZURE_SPEECH_KEY and AZURE_SPEECH_REGION),
    )
        

@app.post("/api/<token>/start")
def api_start(token):
    if token not in PLAYGROUNDS:
        return jsonify({"ok": False, "error": "invalid"}), 404
    rid = uuid.uuid4().hex
    return jsonify({"ok": True, "run_id": rid})

@app.post("/api/<token>/submit")
def api_submit(token):
    pg = PLAYGROUNDS.get(token)
    if not pg:
        return jsonify({"ok": False, "error": "invalid"}), 404

    payload = request.json or {}
    # If this is an SLP preview, don't store the run
    if payload.get("preview"):
        return jsonify({"ok": True, "skipped": "preview"})

    client_name = payload.get("client_name", "عميل")
    pg.setdefault("client_runs", []).append({
        "client_name": client_name,
        "date": datetime.datetime.now().isoformat(),
        "answers": payload
    })
    return jsonify({"ok": True})

# ----------------------------
# AI endpoints (OpenAI via Azure)
# ----------------------------
@app.post("/api/ai/object_prompt")
def generate_object_prompt():
    data = request.json or {}
    verb = data.get("verb", "").strip()
    if not verb:
        return jsonify({"ok": False, "error": "missing verb"}), 400

    # Fallback when AI not configured
    if client is None:
        default_prompt = f"ما هو المفعول به المناسب للفعل '{verb}'؟"
        return jsonify({"ok": True, "prompt": default_prompt})

    try:
        system_prompt = "أنت معلم لغة عربية. ساعد الطلاب في اختيار مفعول به مناسب للأفعال."
        user_prompt = f"اقترح مفعولاً به مناسباً للفعل '{verb}'"

        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=100,
            temperature=0.7
        )

        ai_prompt = response.choices[0].message.content.strip()
        return jsonify({"ok": True, "prompt": ai_prompt})
    except Exception as e:
        return jsonify({
            "ok": False,
            "error": "ai_error",
            "message": str(e)
        }), 500

@app.post("/api/ai/grammar")
def ai_grammar_feedback():
    data = request.json or {}
    sentences = data.get("sentences", [])
    if not isinstance(sentences, list) or len(sentences) == 0:
        return jsonify({"ok": False, "error": "missing sentences"}), 400

    if client is None:
        return jsonify({
            "ok": False,
            "error": "ai_not_configured",
            "feedback": "لم يتم إعداد Azure OpenAI. أضف AZURE_OPENAI_KEY / ENDPOINT / DEPLOYMENT في ملف .env."
        }), 200

    user_text = "\n".join([f"{i+1}. {s}" for i, s in enumerate(sentences)])
    prompt_system = "أنت أخصائي لغوي عربي. قدّم تصحيحًا نحويًا وجيزًا لكل جملة، مع سبب مبسّط."
    prompt_user = f"""صحّح الجمل التالية نحوياً وأعد صياغة كل جملة صحيحة باختصار، ثم اذكر سبب التصحيح باقتضاب.
اكتب النتيجة كقائمة مرقّمة مطابقة لعدد الجمل.

الجمل:
{user_text}
"""
    try:
        resp = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": prompt_system},
                {"role": "user", "content": prompt_user},
            ],
            max_tokens=350,
            temperature=0.2,
        )
        out = resp.choices[0].message.content.strip()
        return jsonify({"ok": True, "feedback": out})
    except Exception as e:
        return jsonify({
            "ok": False,
            "error": "ai_call_failed",
            "feedback": f"تعذّر الاتصال بخدمة الذكاء الاصطناعي: {e}"
        }), 200

@app.post("/api/ai/yn_grammar")
def ai_yn_grammar():
    data = request.json or {}
    sent = data.get("sentence", "").strip()
    answer = data.get("answer", "").strip().lower()
    if not sent or answer not in ("yes", "no"):
        return jsonify({"ok": False, "error": "bad_request"}), 400

    if client is None:
        expected = "yes"
        return jsonify({
            "ok": True,
            "expected": expected,
            "correct": (answer == expected),
            "reason": "الجملة سليمة نحويًا."
        })

    system = "أنت أخصائي نحو عربي. أجب فقط بـ 'yes' أو 'no' ثم سطر تفسير موجز."
    user = f"""هل الجملة التالية صحيحة نحويًا بالعربية الفصحى؟
الجملة: {sent}

أجب بالتنسيق:
answer: yes|no
reason: سبب موجز
"""
    try:
        resp = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=120,
            temperature=0.0,
        )
        text = resp.choices[0].message.content.strip().lower()
        expected = "yes" if "answer: yes" in text else "no"
        reason_line = ""
        for line in text.splitlines():
            if line.startswith("reason:"):
                reason_line = line.split(":", 1)[1].strip()
                break
        return jsonify({
            "ok": True,
            "expected": expected,
            "correct": (answer == expected),
            "reason": reason_line or "—"
        })
    except Exception as e:
        expected = "yes"
        return jsonify({
            "ok": True,
            "expected": expected,
            "correct": (answer == expected),
            "reason": f"تعذّر الاتصال بالذكاء الاصطناعي. ({e})"
        })

@app.post("/api/ai/yn_semantics")
def ai_yn_semantics():
    data = request.json or {}
    sent = data.get("sentence", "").strip()
    answer = data.get("answer", "").strip().lower()
    if not sent or answer not in ("yes", "no"):
        return jsonify({"ok": False, "error": "bad_request"}), 400

    if client is None:
        expected = "no"
        return jsonify({
            "ok": True,
            "expected": expected,
            "correct": (answer == expected),
            "reason": "تناقض زمني: المستقبل مع ظرف الماضي."
        })

    system = "أنت أخصائي دلالة عربية. قيّم الملاءمة الزمنية/المنطقية، ثم فسّر بإيجاز."
    user = f"""هل الجملة التالية صحيحة معنويًا/منطقيًا؟
الجملة: {sent}

أجب بالتنسيق:
answer: yes|no
reason: سبب موجز
"""
    try:
        resp = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=120,
            temperature=0.0,
        )
        text = resp.choices[0].message.content.strip().lower()
        expected = "yes" if "answer: yes" in text else "no"
        reason_line = ""
        for line in text.splitlines():
            if line.startswith("reason:"):
                reason_line = line.split(":", 1)[1].strip()
                break
        return jsonify({
            "ok": True,
            "expected": expected,
            "correct": (answer == expected),
            "reason": reason_line or "—"
        })
    except Exception as e:
        expected = "no"
        return jsonify({
            "ok": True,
            "expected": expected,
            "correct": (answer == expected),
            "reason": f"تعذّر الاتصال بالذكاء الاصطناعي. ({e})"
        })

# ----------------------------
# NEW: Azure Speech token endpoint (secure)
# ----------------------------
import time
import requests

_speech_token_cache = {"token": None, "expires": 0}

@app.route("/api/speech/token")
def speech_token():
    """
    Returns a short-lived token for Azure Speech (so the browser never sees your key).
    Response: { token: "...", region: "eastus", voice: "ar-SA-HamedNeural" }
    """
    if not (AZURE_SPEECH_KEY and AZURE_SPEECH_REGION):
        return jsonify({"error": "speech_not_configured"}), 200

    now = time.time()
    if _speech_token_cache["token"] and _speech_token_cache["expires"] > now + 5:
        return jsonify({
            "token": _speech_token_cache["token"],
            "region": AZURE_SPEECH_REGION,
            "voice": AZURE_SPEECH_VOICE
        })

    try:
        url = f"https://{AZURE_SPEECH_REGION}.api.cognitive.microsoft.com/sts/v1.0/issueToken"
        headers = {"Ocp-Apim-Subscription-Key": AZURE_SPEECH_KEY}
        r = requests.post(url, headers=headers, timeout=10)
        r.raise_for_status()
        token = r.text
        # tokens typically last ~10 minutes; we use 8 to be safe
        _speech_token_cache["token"] = token
        _speech_token_cache["expires"] = now + 8 * 60
        return jsonify({"token": token, "region": AZURE_SPEECH_REGION, "voice": AZURE_SPEECH_VOICE})
    except Exception as e:
        return jsonify({"error": f"token_error: {e}"}), 200

# ----------------------------
# Legacy route (disabled cleanly)
# ----------------------------
@app.route("/submit_verb", methods=["GET", "POST"])
def submit_verb():
    flash("تم إيقاف هذا المسار.", "error")
    return redirect(url_for("slp_dashboard"))

if __name__ == "__main__":
    app.run(debug=True)
