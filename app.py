from flask import Flask, render_template, request, jsonify, url_for, abort
import os, json, uuid
from pathlib import Path

# --- Flask setup ---
BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
GENERATED_DIR = BASE_DIR / "generated_sessions"
GENERATED_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__, template_folder=str(TEMPLATES_DIR), static_folder=str(STATIC_DIR))

# --- Routes ---

@app.get("/")
def home():
    # Verb input page for SLP
    return render_template("playground.html")

@app.post("/start")
def start():
    # Begin the SLP sandbox flow with a verb
    verb = (request.form.get("verbInput") or "").strip()
    if not verb:
        return "لم يتم إدخال أي فعل", 400
    # Pass initial context to the SLP flow template
    return render_template("slp_flow.html", verb=verb)

@app.post("/share")
def share():
    """
    Receives JSON from the SLP flow containing:
    - verb
    - subjects (list length 2)
    - objects (list length 2 aligned with subjects)
    - places (list length 2 aligned with subjects)
    - grammar_questions (list of dicts: sentence, answer: yes/no, correction)
    - semantic_items (list of dicts: item, judgement, correction)
    Creates a static HTML page for the patient and returns a shareable URL.
    """
    try:
        data = request.get_json(force=True)
    except Exception:
        return "Bad JSON", 400

    # Minimal validation
    verb = (data.get("verb") or "").strip()
    if not verb:
        return "verb is required", 400

    token = uuid.uuid4().hex[:10]
    payload_path = GENERATED_DIR / f"{token}.json"
    html_path = GENERATED_DIR / f"{token}.html"

    # Persist the session payload (helps future analysis/debugging)
    payload_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # Render the patient page with the payload embedded
    html = render_template("patient_session.html", token=token, payload_json=json.dumps(data, ensure_ascii=False))
    html_path.write_text(html, encoding="utf-8")

    return jsonify({
        "ok": True,
        "url": url_for("serve_generated", token=token, _external=True),
        "token": token
    })

@app.get("/p/<token>")
def serve_generated(token):
    # Serve the generated patient page (static HTML created by /share)
    html_file = GENERATED_DIR / f"{token}.html"
    if not html_file.exists():
        abort(404)
    return html_file.read_text(encoding="utf-8")

if __name__ == "__main__":
    # Bind explicitly for local dev; change host as needed for deployment
    app.run(debug=True, host="127.0.0.1", port=5000)
