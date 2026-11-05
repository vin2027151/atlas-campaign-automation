import os, sys, json, urllib.request, time, glob
ROOT = os.path.expanduser("~/atlas-dashboard")
OUT = os.path.join(ROOT, "kimi")
KEY = os.environ["SECRET_VALUE"]
MODEL = "kimi-k3.1-pro"

def call(name, system, user, max_tokens=32000):
    body = {"model": MODEL, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": max_tokens, "temperature": 1, "stream": True, "reasoning_effort": "high"}
    t0 = time.time()
    content, reasoning_chars, finish, usage = [], 0, None, None
    out_path = os.path.join(OUT, name + ".md")
    for attempt in (1, 2):
        req = urllib.request.Request("https://api.moonshot.ai/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json", "Accept": "text/event-stream"})
        try:
            resp = urllib.request.urlopen(req, timeout=600)
        except urllib.error.HTTPError as e:
            err = e.read().decode()[:600]
            if attempt == 1 and "reasoning_effort" in err:
                body.pop("reasoning_effort"); body["thinking"] = {"type": "enabled"}; continue
            open(os.path.join(OUT, name + ".error.txt"), "w").write(err); return
        with open(out_path, "w") as fh:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"): continue
                data = line[5:].strip()
                if data == "[DONE]": break
                try: ev = json.loads(data)
                except Exception: continue
                if ev.get("usage"): usage = ev["usage"]
                for ch in ev.get("choices", []):
                    d = ch.get("delta", {})
                    if d.get("reasoning_content"): reasoning_chars += len(d["reasoning_content"])
                    if d.get("content"):
                        fh.write(d["content"]); fh.flush(); content.append(d["content"])
                    if ch.get("finish_reason"): finish = ch["finish_reason"]
                if int(time.time() - t0) % 60 == 0:
                    open(os.path.join(OUT, name + ".progress"), "w").write("%ds reasoning=%d content=%d\n" % (time.time() - t0, reasoning_chars, sum(map(len, content))))
        break
    meta = {"model": MODEL, "usage": usage, "seconds": round(time.time() - t0), "finish": finish, "reasoning_chars": reasoning_chars, "content_chars": sum(map(len, content))}
    open(os.path.join(OUT, name + ".meta.json"), "w").write(json.dumps(meta, indent=1))

def read(p): return open(os.path.join(ROOT, p)).read()
which = sys.argv[1]
files = ["app.py", "store.py", "templates/base.html", "templates/home.html", "templates/spend.html", "templates/calendar.html",
         "templates/reporting.html", "templates/management.html", "templates/campaigns.html", "static/css/app.css",
         "static/js/common.js", "static/js/spend.js", "static/js/calendar.js", "static/js/reporting.js",
         "static/js/management.js", "static/js/campaigns.js", "api/spend.py", "api/calendar.py", "api/reporting.py",
         "api/management.py", "api/campaigns.py"]
if which == "design":
    src = "\n\n".join("===== FILE: %s =====\n%s" % (f, read(f)) for f in files)
    system = ("You are a principal product designer and front-end engineer reviewing an internal paid-media operations "
              "dashboard for a performance marketing manager. You are blunt, specific, and you write code. You never "
              "change the data model, the API routes, or the Python. You never invent new data the API does not return.")
    user = (read("SPEC.md") + "\n\n--- BRAND ---\nThe dashboard uses Search Atlas brand tokens (see :root in app.css): dark ink, "
            "purple #936BDA, mint #00FFD4, Inter Tight display / Inter body, pill buttons. Keep that identity.\n\n"
            "--- TASK ---\nReview the whole dashboard below and make it materially better on: organization (page structure, "
            "what sits where, what is above the fold), labelling (every number has an unambiguous name and unit), usability "
            "and interaction (fewer clicks to the daily decisions, obvious affordances, inline confirms, keyboard), management "
            "workflows (the media buyer's morning routine: what is failing, what to pause, what to scale, what to approve), "
            "viewability (density, hierarchy, scanning at a glance, dark-mode contrast), device compatibility (1440 desktop, "
            "1024 laptop, 768 tablet, 390 phone), and data display (tables vs tiles vs charts, number formatting, sparklines, "
            "deltas, target bands, empty and null states, small-count caveats).\n\n"
            "Deliver, in this order:\n"
            "1. A ranked list of the 15 most valuable changes across the product, each with: page, the problem, the fix, why it matters to a media buyer, effort (S/M/L).\n"
            "2. Per page (home, spend, calendar, reporting, management, campaigns): a short critique and the recommended section order above the fold at 1440 and at 390.\n"
            "3. CODE: complete replacement files for static/css/app.css and templates/base.html implementing your global changes (keep every existing class name that page templates use, you may add new ones), plus, for each page, a unified diff or a complete replacement of its template and JS where you changed it. Mark each code block with the exact path. Do not shorten files with '...' — a file you emit must be complete and runnable.\n"
            "4. A short list of things you chose NOT to change and why.\n\n"
            "--- SOURCE ---\n" + src)
    call("design-review", system, user, max_tokens=48000)
elif which == "preloader":
    svg = read("static/img/searchatlas-wordmark-white.svg")
    system = ("You are a senior motion designer and front-end engineer. You write complete, dependency-free, production-quality "
              "HTML/CSS/JS. You respect reduced-motion preferences and never block assistive technology.")
    user = ("Build an animated page preloader for an internal dashboard branded for Search Atlas. Brand: ink #121212, purple #936BDA "
            "(soft #AA85EC, dark #653A9D), mint #00FFD4, font Inter Tight. The logo is the SVG wordmark below (white on dark). "
            "Animate the LOGO ITSELF for exactly 3 seconds: for example stroke-draw / reveal of the letter paths, a mint-to-purple "
            "sweep, a subtle scale settle — your call, but it must read as the Search Atlas logo from the first frame and end on the "
            "clean white wordmark before fading the overlay out. Total 3.0s then a 300ms fade. Must look premium, not generic.\n\n"
            "Deliver as a single self-contained ES module file static/js/preloader.js that: (1) injects its own CSS and the overlay "
            "into document.body as early as possible (it will be loaded in <head> with type=module, so handle DOMContentLoaded), "
            "(2) exports showPreloader({duration=3000}) returning a Promise, (3) decides on its own whether to run using localStorage "
            "key 'sa_preloader_last' (epoch ms): run when the key is missing (new browser) OR older than 30 minutes, then write the "
            "current time; never use cookies; wrap all storage access in try/catch and treat failure as 'run it', (4) under "
            "prefers-reduced-motion shows a static logo for 800ms instead, (5) sets aria-busy on body while visible and is "
            "aria-hidden itself, (6) prevents layout flash: the overlay is full-viewport, ink background, above everything (z-index "
            "9999), and page scroll is locked while it shows, (7) is safe to call twice. Also deliver a 20-line README comment at the top "
            "of the file explaining how to include it and how to force it (?preloader=1 query param) for demos.\n\n"
            "If you need the logo as inline SVG inside the overlay, embed the paths from the file below (you may simplify but it must "
            "remain visibly the same wordmark). Output ONLY the file, in one code block, path marked.\n\n"
            "===== FILE: static/img/searchatlas-wordmark-white.svg =====\n" + svg)
    call("preloader", system, user, max_tokens=24000)
