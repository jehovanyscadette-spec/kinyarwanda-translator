"""Translator website with sign up and log in.
Run locally:  py -3.11 web_app.py      Online:  gunicorn web_app:app"""
import os
import re
from datetime import date
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
# Online: set DATABASE_URL (Postgres, e.g. Neon) so accounts are kept forever.
# On your computer: no setting needed, it uses the file users.db.
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL:
    import psycopg
    from psycopg.rows import dict_row

CODE_NAME = {GOOGLE[n]: n.title() for n in NAMES}
CODE_NAME["auto"] = "Auto-detect"


def run(sql, params=(), fetch=None):
    """Run one SQL command. fetch: None, 'one', 'all' or 'id' (new row id)."""
    if DATABASE_URL:
        con = psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=15)
        sql = sql.replace("?", "%s") + (" RETURNING id" if fetch == "id" else "")
    else:
        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row
    try:
        cur = con.execute(sql, params)
        if fetch == "one":
            out = cur.fetchone()
        elif fetch == "all":
            out = cur.fetchall()
        elif fetch == "id":
            out = cur.fetchone()["id"] if DATABASE_URL else cur.lastrowid
        else:
            out = None
        con.commit()
        return out
    finally:
        con.close()


def init_db():
    pk = "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"
    run(f"CREATE TABLE IF NOT EXISTS users (id {pk}, name TEXT NOT NULL, "
        "email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, "
        "created TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    run(f"CREATE TABLE IF NOT EXISTS history (id {pk}, user_id INTEGER NOT NULL, "
        "source TEXT, target TEXT, original TEXT, result TEXT, "
        "created TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")


def iso(v):
    s = v.isoformat() if hasattr(v, "isoformat") else str(v).replace(" ", "T")
    return s if s.endswith("Z") else s + "Z"


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


def microsoft(text, src, tgt):
    """Official Microsoft Translator (needs AZURE_TRANSLATOR_KEY)."""
    fix = {"zh-CN": "zh-Hans"}
    params = {"api-version": "3.0", "to": fix.get(tgt, tgt)}
    if src != "auto":
        params["from"] = fix.get(src, src)
    r = requests.post(
        "https://api.cognitive.microsofttranslator.com/translate",
        params=params,
        headers={
            "Ocp-Apim-Subscription-Key": os.environ["AZURE_TRANSLATOR_KEY"],
            "Ocp-Apim-Subscription-Region": os.environ.get("AZURE_TRANSLATOR_REGION", "global"),
            "Content-Type": "application/json",
        },
        json=[{"Text": text}],
        timeout=10,
    )
    r.raise_for_status()
    return r.json()[0]["translations"][0]["text"]


def google_cloud(text, src, tgt):
    """Official Google Cloud Translation (needs GOOGLE_API_KEY)."""
    data = {"q": text, "target": tgt, "format": "text",
            "key": os.environ["GOOGLE_API_KEY"]}
    if src != "auto":
        data["source"] = src
    r = requests.post("https://translation.googleapis.com/language/translate/v2",
                      data=data, timeout=10)
    r.raise_for_status()
    return r.json()["data"]["translations"][0]["translatedText"]


def active_methods():
    """Official services first (if a key is set), free routes last."""
    found = []
    if os.environ.get("AZURE_TRANSLATOR_KEY"):
        found.append(microsoft)
    if os.environ.get("GOOGLE_API_KEY"):
        found.append(google_cloud)
    return found + [method_1, method_2]


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
    for method in active_methods():
        try:
            out = method(text, src, tgt)
            if out and out.strip():
                try:
                    run("INSERT INTO history (user_id, source, target, original, result) "
                        "VALUES (?, ?, ?, ?, ?)", (session["user_id"], src, tgt, text, out))
                except Exception:
                    pass  # a history problem must never block a translation
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
/* tabs, history, learn */
[hidden]{display:none!important}
.logo{font:700 1.2rem Georgia,"Times New Roman",serif;color:var(--deep);text-decoration:none}
nav{display:flex;gap:4px;flex:1;margin-left:18px}
nav a{padding:7px 14px;border-radius:8px;color:var(--muted);text-decoration:none;font-weight:600}
nav a:hover{background:var(--paper)}nav a.on{background:#e4efe8;color:var(--deep)}
.who{color:var(--muted);margin-right:10px}
.toolbar{display:flex;gap:10px;margin-bottom:16px}.toolbar form{margin:0}
.toolbar input{flex:1;font:inherit;padding:10px 12px;border:1px solid var(--line);border-radius:8px;min-width:0}
.hist{list-style:none;margin:0;padding:0;display:grid;gap:12px}
.hist li{background:#fff;border:1px solid var(--line);border-left:5px solid var(--green);border-radius:10px;padding:14px 16px}
.pair{display:flex;justify-content:space-between;gap:10px;color:var(--muted);font-size:.85rem}
.tag{font-weight:600;color:var(--green)}
.orig{margin:8px 0 2px;color:var(--muted);overflow-wrap:anywhere}
.res{margin:0 0 12px;font-size:1.2rem;font-weight:600;overflow-wrap:anywhere}
.row{display:flex;gap:10px;align-items:center}.row form{margin:0}
.small{padding:6px 12px;font-size:.9rem}
a.btn{text-decoration:none;display:inline-block}a.btn.ghost{background:transparent;color:var(--green)}
.empty{text-align:center;padding:56px 20px;background:#fff;border:1px dashed var(--line);border-radius:12px}
.empty h2{font-size:1.5rem;margin-bottom:6px}.empty p{color:var(--muted);margin:0 0 18px}
.today{background:var(--deep);color:#fff;border-radius:14px;padding:28px;margin-bottom:24px}
.today .label{color:var(--yellow);font-weight:700;letter-spacing:.06em;text-transform:uppercase;font-size:.8rem}
.today .kin{font:700 clamp(2rem,6vw,3.2rem)/1.1 Georgia,serif;margin:8px 0}.today .en{color:#cfe3d7}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:12px}
.cards div{background:#fff;border:1px solid var(--line);border-top:4px solid var(--blue);border-radius:10px;padding:14px 16px}
.cards div:nth-child(3n+2){border-top-color:var(--yellow)}.cards div:nth-child(3n){border-top-color:var(--green)}
.cards b{display:block;font:700 1.25rem Georgia,serif}.cards span{color:var(--muted)}
@media(max-width:700px){nav{margin-left:6px}.who{display:none}header{flex-wrap:wrap}}
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

LAYOUT = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ikinyarwanda Translator</title><style>{{ css|safe }}</style></head><body>
<div class="flag"><i></i><i></i><i></i></div>
<header>
  <a class="logo" href="{{ url_for('home') }}">Ikinyarwanda</a>
  <nav>{% for key, label, url in tabs %}<a href="{{ url }}" class="{{ 'on' if active == key else '' }}">{{ label }}</a>{% endfor %}</nav>
  <span class="who">Muraho, {{ name }}</span>
  <form method="post" action="{{ url_for('logout') }}">
    <input type="hidden" name="csrf" value="{{ csrf }}">
    <button class="ghost" type="submit">Log out</button>
  </form>
</header>
<main>__BODY__</main>
<script>const $ = id => document.getElementById(id);__SCRIPT__</script></body></html>"""

APP_BODY = """
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
<p class="hint">Needs an internet connection. Machine translation can make small mistakes, so check important text. Press Ctrl+Enter to translate.</p>"""

APP_JS = """
const pre = {{ pre|tojson }};
if(pre.text) $("text").value = pre.text;
if(pre.src) $("src").value = pre.src;
if(pre.tgt) $("tgt").value = pre.tgt;
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
"""

HISTORY_BODY = """
<h1>History</h1>
<p class="sub2">Everything you translated, newest first. Only you can see it.</p>
{% if items %}
<div class="toolbar">
  <input type="search" id="find" placeholder="Search your history" aria-label="Search history">
  <form method="post" action="{{ url_for('history_clear') }}" onsubmit="return confirm('Delete all your history?')">
    <input type="hidden" name="csrf" value="{{ csrf }}"><button class="ghost" type="submit">Clear all</button>
  </form>
</div>
<ul class="hist" id="hist">
{% for h in items %}
<li data-s="{{ (h.original ~ ' ' ~ h.result)|lower }}">
  <div class="pair"><span class="tag">{{ h.src }} &rarr; {{ h.tgt }}</span><time datetime="{{ h.when }}"></time></div>
  <p class="orig">{{ h.original }}</p>
  <p class="res">{{ h.result }}</p>
  <div class="row">
    <a class="btn ghost small" href="{{ url_for('home', text=h.original, src=h.source, tgt=h.target) }}">Translate again</a>
    <form method="post" action="{{ url_for('history_delete', hid=h.id) }}">
      <input type="hidden" name="csrf" value="{{ csrf }}"><button class="ghost small" type="submit">Delete</button>
    </form>
  </div>
</li>
{% endfor %}
</ul>
<p id="none" class="sub2" hidden>No match.</p>
{% else %}
<div class="empty"><h2>Nothing here yet</h2><p>Your translations will appear here.</p>
<a class="btn" href="{{ url_for('home') }}">Start translating</a></div>
{% endif %}"""

HISTORY_JS = """
document.querySelectorAll("time").forEach(t => t.textContent = new Date(t.dateTime).toLocaleString([], {dateStyle:"medium", timeStyle:"short"}));
const f = $("find");
if(f) f.oninput = () => { const q = f.value.toLowerCase(); let n = 0;
  document.querySelectorAll("#hist li").forEach(li => { const ok = li.dataset.s.includes(q); li.hidden = !ok; if(ok) n++; });
  $("none").hidden = n > 0; };
"""

LEARN_BODY = """
<h1>Learn Kinyarwanda</h1>
<p class="sub2">Everyday phrases to practise. A new one is featured each day.</p>
<section class="today"><div class="label">Phrase of the day</div>
<div class="kin">{{ today[1] }}</div><div class="en">{{ today[0] }}</div></section>
<div class="cards">{% for en, kin in phrases %}<div><b>{{ kin }}</b><span>{{ en }}</span></div>{% endfor %}</div>
<p class="hint">These phrases are written for learners. Check with a native speaker before using them in formal writing.</p>"""

PHRASES = [
    ("Hello", "Muraho"), ("Good morning", "Mwaramutse"),
    ("Good afternoon / evening", "Mwiriwe"), ("How are you?", "Amakuru?"),
    ("I am fine", "Meze neza"), ("Thank you", "Murakoze"),
    ("You are welcome", "Ntacyo"), ("Welcome", "Murakaza neza"),
    ("Yes", "Yego"), ("No", "Oya"), ("Please", "Nyabuneka"),
    ("Excuse me / Sorry", "Mbabarira"), ("Goodbye", "Murabeho"),
    ("See you later", "Turabonana"), ("Good night", "Ijoro ryiza"),
    ("My name is ...", "Nitwa ..."), ("I love you", "Ndagukunda"),
    ("Water", "Amazi"), ("Happy birthday", "Isabukuru nziza"),
    ("How much is it?", "Ni angahe?"),
]


def page(body, script="", active="", **ctx):
    tpl = LAYOUT.replace("__BODY__", body).replace("__SCRIPT__", script)
    tabs = [("translate", "Translate", url_for("home")),
            ("history", "History", url_for("history")),
            ("learn", "Learn", url_for("learn"))]
    return render_template_string(
        tpl, css=CSS, csrf=csrf_token(), name=session.get("name", ""),
        active=active, tabs=tabs, **ctx)


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
    pre = {"text": request.args.get("text", "")[:4000],
           "src": request.args.get("src", ""), "tgt": request.args.get("tgt", "")}
    return page(APP_BODY, APP_JS, "translate", opts=options(), opts_t=options("rw"), pre=pre)


@app.get("/history")
@login_required
def history():
    rows = run("SELECT * FROM history WHERE user_id = ? ORDER BY id DESC LIMIT 200",
               (session["user_id"],), "all")
    items = [{"id": r["id"], "source": r["source"], "target": r["target"],
              "src": CODE_NAME.get(r["source"], r["source"]),
              "tgt": CODE_NAME.get(r["target"], r["target"]),
              "original": r["original"], "result": r["result"],
              "when": iso(r["created"])} for r in rows]
    return page(HISTORY_BODY, HISTORY_JS, "history", items=items)


@app.post("/history/<int:hid>/delete")
@login_required
def history_delete(hid):
    if csrf_ok():
        run("DELETE FROM history WHERE id = ? AND user_id = ?", (hid, session["user_id"]))
    return redirect(url_for("history"))


@app.post("/history/clear")
@login_required
def history_clear():
    if csrf_ok():
        run("DELETE FROM history WHERE user_id = ?", (session["user_id"],))
    return redirect(url_for("history"))


@app.get("/learn")
@login_required
def learn():
    today = PHRASES[date.today().toordinal() % len(PHRASES)]
    return page(LEARN_BODY, "", "learn", phrases=PHRASES, today=today)


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

    try:
        uid = run("INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                  (name, email, generate_password_hash(pw)), "id")
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            return auth_page("signup", "An account with this email already exists. Log in instead.", form)
        raise
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
    row = run("SELECT * FROM users WHERE email = ?", (email,), "one")
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