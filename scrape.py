import json, os, re, sys, time, subprocess, urllib.request, html
from datetime import datetime

BASE = "https://puerto-rico2.wanuncios.com/"
UA = {"User-Agent": "Mozilla/5.0 (compatible; feedbot/1.0)"}
KEEP_DAYS = 21
MONTHS = {m: i for i, m in enumerate(
    "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split())}

def get(url):
    for _ in range(3):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            time.sleep(3)
    return ""

def page_url(n):
    return BASE + ("contactos-8.html" if n <= 1 else "contactos-8_%d.html" % n)

PAT = re.compile(
    r'(?:<td[^>]*colspan="2"[^>]*>\s*<div[^>]*>\s*</div>\s*<span[^>]*><strong>(?P<date>[^<]+)</strong>)'
    r'|<strong><a href="(?P<url>[^"]+?-(\d+)-(\d+)\.html)"[^>]*>(?P<title>[^<]*)</a></strong>'
    r'(?:\s*<span[^>]*>\((?P<loc>[^)]*)\)</span>)?\s*(?:<br\s*/?>)?\s*'
    r'(?:<span[^>]*gris[^>]*>(?P<desc>.*?)</span>)?',
    re.S)

def parse(doc):
    out, cur = [], None
    for m in PAT.finditer(doc):
        if m.group("date"):
            d = re.search(r"(\d{1,2}) de (\w+) de (\d{4})", m.group("date"))
            if d and d.group(2).lower() in MONTHS:
                cur = datetime(int(d.group(3)), MONTHS[d.group(2).lower()] + 1,
                               int(d.group(1)), 13).timestamp()
            continue
        if not m.group("title"):
            continue
        u = m.group("url")
        out.append({
            "id": u.rsplit("-", 1)[-1].replace(".html", ""),
            "cat": re.search(r"-(\d+)-\d+\.html$", u).group(1),
            "url": u,
            "title": html.unescape(m.group("title")).strip(),
            "loc": (m.group("loc") or "").strip(),
            "desc": re.sub(r"\s+", " ", html.unescape(m.group("desc") or "")).strip(),
            "ts": cur or time.time(),
        })
    return out

def photos_of(url):
    doc = get(url)
    found = []
    for m in re.finditer(r'href="([^"]*?/uploads/[^"]+?\.jpg)[^"]*"', doc):
        u = m.group(1)
        if u.startswith("/"):
            u = BASE + u[1:]
        u = u.split("?")[0].replace("_thumb.jpg", ".jpg")
        if u not in found:
            found.append(u)
    return found[:5]

def sh(cmd):
    subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def cycle():
    cutoff = time.time() - KEEP_DAYS * 86400
    index = json.load(open("index.json")) if os.path.exists("index.json") else []
    known = {i["id"] for i in index}
    os.makedirs("img", exist_ok=True)
    new = []

    for p in range(1, 4):
        doc = get(page_url(p))
        if not doc:
            break
        items = parse(doc)
        if not items:
            break
        for it in [i for i in items if i["id"] not in known]:
            known.add(it["id"])
            paths = []
            for n, u in enumerate(photos_of(it["url"]), 1):
                fn = "img/%s-%d.jpg" % (it["id"], n)
                try:
                    with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30) as r:
                        data = r.read()
                    if len(data) > 3000:
                        open(fn, "wb").write(data)
                        paths.append(fn)
                except Exception:
                    pass
            it["photos"] = paths
            new.append(it)
        if min(i["ts"] for i in items) < cutoff:
            break

    index = [i for i in new + index if i["ts"] >= cutoff]
    live = {i["id"] for i in index}
    json.dump(index, open("index.json", "w"), ensure_ascii=False)

    for f in os.listdir("img"):
        if f.split("-")[0] not in live:
            os.remove(os.path.join("img", f))

    sh("git add -A")
    sh('git commit -q -m feed')
    sh("git pull --rebase -q")
    sh("git push -q")
    print("%d nuevos, %d en total" % (len(new), len(index)))

if __name__ == "__main__":
    mins = int(sys.argv[sys.argv.index("--minutes") + 1]) if "--minutes" in sys.argv else 10
    iv = int(sys.argv[sys.argv.index("--interval") + 1]) if "--interval" in sys.argv else 180
    end = time.time() + mins * 60
    while time.time() < end:
        try:
            cycle()
        except Exception as e:
            print("error:", e)
        time.sleep(iv)
