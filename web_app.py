"""Translator website. Run:  py -3.11 web_app.py   (opens in your browser)"""
import threading
import webbrowser

import requests
from deep_translator import GoogleTranslator
from deep_translator.constants import GOOGLE_LANGUAGES_TO_CODES as GOOGLE
from flask import Flask, jsonify, request

NAMES = [
    "english", "french", "kinyarwanda", "swahili", "spanish", "german",
    "portuguese", "italian", "dutch", "russian", "arabic", "turkish",
    "hindi", "chinese (simplified)", "japanese", "korean",
    "amharic", "luganda", "zulu", "somali", "yoruba", "hausa", "lingala",
]

app = Flask(__name__)


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
def translate():
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
                                   "Try a phone hotspot or wait a while.")


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kinyarwanda Translator</title>
<style>
:root{--paper:#f6f7f2;--ink:#14231a;--muted:#5d6b62;--line:#d5dacf;--green:#1f6b45;--blue:#00a1de;--yellow:#fad201}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.5 system-ui,"Segoe UI",sans-serif}
.flag{display:flex;height:10px}.flag i{flex:1}
.flag i:nth-child(1){background:var(--blue);flex:2}.flag i:nth-child(2){background:var(--yellow)}.flag i:nth-child(3){background:var(--green)}
main{max-width:920px;margin:0 auto;padding:40px 20px 60px}
h1{font:700 clamp(1.8rem,4vw,2.6rem)/1.15 Georgia,"Times New Roman",serif;margin:0 0 8px}
.sub{color:var(--muted);margin:0 0 28px;max-width:60ch}
.langs{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
select{font:inherit;padding:9px 12px;border:1px solid var(--line);border-radius:8px;background:#fff;min-width:0;flex:1 1 150px}
.panes{display:grid;grid-template-columns:1fr 1fr;gap:12px}
textarea,.out{min-height:220px;padding:16px;border:1px solid var(--line);border-radius:10px;background:#fff;font:inherit;font-size:1.15rem;line-height:1.5}
textarea{resize:vertical;width:100%}
.out{white-space:pre-wrap;overflow-wrap:anywhere}.out.empty{color:var(--muted)}.out.error{color:#a3261c}
.actions{display:flex;gap:10px;margin-top:14px;flex-wrap:wrap}
button{font:inherit;padding:10px 20px;border-radius:8px;border:1px solid var(--green);background:var(--green);color:#fff;cursor:pointer}
button.ghost{background:transparent;color:var(--green)}
button#swap{padding:9px 14px;background:#fff;color:var(--green);border-color:var(--line)}
button:disabled{opacity:.6;cursor:wait}
button:focus-visible,select:focus-visible,textarea:focus-visible{outline:3px solid var(--blue);outline-offset:2px}
.hint{color:var(--muted);font-size:.9rem;margin-top:18px}
@media(max-width:700px){.panes{grid-template-columns:1fr}textarea,.out{min-height:140px}}
</style></head><body>
<div class="flag"><i></i><i></i><i></i></div>
<main>
<h1>Translate into Kinyarwanda</h1>
<p class="sub">Type a word or sentence in any language. You can also choose a different language to translate into.</p>
<div class="langs">
<select id="src" aria-label="Translate from"><option value="auto">Auto-detect</option>__OPTIONS__</select>
<button id="swap" title="Swap languages" aria-label="Swap languages">&#8644;</button>
<select id="tgt" aria-label="Translate to">__OPTIONS_T__</select>
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
    const r = await fetch("/translate",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({text, source:$("src").value, target:$("tgt").value})});
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


@app.get("/")
def home():
    return PAGE.replace("__OPTIONS_T__", options("rw")).replace("__OPTIONS__", options())


if __name__ == "__main__":
    threading.Timer(1.0, lambda: webbrowser.open("http://127.0.0.1:5000")).start()
    app.run(host="127.0.0.1", port=5000)