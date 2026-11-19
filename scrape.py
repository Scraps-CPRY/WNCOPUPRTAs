import json, os, re, sys, time, subprocess, urllib.request
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

BASE = "https://femdom-joi.com/"
UA = {"User-Agent": "Mozilla/5.0 (compatible; feedbot/1.0)"}
LAST_PAGE = 4377
MONTHS = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}

def get(url, tries=3):
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            time.sleep(1.2)
    return ""

def page_url(n):
    return BASE if n <= 1 else BASE + "page/%d/" % n

def parse(doc):
    out = []
    for block in doc.split('<article class="video-card')[1:]:
        block = block.split("</article>")[0]
        a = re.search(r'<a href="([^"]+)"', block)
        t = re.search(r'aria-label="([^"]*)"', block)
        i = re.search(r'<img src="([^"]+)"', block)
        meta = re.findall(r'<span class="video-meta">\s*<span>([^<]*)</span>\s*<span>([^<]*)</span>', block)
        if not (a and t):
            continue
        title = t.group(1).strip()
        parts = re.split(r"\s+[–-]\s+", title, 1)
        performer = parts[0].strip() if len(parts) > 1 else ""
        vtype = meta[0][0].strip() if meta else ""
        ts = time.time()
        if meta:
            d = re.match(r"([A-Za-z]{3})\w*\s+(\d{1,2}),\s*(\d{4})", meta[0][1])
            if d and d.group(1).lower() in MONTHS:
                ts = datetime(int(d.group(3)), MONTHS[d.group(1).lower()], int(d.group(2)), 12).timestamp()
        out.append({
            "id": a.group(1).rstrip("/").rsplit("/", 1)[-1],
            "url": a.group(1),
            "title": title,
            "performer": performer,
            "type": vtype,
            "ts": ts,
            "img": i.group(1) if i else "",
        })
    return out

def cats_of(url):
    doc = get(url, 2)
    return sorted({m.group(1) for m in re.finditer(r'/category/([a-z0-9-]+)/', doc)})[:8]

def sh(cmd):
    subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def push():
    sh("git add -A")
    sh('git commit -q -m feed')
    for _ in range(4):
        sh("git pull --rebase -q")
        if subprocess.run("git push -q", shell=True).returncode == 0:
            return
        time.sleep(2)

def load_index():
    return json.load(open("index.json")) if os.path.exists("index.json") else []

def enrich(items):
    with ThreadPoolExecutor(max_workers=10) as ex:
        cats = list(ex.map(lambda x: cats_of(x["url"]), items))
    for it, c in zip(items, cats):
        it["cats"] = c
    return items

def cycle(enrich_limit=0, enrich_only_new=True):
    index = load_index()
    known = {i["id"] for i in index}
    added = []
    for p in (1, 2):
        items = [i for i in parse(get(page_url(p))) if i["id"] not in known]
        if not items:
            continue
        for i in items:
            known.add(i["id"])
        added += enrich(items)
    if enrich_limit and not enrich_only_new:
        pending = [i for i in index if not i.get("cats")][:enrich_limit]
        enrich(pending)
    index = added + index
    json.dump(index, open("index.json", "w"), ensure_ascii=False)
    push()
    print("%d nuevos, %d total" % (len(added), len(index)))

def archive(minutes):
    state = json.load(open("state.json")) if os.path.exists("state.json") else {}
    page = state.get("page", 3)
    end = time.time() + minutes * 60
    batch = 0
    with open("arc.jsonl", "a", encoding="utf-8") as out:
        while page <= LAST_PAGE and time.time() < end:
            items = parse(get(page_url(page)))
            if not items:
                page += 1
                time.sleep(2)
                continue
            for it in enrich(items):
                out.write(json.dumps(it, ensure_ascii=False) + "\n")
            out.flush()
            page += 1
            batch += 1
            if batch % 40 == 0:
                state["page"] = page
                json.dump(state, open("state.json", "w"))
                push()
            time.sleep(0.8)
    state["page"] = page
    state["done"] = page > LAST_PAGE
    json.dump(state, open("state.json", "w"))
    push()
    print("archivo en pagina %d de %d" % (page, LAST_PAGE))

if __name__ == "__main__":
    if "--archive" in sys.argv:
        archive(int(sys.argv[sys.argv.index("--minutes") + 1]) if "--minutes" in sys.argv else 10)
    else:
        mins = int(sys.argv[sys.argv.index("--minutes") + 1]) if "--minutes" in sys.argv else 10
        iv = int(sys.argv[sys.argv.index("--interval") + 1]) if "--interval" in sys.argv else 180
        end = time.time() + mins * 60
        while time.time() < end:
            try:
                cycle()
            except Exception as e:
                print("error:", e)
            time.sleep(iv)
