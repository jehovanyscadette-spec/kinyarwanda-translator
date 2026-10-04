"""Translator website with sign up and log in.
Run locally:  py -3.11 web_app.py      Online:  gunicorn web_app:app"""
import os
import re
import secrets
import sqlite3
import threading
import webbrowser
from functools import wraps

import requests
from deep_translator import GoogleTranslator
from deep_translator.constants import GOOGLE_LANGUAGES_TO_CODES as GOOGLE
from flask import (Flask, jsonify, redirect, render_template_string, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

NAMES = [
    "english", "french", "kinyarwanda", "swahili", "spanish", "german",
    "portuguese", "italian", "dutch", "russian", "arabic", "turkish",
    "hindi", "chinese (simplified)", "japanese", "korean",
    "amharic", "luganda", "zulu", "somali", "yoruba", "hausa", "lingala",
]
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DB_PATH = os.environ.get("DB_PATH", "users.db")

app = Flask(__name__)
# On Render, set a SECRET_KEY environment variable so logins survive restarts.
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")),
)


# ---------------------------------------------------------------- database
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = db()
    con.execute(
        "CREATE TABLE IF NOT EXISTS users ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, "
        "email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, "
        "created TEXT DEFAULT CURRENT_TIMESTAMP)")
    con.commit()
    con.close()


init_db()


# ---------------------------------------------------------------- security
def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


def csrf_ok():
    sent = request.form.get("csrf") or request.headers.get("X-CSRF") or ""
    return secrets.compare_digest(sent, session.get("csrf", ""))


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            if request.path == "/translate":
                return jsonify(ok=False, error="Please log in first."), 401
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------- translation
def method_1(text, src, tgt):
    return GoogleTranslator(source=src, target=tgt).translate(text)


def method_2(text, src, tgt):
    r = requests.get(
        "https://translate.googleapis.com/translate_a/single",
        params={"client": "gtx", "sl": src, "tl": tgt, "dt": "t", "q": text},
        timeout=10,
    )
    r.raise_for_status()
    return "".join(part[0] for part in r.json()[0] if part[0])


@app.post("/translate")
@login_required
def translate():
    if not csrf_ok():
        return jsonify(ok=False, error="Your session expired. Reload the page."), 400
    data = request.get_json(force=True)
    text = (data.get("text") or "").strip()
    src = data.get("source", "auto")
    tgt = data.get("target", "rw")
    if not text:
        return jsonify(ok=False, error="Type some text first.")
    if len(text) > 4000:
        return jsonify(ok=False, error="Text is too long. Keep it under 4000 characters.")
    for method in (method_1, method_2):
        try:
            out = method(text, src, tgt)
            if out and out.strip():
                return jsonify(ok=True, text=out)
        except Exception:
            pass
    return jsonify(ok=False, error="No answer. Google is limiting this connection. "
                                   "Try again in a while.")


# ---------------------------------------------------------------- pages
CSS = """
:root{--paper:#f6f7f2;--ink:#14231a;--muted:#5d6b62;--line:#d5dacf;--green:#1f6b45;--deep:#154a31;--blue:#00a1de;--yellow:#fad201;--red:#a3261c}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.5 system-ui,"Segoe UI",sans-serif}
.flag{display:flex;height:10px}.flag i{flex:1}
.flag i:nth-child(1){background:var(--blue);flex:2}.flag i:nth-child(2){background:var(--yellow)}.flag i:nth-child(3){background:var(--green)}
h1,h2{font-family:Georgia,"Times New Roman",serif;line-height:1.15;margin:0}
button,.btn{font:inherit;padding:11px 20px;border-radius:8px;border:1px solid var(--green);background:var(--green);color:#fff;cursor:pointer}
button.ghost{background:transparent;color:var(--green)}
button:disabled{opacity:.6;cursor:wait}
button:focus-visible,select:focus-visible,textarea:focus-visible,input:focus-visible,a:focus-visible{outline:3px solid var(--blue);outline-offset:2px}
/* auth */
.auth{display:grid;grid-template-columns:1fr 1fr;min-height:100vh}
.brand{background:var(--deep);color:#fff;padding:48px;display:flex;flex-direction:column;justify-content:flex-end;gap:14px}
.brand h1{font-size:clamp(2.4rem,5vw,4rem)}
.brand p{margin:0;max-width:34ch;color:#cfe3d7}
.stripe{display:flex;height:10px;width:120px;margin-bottom:6px}.stripe i{flex:1}
.stripe i:nth-child(1){background:var(--blue);flex:2}.stripe i:nth-child(2){background:var(--yellow)}.stripe i:nth-child(3){background:#fff}
.formside{display:flex;align-items:center;justify-content:center;padding:32px}
.card{width:100%;max-width:400px}
.card h2{font-size:1.8rem;margin-bottom:6px}
.card .sub{color:var(--muted);margin:0 0 22px}
label{display:block;font-weight:600;margin:14px 0 5px}
input[type=text],input[type=email],input[type=password]{width:100%;font:inherit;padding:11px 12px;border:1px solid var(--line);border-radius:8px;background:#fff}
.show{display:flex;gap:8px;align-items:center;margin:10px 0 0;font-weight:400;color:var(--muted)}
.card button[type=submit]{width:100%;margin-top:20px}
.error{background:#fbeceb;color:var(--red);border:1px solid #efc4c0;border-radius:8px;padding:10px 12px;margin-bottom:6px}
.switch{margin-top:20px;color:var(--muted)}.switch a{color:var(--green);font-weight:600}
@media(max-width:760px){.auth{grid-template-columns:1fr}.brand{padding:28px 24px;min-height:200px}}
/* app */
header{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:12px 20px;border-bottom:1px solid var(--line);background:#fff}
header form{margin:0}header button{padding:7px 14px}
main{max-width:920px;margin:0 auto;padding:36px 20px 60px}
main h1{font-size:clamp(1.8rem,4vw,2.6rem);margin-bottom:8px}
.sub2{color:var(--muted);margin:0 0 26px;max-width:60ch}
.langs{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
select{font:inherit;padding:9px 12px;border:1px solid var(--line);border-radius:8px;background:#fff;min-width:0;flex:1 1 150px}
.panes{display:grid;grid-template-columns:1fr 1fr;gap:12px}
textarea,.out{min-height:220px;padding:16px;border:1px solid var(--line);border-radius:10px;background:#fff;font:inherit;font-size:1.15rem;line-height:1.5}
textarea{resize:vertical;width:100%}
.out{white-space:pre-wrap;overflow-wrap:anywhere}.out.empty{color:var(--muted)}.out.error{color:var(--red)}
.actions{display:flex;gap:10px;margin-top:14px;flex-wrap:wrap}
button#swap{padding:9px 14px;background:#fff;color:var(--green);border-color:var(--line)}
.hint{color:var(--muted);font-size:.9rem;margin-top:18px}
@media(max-width:700px){.panes{grid-template-columns:1fr}textarea,.out{min-height:140px}}
"""

AUTH = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ 'Create account' if mode == 'signup' else 'Log in' }} - Kinyarwanda Translator</title>
<style>{{ css|safe }}</style></head><body>
<div class="auth">
  <section class="brand">
    <div class="stripe"><i></i><i></i><i></i></div>
    <h1>Murakaza neza</h1>
    <p>Translate into Kinyarwanda from 22 other languages. Log in to start.</p>
  </section>
  <section class="formside"><div class="card">
    <h2>{{ 'Create your account' if mode == 'signup' else 'Log in' }}</h2>
    <p class="sub">{{ 'It takes less than a minute.' if mode == 'signup' else 'Use the email and password you signed up with.' }}</p>
    {% if error %}<div class="error" role="alert">{{ error }}</div>{% endif %}
    <form method="post" autocomplete="on">
      <input type="hidden" name="csrf" value="{{ csrf }}">
      {% if mode == 'signup' %}
      <label for="name">Your name</label>
      <input type="text" id="name" name="name" value="{{ form.name }}" required maxlength="60" autocomplete="name">
      {% endif %}
      <label for="email">Email</label>
      <input type="email" id="email" name="email" value="{{ form.email }}" required maxlength="120" autocomplete="email">
      <label for="password">Password</label>
      <input type="password" id="password" name="password" required {% if mode == 'signup' %}minlength="8" autocomplete="new-password"{% else %}autocomplete="current-password"{% endif %}>
      {% if mode == 'signup' %}
      <label for="confirm">Confirm password</label>
      <input type="password" id="confirm" name="confirm" required minlength="8" autocomplete="new-password">
      {% endif %}
      <label class="show"><input type="checkbox" id="show"> Show password</label>
      <button type="submit">{{ 'Create account' if mode == 'signup' else 'Log in' }}</button>
    </form>
    <p class="switch">
      {% if mode == 'signup' %}Already have an account? <a href="{{ url_for('login') }}">Log in</a>
      {% else %}New here? <a href="{{ url_for('signup') }}">Create an account</a>{% endif %}
    </p>
  </div></section>
</div>
<script>
document.getElementById("show").onchange = e => {
  document.querySelectorAll('input[type=password],input[data-pw]').forEach(i => {
    i.type = e.target.checked ? "text" : "password"; i.dataset.pw = "1"; });
};
</script></body></html>"""

APP = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kinyarwanda Translator</title><style>{{ css|safe }}</style></head><body>
<div class="flag"><i></i><i></i><i></i></div>
<header>
  <strong>Muraho, {{ name }}</strong>
  <form method="post" action="{{ url_for('logout') }}">
    <input type="hidden" name="csrf" value="{{ csrf }}">
    <button class="ghost" type="submit">Log out</button>
  </form>
</header>
<main>
<h1>Translate into Kinyarwanda</h1>
<p class="sub2">Type a word or sentence in any language. You can also choose a different language to translate into.</p>
<div class="langs">
<select id="src" aria-label="Translate from"><option value="auto">Auto-detect</option>{{ opts|safe }}</select>
<button id="swap" title="Swap languages" aria-label="Swap languages">&#8644;</button>
<select id="tgt" aria-label="Translate to">{{ opts_t|safe }}</select>
</div>
<div class="panes">
<textarea id="text" placeholder="Type or paste text here" aria-label="Text to translate"></textarea>
<div id="out" class="out empty" aria-live="polite">The translation appears here.</div>
</div>
<div class="actions">
<button id="go">Translate</button>
<button id="copy" class="ghost">Copy translation</button>
<button id="clear" class="ghost">Clear</button>
</div>
<p class="hint">Needs an internet connection. Machine translation can make small mistakes, so check important text. Press Ctrl+Enter to translate.</p>
</main>
<script>
const $ = id => document.getElementById(id);
async function go(){
  const text = $("text").value.trim();
  if(!text){ show("Type some text first.", "error"); return; }
  $("go").disabled = true; show("Translating...", "empty");
  try{
    const r = await fetch("/translate",{method:"POST",headers:{"Content-Type":"application/json","X-CSRF":"{{ csrf }}"},
      body:JSON.stringify({text, source:$("src").value, target:$("tgt").value})});
    if(r.status===401){ location.href="/login"; return; }
    const d = await r.json();
    d.ok ? show(d.text, "") : show(d.error, "error");
  }catch(e){ show("Could not reach the translator. Is the program still running?", "error"); }
  $("go").disabled = false;
}
function show(t, cls){ const o=$("out"); o.textContent=t; o.className="out "+cls; }
$("go").onclick = go;
$("text").addEventListener("keydown", e => { if(e.ctrlKey && e.key==="Enter") go(); });
$("clear").onclick = () => { $("text").value=""; show("The translation appears here.", "empty"); };
$("copy").onclick = async () => { const o=$("out"); if(!o.classList.contains("empty") && !o.classList.contains("error")){ await navigator.clipboard.writeText(o.textContent); $("copy").textContent="Copied"; setTimeout(()=>$("copy").textContent="Copy translation",1500);} };
$("swap").onclick = () => { if($("src").value!=="auto"){ const s=$("src").value; $("src").value=$("tgt").value; $("tgt").value=s; } };
</script></body></html>"""


def options(selected=None):
    out = []
    for n in NAMES:
        code = GOOGLE[n]
        sel = " selected" if code == selected else ""
        out.append(f'<option value="{code}"{sel}>{n.title()}</option>')
    return "".join(out)


def auth_page(mode, error="", form=None):
    return render_template_string(
        AUTH, mode=mode, error=error, css=CSS, csrf=csrf_token(),
        form=form or {"name": "", "email": ""})


# ---------------------------------------------------------------- routes
@app.get("/")
@login_required
def home():
    return render_template_string(
        APP, css=CSS, csrf=csrf_token(), name=session.get("name", ""),
        opts=options(), opts_t=options("rw"))


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if "user_id" in session:
        return redirect(url_for("home"))
    if request.method == "GET":
        return auth_page("signup")

    if not csrf_ok():
        return auth_page("signup", "Your session expired. Please try again.")
    name = request.form.get("name", "").strip()[:60]
    email = request.form.get("email", "").strip().lower()[:120]
    pw = request.form.get("password", "")
    form = {"name": name, "email": email}

    if len(name) < 2:
        return auth_page("signup", "Enter your name.", form)
    if not EMAIL_RE.match(email):
        return auth_page("signup", "Enter a valid email address.", form)
    if len(pw) < 8:
        return auth_page("signup", "Use a password with at least 8 characters.", form)
    if pw != request.form.get("confirm", ""):
        return auth_page("signup", "The two passwords do not match.", form)

    con = db()
    try:
        cur = con.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (name, email, generate_password_hash(pw)))
        con.commit()
        uid = cur.lastrowid
    except sqlite3.IntegrityError:
        return auth_page("signup", "An account with this email already exists. Log in instead.", form)
    finally:
        con.close()

    session.clear()
    session["user_id"], session["name"] = uid, name
    return redirect(url_for("home"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("home"))
    if request.method == "GET":
        return auth_page("login")

    if not csrf_ok():
        return auth_page("login", "Your session expired. Please try again.")
    email = request.form.get("email", "").strip().lower()
    pw = request.form.get("password", "")
    con = db()
    row = con.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    con.close()
    if not row or not check_password_hash(row["password_hash"], pw):
        return auth_page("login", "The email or password is wrong.", {"name": "", "email": email})

    session.clear()
    session["user_id"], session["name"] = row["id"], row["name"]
    return redirect(url_for("home"))


@app.post("/logout")
def logout():
    if csrf_ok():
        session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    threading.Timer(1.0, lambda: webbrowser.open("http://127.0.0.1:5000")).start()
    app.run(host="127.0.0.1", port=5000)