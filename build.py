#!/usr/bin/env python3
"""Stiri 3DExposed: citeste sursele, da scoruri si genereaza site/index.html."""
import calendar
import html
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import feedparser
import requests
import yaml

ROOT = Path(__file__).parent
SITE = ROOT / "site"
UA = {"User-Agent": "Mozilla/5.0 (compatible; stiri-bot/1.0)"}
NOW = datetime.now(timezone.utc)
TODAY = NOW.date()


# ---------------------------------------------------------------- utilitare
def get(url, **kw):
    r = requests.get(url, headers=UA, timeout=25, **kw)
    r.raise_for_status()
    return r


def clean(text, limit):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "…"
    return text


def cats_of(src):
    c = src.get("categorie", "Viral")
    return c if isinstance(c, list) else [c]


STOP = set(
    "the a an and or of to in on for with at by from is are was be as its it this that "
    "new how why what after over into says say will has have you your not but can could "
    "than more just now about out off all his her their".split()
)


def tokens(title):
    words = re.findall(r"[a-z0-9]+", title.lower())
    return {w.rstrip("s") if len(w) > 3 else w for w in words if len(w) > 2 and w not in STOP}


def make_item(title, link, source, cats, when, body="", hn=0.0):
    if not link.startswith(("http://", "https://")):
        return None
    return {
        "title": title,
        "link": link,
        "source": source,
        "cats": cats,
        "when": min(when, NOW),
        "desc": clean(body, 220),
        "text": clean(body, 700),
        "hn": hn,
        "tok": tokens(title),
    }


# ---------------------------------------------------------------- citire surse
def fetch_rss(src):
    feed = feedparser.parse(get(src["url"]).content)
    out = []
    for e in feed.entries[: src.get("max", 40)]:
        t = e.get("published_parsed") or e.get("updated_parsed")
        if not t or not e.get("link") or not e.get("title"):
            continue
        when = datetime.fromtimestamp(calendar.timegm(t), timezone.utc)
        title = clean(e.title, 300)
        name = src["nume"]
        body = e.get("summary", "")
        if src.get("tip") == "google":
            name = (e.get("source") or {}).get("title") or name
            if title.endswith(" - " + name):
                title = title[: -len(" - " + name)]
            body = ""
        it = make_item(title, e.link, name, cats_of(src), when, body)
        if it:
            out.append(it)
    return out


def fetch_hn(src):
    base = "https://hacker-news.firebaseio.com/v0"
    ids = get(f"{base}/topstories.json").json()[: src.get("max", 40)]

    def one(i):
        try:
            return get(f"{base}/item/{i}.json").json()
        except Exception:
            return None

    with ThreadPoolExecutor(8) as ex:
        stories = list(ex.map(one, ids))
    out = []
    for s in stories:
        if not s or s.get("type") != "story" or not s.get("title") or not s.get("time"):
            continue
        when = datetime.fromtimestamp(s["time"], timezone.utc)
        age_h = max((NOW - when).total_seconds() / 3600, 0.5)
        link = s.get("url") or f"https://news.ycombinator.com/item?id={s['id']}"
        it = make_item(s["title"], link, src["nume"], cats_of(src), when, hn=s.get("score", 0) / age_h)
        if it:
            out.append(it)
    return out


def fetch_all(cfg):
    items, errors = [], []
    for src in cfg["surse"]:
        try:
            got = fetch_hn(src) if src.get("tip") == "hn" else fetch_rss(src)
            if not got:
                raise RuntimeError("0 stiri")
            items += got
            print(f"  ok   {src['nume']}: {len(got)}")
        except Exception as ex:  # o sursa picata nu opreste restul
            errors.append(src["nume"])
            print(f"  EROARE {src['nume']}: {ex}")
    return items, errors


# ---------------------------------------------------------------- grupare + scor
def cluster(items, thr):
    groups = []
    for it in sorted(items, key=lambda x: x["when"]):
        tk = it["tok"]
        for g in groups:
            common = len(tk & g["tok"])
            if common >= 3 and common / min(len(tk), len(g["tok"])) >= thr:
                g["items"].append(it)
                break
        else:
            groups.append({"tok": tk, "items": [it]})
    return groups


def compile_words(words):
    return [
        (str(w), pts, re.compile(r"\b" + re.escape(str(w)) + r"(?:s|es|d|ed|ing)?\b", re.I))
        for w, pts in (words or {}).items()
    ]


def build_story(group, cfg, good, bad):
    its = group["items"]
    s = cfg["scor"]
    main = max(its, key=lambda x: (bool(x["desc"]), x["when"]))
    by_src = {}
    for it in its:
        by_src.setdefault(it["source"], it)
    first = min(x["when"] for x in its)
    age_h = (NOW - first).total_seconds() / 3600
    text = " ".join(x["title"] for x in its) + " " + main["text"]

    why = []
    fresh = s["prospetime_max"] * 0.5 ** (age_h / s["prospetime_injumatatire_ore"])
    multi = min((len(by_src) - 1) * s["puncte_per_sursa_extra"], s["surse_max"])
    if len(by_src) > 1:
        why.append(f"{len(by_src)} surse")
    vel = max(x["hn"] for x in its)
    hn = min(vel * s["hn_per_punct_pe_ora"], s["hn_max"])
    if vel >= 1:
        why.append(f"HN {vel:.0f} pct/oră")
    g_hits = [(w, p) for w, p, rx in good if rx.search(text)]
    b_hits = [(w, p) for w, p, rx in bad if rx.search(text)]
    g_pts = min(sum(p for _, p in g_hits), s["cuvinte_bune_max"])
    b_pts = sum(p for _, p in b_hits)
    why += [f"+{w}" for w, _ in g_hits] + [f"−{w}" for w, _ in b_hits]

    cats = []
    for it in its:
        for c in it["cats"]:
            if c not in cats:
                cats.append(c)
    return {
        "t": main["title"],
        "u": main["link"],
        "s": main["source"],
        "d": main["desc"],
        "w": first.isoformat(),
        "sc": max(0, min(100, round(fresh + multi + hn + g_pts - b_pts))),
        "c": cats,
        "o": [{"s": n, "u": it["link"]} for n, it in by_src.items() if it is not main],
        "y": why,
        "_bad": b_pts > 0,
        "_items": its,
    }


# ---------------------------------------------------------------- extragere date (Upcoming)
MON = ["January", "February", "March", "April", "May", "June", "July", "August",
       "September", "October", "November", "December"]
MON_FULL = "|".join(MON)
MON_ANY = "|".join(MON + [m[:3] for m in MON] + ["Sept"])
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
SEASON_END = {"spring": (5, 31), "summer": (8, 31), "fall": (11, 30), "autumn": (11, 30), "winter": (2, 28)}


def month_num(name):
    return [m[:3] for m in MON].index(name[:3]) + 1


def end_of_month(y, m):
    return date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)


def find_date(sent, pub):
    """Intoarce (data, aproximativ, text_gasit) sau None."""
    y = pub.year
    m = re.search(rf"\b({MON_ANY})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(20\d\d))?", sent)
    parts = (m.group(1), m.group(2), m.group(3)) if m else None
    if not m:
        m = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({MON_ANY})\b(?:,?\s+(20\d\d))?", sent)
        parts = (m.group(2), m.group(1), m.group(3)) if m else None
    if parts:
        try:
            dt = date(int(parts[2]) if parts[2] else y, month_num(parts[0]), int(parts[1]))
            if not parts[2] and dt < pub:
                if (pub - dt).days <= 180:
                    return None  # data deja trecuta
                dt = dt.replace(year=y + 1)
            return dt, False, m.group(0)
        except ValueError:
            pass

    low = sent.lower()
    if re.search(r"\btomorrow\b", low):
        return pub + timedelta(days=1), False, "tomorrow"
    m = re.search(rf"\b(?:on|next|this|coming)\s+({'|'.join(DAYS)})\b", sent)
    if m:
        delta = (DAYS.index(m.group(1)) - pub.weekday()) % 7 or 7
        return pub + timedelta(days=delta), False, m.group(0)
    if re.search(r"\bnext week\b", low):
        return pub + timedelta(days=13 - pub.weekday()), True, "next week"
    if re.search(r"\bnext month\b", low):
        return end_of_month(y + (pub.month == 12), pub.month % 12 + 1), True, "next month"
    m = re.search(rf"\b(?:in|by|early|mid|late|until|this|during)[\s-]+({MON_FULL})\b(?:\s+(20\d\d))?", sent)
    if m:
        mo = month_num(m.group(1))
        dt = end_of_month(int(m.group(2)) if m.group(2) else y, mo)
        if not m.group(2) and dt < pub:
            dt = end_of_month(y + 1, mo)
        return dt, True, m.group(0)
    m = re.search(r"\bQ([1-4])\s+(?:of\s+)?(20\d\d)\b", sent)
    if m:
        return end_of_month(int(m.group(2)), int(m.group(1)) * 3), True, m.group(0)
    m = re.search(r"\b(this|next|in|by|early|late|coming)\s+(spring|summer|fall|autumn|winter)\b(?:\s+(?:of\s+)?(20\d\d))?", low)
    if m:
        mo, d = SEASON_END[m.group(2)]
        dt = date(int(m.group(3)) if m.group(3) else y, mo, d)
        if not m.group(3) and (dt < pub or m.group(1) == "next"):
            dt = dt.replace(year=dt.year + 1)
        return dt, True, m.group(0)
    m = re.search(r"later this year|end of (?:the|this) year|year[’'\s-]*s?[\s-]*end|\bthis year\b", low)
    if m:
        return date(y, 12, 31), True, m.group(0)
    if re.search(r"\bnext year\b", low):
        return date(y + 1, 12, 31), True, "next year"
    m = re.search(r"\b(?:in|by|early|mid|late|for|until|during)[\s-]+(20\d\d)\b", low)
    if m:
        return date(int(m.group(1)), 12, 31), True, m.group(0)
    return None


def upcoming_from_news(stories, cfg):
    phrases = cfg["upcoming"].get("fraze") or []
    if not phrases:
        return []
    trig = re.compile(r"\b(?:" + "|".join(re.escape(p) for p in phrases) + r")\b", re.I)
    limit = TODAY + timedelta(days=3 * 365)
    out = []
    for st in stories:
        if st["_bad"]:
            continue
        found = None
        for it in st["_items"]:
            text = it["title"] + ". " + it["text"]
            text = re.sub(rf"\b({MON_ANY})\.", r"\1", text)  # "Nov." -> "Nov"
            for sent in re.split(r"(?<=[.!?…])\s+", text):
                if not trig.search(sent):
                    continue
                res = find_date(sent, it["when"].date())
                if res and TODAY <= res[0] <= limit:
                    found = (res, sent.strip(), it)
                    break
            if found:
                break
        if found:
            (dt, approx, label), sent, it = found
            out.append({
                "t": st["t"], "u": it["link"], "s": it["source"], "c": st["c"],
                "date": dt.isoformat(), "approx": approx, "label": label,
                "phrase": sent[:300], "src": "news",
            })
    return out


def fetch_ll2(cfg):
    up = cfg["upcoming"]
    data = get(
        "https://ll.thespacedevs.com/2.2.0/launch/upcoming/",
        params={"limit": up.get("lansari_spatiale", 40), "hide_recent_previous": "true"},
    ).json()
    skip = [w.lower() for w in up.get("spatiu_ignora") or []]
    out = []
    for l in data.get("results", []):
        name = l.get("name") or ""
        if not l.get("net") or any(w in name.lower() for w in skip):
            continue
        prec = (l.get("net_precision") or {}).get("name") or ""
        status = (l.get("status") or {}).get("abbrev") or ""
        approx = status == "TBD" or (bool(prec) and prec not in ("Second", "Minute", "Hour", "Day"))
        exact_time = prec in ("Second", "Minute", "Hour") and not approx
        place = ((l.get("pad") or {}).get("location") or {}).get("name") or ""
        who = (l.get("launch_service_provider") or {}).get("name") or ""
        mission = clean((l.get("mission") or {}).get("description") or "", 220)
        out.append({
            "t": name,
            "u": f"https://spacelaunchnow.me/launch/{l['slug']}" if l.get("slug") else "https://spacelaunchnow.me/",
            "s": " · ".join(x for x in (who, place) if x),
            "c": ["Spațiu"],
            "date": l["net"] if exact_time else l["net"][:10],
            "approx": approx,
            "label": {"TBD": "dată neconfirmată"}.get(status, prec.lower()) if approx else "",
            "phrase": mission, "src": "ll2",
        })
    return out


def merge_upcoming(new_news, ll2, prev):
    by_link = {e["u"]: e for e in prev if e.get("src") == "news"}
    by_link.update({e["u"]: e for e in new_news})
    if ll2 is None:  # Launch Library a picat: pastram lansarile de data trecuta
        ll2 = [e for e in prev if e.get("src") == "ll2"]
    alive = [e for e in list(by_link.values()) + ll2 if e["date"][:10] >= TODAY.isoformat()]
    alive.sort(key=lambda e: e["date"])
    kept = []
    for e in alive:  # scoatem dublurile (acelasi eveniment, aceeasi zi)
        tk = tokens(e["t"])
        dup = any(
            k["date"][:10] == e["date"][:10] and len(tk & tokens(k["t"])) >= 3
            and len(tk & tokens(k["t"])) / max(1, min(len(tk), len(tokens(k["t"])))) >= 0.6
            for k in kept
        )
        if not dup:
            kept.append(e)
    return kept


# ---------------------------------------------------------------- main
def main():
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    SITE.mkdir(exist_ok=True)
    try:
        prev = json.loads((SITE / "data.json").read_text(encoding="utf-8"))
    except Exception:
        prev = {}

    print("Citesc sursele...")
    items, errors = fetch_all(cfg)
    st = cfg["setari"]
    cutoff = NOW - timedelta(hours=st["max_ore"])
    items = [i for i in items if i["when"] >= cutoff and i["tok"]]

    good, bad = compile_words(cfg.get("cuvinte_bune")), compile_words(cfg.get("cuvinte_rele"))
    stories = [build_story(g, cfg, good, bad) for g in cluster(items, st["prag_asemanare"])]

    print("Upcoming...")
    try:
        ll2 = fetch_ll2(cfg)
        print(f"  ok   Launch Library 2: {len(ll2)}")
    except Exception as ex:
        ll2 = None
        errors.append("Launch Library 2")
        print(f"  EROARE Launch Library 2: {ex}")
    upcoming = merge_upcoming(upcoming_from_news(stories, cfg), ll2, prev.get("upcoming") or [])

    news = [s for s in stories if s["sc"] >= st["scor_minim"]]
    news.sort(key=lambda s: -s["sc"])
    news = [{k: v for k, v in s.items() if not k.startswith("_")} for s in news[: st["max_stiri"]]]
    if not items and prev.get("news"):  # totul a picat: pastram stirile vechi
        news = prev["news"]

    data = {"updated": NOW.isoformat(), "news": news, "upcoming": upcoming, "errors": errors}
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    (SITE / "data.json").write_text(blob, encoding="utf-8")
    page = (ROOT / "template.html").read_text(encoding="utf-8")
    (SITE / "index.html").write_text(page.replace("/*DATA*/null", blob.replace("</", "<\\/")), encoding="utf-8")
    print(f"Gata: {len(news)} stiri, {len(upcoming)} upcoming, {len(errors)} surse picate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
