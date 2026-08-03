#!/usr/bin/env python3
"""
Daily job refresh for the UK / Naija job-tracker dashboards.

Fetches fresh listings from keyless JSON job APIs, filters/scores them with the
same rubric as REFRESH_INSTRUCTIONS.md, and rewrites ONLY the `const JOBS`,
`const LAST_UPDATED` and `const SOURCES` lines in index.html. Everything else in
the file (CSS, CV_BASE / buildCV / downloadCV, SVG icons) is left untouched.

Standard library only. Region is chosen with the TRACKER_REGION env var
("uk" or "ng"); defaults to auto-detect from the working directory.

Runs from a GitHub Actions workflow that commits + pushes the result.
"""

import os
import re
import json
import html
import urllib.request
import urllib.parse
from datetime import datetime, timezone, date

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

TODAY = datetime.now(timezone.utc).date()
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
TIMEOUT = 15
MAX_JOBS = 36          # cap total jobs written
MAX_PER_CAT = 12       # cap per role track so one track can't dominate
MAX_AGE_DAYS = 3       # hard freshness cutoff: anything older than this is wiped

# Skills already on Azeez's CV (used for `have` + scoring). Lowercased match keys
# map to the canonical label shown on the card.
CV_SKILLS = {
    "python": "Python", "typescript": "TypeScript", "pytorch": "PyTorch",
    "tensorflow": "TensorFlow", "scikit-learn": "scikit-learn", "sklearn": "scikit-learn",
    "xgboost": "XGBoost", "sql": "SQL", "fastapi": "FastAPI", "react": "React",
    "next.js": "Next.js", "nextjs": "Next.js", "pandas": "Pandas", "numpy": "NumPy",
    "llm": "LLMs", "large language model": "LLMs", "adversarial": "Adversarial ML",
    "ocr": "OCR", "data visualu": "Data Viz", "data visual": "Data Viz",
    "visualisation": "Data Viz", "visualization": "Data Viz", "rest api": "REST APIs",
    "tailwind": "Tailwind", "git": "Git/GitHub",
}

# In-demand skills NOT on the CV -> used to fill `add` (keyword gaps).
POOL_SKILLS = {
    "docker": "Docker", "kubernetes": "Kubernetes", "aws": "AWS", "gcp": "GCP",
    "azure": "Azure", "sagemaker": "SageMaker", "vertex ai": "Vertex AI",
    "mlops": "MLOps", "ci/cd": "CI/CD", "spark": "Spark", "airflow": "Airflow",
    "kafka": "Kafka", "databricks": "Databricks", "snowflake": "Snowflake",
    "dbt": "dbt", "tableau": "Tableau", "power bi": "Power BI", "powerbi": "Power BI",
    "looker": "Looker", "langchain": "LangChain", "rag": "RAG",
    "hugging face": "Hugging Face", "huggingface": "Hugging Face",
    "a/b test": "A/B testing", "experimentation": "Experimentation",
    "statistics": "Statistics", "nlp": "NLP", "computer vision": "Computer Vision",
    "mlflow": "MLflow",
}
DEFAULT_ADD = {
    "ds": ["Statistics", "A/B testing", "Spark"],
    "mle": ["Docker", "MLOps", "AWS"],
    "da": ["Power BI", "Tableau", "dbt"],
    "ai": ["RAG", "LangChain", "Hugging Face"],
}

SENIOR = re.compile(r"\b(senior|staff|lead|principal|head|director|vp|vice president|"
                    r"chief|snr|sr\.?|manager|architect|iii|iv)\b", re.I)

# The job TITLE must carry a data / ML / analytics / AI signal (TITLE_SIGNAL) and
# must NOT be an explicit off-track role (TITLE_BLOCK). Together these keep genuine
# Data/ML/Analytics/AI roles while dropping generic software-engineering, web, and
# non-technical titles.
TITLE_SIGNAL = re.compile(
    r"(data scien|data analy|data analytics|analytics engineer|business intelligence|"
    r"\bbi analyst\b|\bbi developer\b|machine learning|\bml engineer\b|\bmlops\b|ml ops|"
    r"ai engineer|ai/ml|\bai/ ml\b|ai scientist|applied scientist|research scientist|"
    r"decision scien|data scientist|ai trainer|ai tutor|generative ai|\bgenai\b|"
    r"\bllm\b|\bnlp\b|computer vision|deep learning|prompt engineer|annotation|"
    r"data label|quantitative analyst|quantitative research|quant research|big data)",
    re.I)
TITLE_BLOCK = re.compile(
    r"\b(software engineer|full[- ]?stack|front[- ]?end|back[- ]?end|frontend|backend|"
    r"web developer|web engineer|devops|sre|site reliability|mobile|ios|android|"
    r"product manager|project manager|designer|\bux\b|\bui\b|sales|marketing|recruit|"
    r"account executive|customer success|support engineer|network|security engineer|"
    r"cloud engineer|platform engineer|solutions engineer|qa engineer|test engineer|"
    r"financial analyst|accountant|java engineer)\b", re.I)
JUNIOR = re.compile(r"\b(junior|graduate|grad|entry[- ]?level|intern|internship|"
                    r"trainee|early[- ]?career|associate|apprentice|jnr|jr\.?)\b", re.I)
MID = re.compile(r"\bmid[- ]?level\b", re.I)
PARTTIME = re.compile(r"\b(part[- ]?time|contract|freelance|temporary)\b", re.I)
VISA = re.compile(r"\b(visa|sponsorship|sponsor)\b", re.I)
MISMATCH = re.compile(r"\b(phd required|ph\.d\. required|5\+ years|6\+ years|7\+ years|"
                      r"8\+ years|devops engineer|site reliability|data engineer\b)", re.I)

REGIONS = {
    "uk": {
        "label": "UK",
        "onsite": ["london", "greater london", "city of london", "reading", "slough",
                   "watford", "st albans", "guildford", "brighton", "oxford",
                   "cambridge", "chelmsford", "milton keynes", "maidenhead",
                   "united kingdom", "england", "uk"],
        "remote_ok": ["worldwide", "anywhere", "global", "emea", "europe", "united kingdom",
                      "uk", "eu", "gb", "britain"],
        "muse_locations": ["London, United Kingdom", "Flexible / Remote"],
    },
    "ng": {
        "label": "Nigeria",
        "onsite": ["lagos", "lekki", "ikeja", "victoria island", "abuja", "port harcourt",
                   "ibadan", "nigeria", "yaba", "abeokuta"],
        "remote_ok": ["worldwide", "anywhere", "global", "emea", "africa", "nigeria",
                      "remote"],
        "muse_locations": ["Lagos, Nigeria", "Flexible / Remote"],
    },
}

# Role tracks -> query terms + display category.
TRACKS = [
    ("ds",  "data scientist",            ["data scientist", "data science"]),
    ("mle", "machine learning engineer", ["machine learning engineer", "ml engineer",
                                          "ai engineer", "mlops engineer"]),
    ("da",  "data analyst",              ["data analyst", "analytics", "business intelligence"]),
    ("ai",  "ai trainer llm",            ["ai trainer", "llm", "prompt engineer",
                                          "annotation", "data labelling", "ai tutor"]),
]


def region_key():
    r = os.environ.get("TRACKER_REGION", "").strip().lower()
    if r in REGIONS:
        return r
    cwd = os.getcwd().lower()
    if "naija" in cwd or "-ng" in cwd:
        return "ng"
    return "uk"


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #

def get_json(url, data=None):
    headers = {"User-Agent": UA, "Accept": "application/json"}
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


# --------------------------------------------------------------------------- #
# Text helpers
# --------------------------------------------------------------------------- #

EMOJI = re.compile(
    "[" "\U0001F000-\U0001FAFF" "\U00002600-\U000027BF" "\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF" "\U00002B00-\U00002BFF" "\U0000FE00-\U0000FE0F"
    "\U00002700-\U000027BF" "\U0001F900-\U0001F9FF" "•‍⌨❤" "]+",
    flags=re.UNICODE)


def clean(s):
    """Strip HTML, emojis and em/en dashes; collapse whitespace."""
    if not s:
        return ""
    s = html.unescape(str(s))
    s = re.sub(r"<[^>]+>", " ", s)
    s = EMOJI.sub("", s)
    s = s.replace("—", "-").replace("–", "-").replace("―", "-")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def to_date(val):
    """Parse a date/ISO/epoch value into a date, or None."""
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        try:
            return datetime.fromtimestamp(val, timezone.utc).date()
        except Exception:
            return None
    s = str(val).strip()
    if s.isdigit():
        try:
            return datetime.fromtimestamp(int(s), timezone.utc).date()
        except Exception:
            return None
    s = s.replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
                "%a, %d %b %Y %H:%M:%S %z", "%d %b %Y"):
        try:
            if fmt is None:
                return datetime.fromisoformat(s).date()
            return datetime.strptime(s, fmt).date()
        except Exception:
            continue
    return None


def age_days(d):
    if d is None:
        return None
    return max(0, (TODAY - d).days)


def posted_str(d):
    a = age_days(d)
    if a is None:
        return "recently"
    if a == 0:
        return "today"
    if a == 1:
        return "1 day ago"
    return f"{a} days ago"


# --------------------------------------------------------------------------- #
# Fetchers -> yield normalized records
#   {title, company, location, remote, dt(date|None), url, text, salary, source}
# --------------------------------------------------------------------------- #

def rec(title, company, location, remote, dt, url, text, salary, source):
    return {"title": clean(title), "company": clean(company),
            "location": clean(location) or ("Remote" if remote else ""),
            "remote": bool(remote), "dt": dt, "url": (url or "").strip(),
            "text": (text or ""), "salary": clean(salary), "source": source}


def fetch_muse(region):
    out = []
    cats = ["Data Science", "Data and Analytics", "Software Engineering"]
    for loc in REGIONS[region]["muse_locations"]:
        for cat in cats:
            q = urllib.parse.urlencode({"category": cat, "location": loc, "page": 0})
            try:
                data = get_json(f"https://www.themuse.com/api/public/jobs?{q}")
            except Exception:
                continue
            for j in (data.get("results") or []):
                locs = ", ".join(l.get("name", "") for l in (j.get("locations") or []))
                remote = "remote" in locs.lower() or "flexible" in locs.lower()
                out.append(rec(
                    j.get("name"), (j.get("company") or {}).get("name"), locs, remote,
                    to_date(j.get("publication_date")),
                    (j.get("refs") or {}).get("landing_page"),
                    (j.get("contents") or "") + " " +
                    " ".join(lv.get("name", "") for lv in (j.get("levels") or [])),
                    "", "The Muse"))
    return out


def fetch_arbeitnow():
    out = []
    try:
        data = get_json("https://www.arbeitnow.com/api/job-board-api")
    except Exception:
        return out
    for j in (data.get("data") or []):
        out.append(rec(
            j.get("title"), j.get("company_name"), j.get("location"),
            bool(j.get("remote")), to_date(j.get("created_at")), j.get("url"),
            (j.get("description") or "") + " " + " ".join(j.get("tags") or []) +
            " " + " ".join(j.get("job_types") or []),
            "", "Arbeitnow"))
    return out


def fetch_remotive():
    out = []
    for _cat, q, _terms in TRACKS:
        url = "https://remotive.com/api/remote-jobs?" + urllib.parse.urlencode(
            {"search": q, "limit": 40})
        try:
            data = get_json(url)
        except Exception:
            continue
        for j in (data.get("jobs") or []):
            out.append(rec(
                j.get("title"), j.get("company_name"),
                j.get("candidate_required_location") or "Remote", True,
                to_date(j.get("publication_date")), j.get("url"),
                (j.get("description") or "") + " " + (j.get("job_type") or "") +
                " " + (j.get("category") or ""),
                j.get("salary"), "Remotive"))
    return out


def fetch_jobicy():
    out = []
    for tag in ("data science", "machine learning", "data analyst", "ai"):
        url = "https://jobicy.com/api/v2/remote-jobs?" + urllib.parse.urlencode(
            {"count": 40, "tag": tag})
        try:
            data = get_json(url)
        except Exception:
            continue
        for j in (data.get("jobs") or []):
            sal = ""
            if j.get("annualSalaryMin"):
                cur = j.get("salaryCurrency", "USD")
                sal = f"{cur} {j.get('annualSalaryMin')}-{j.get('annualSalaryMax','')}"
            out.append(rec(
                j.get("jobTitle"), j.get("companyName"), j.get("jobGeo") or "Remote",
                True, to_date(j.get("pubDate")), j.get("url"),
                (j.get("jobExcerpt") or "") + " " +
                " ".join(j.get("jobIndustry") or []) + " " +
                " ".join(j.get("jobType") or []),
                sal, "Jobicy"))
    return out


def fetch_himalayas():
    out = []
    try:
        data = get_json("https://himalayas.app/jobs/api?limit=50")
    except Exception:
        return out
    for j in (data.get("jobs") or []):
        locs = ", ".join(j.get("locationRestrictions") or []) or "Remote"
        out.append(rec(
            j.get("title"), j.get("companyName"), locs, True,
            to_date(j.get("pubDate") or j.get("publishedDate")),
            j.get("applicationLink") or j.get("guid") or j.get("url"),
            (j.get("excerpt") or j.get("description") or "") + " " +
            " ".join(j.get("categories") or []),
            "", "Himalayas"))
    return out


def fetch_remoteok():
    out = []
    try:
        data = get_json("https://remoteok.com/api")
    except Exception:
        return out
    for j in data:
        if not isinstance(j, dict) or not j.get("position"):
            continue
        out.append(rec(
            j.get("position"), j.get("company"), j.get("location") or "Remote", True,
            to_date(j.get("date")), j.get("url") or j.get("apply_url"),
            (j.get("description") or "") + " " + " ".join(j.get("tags") or []),
            j.get("salary_max") and f"${j.get('salary_min','')}-{j.get('salary_max')}" or "",
            "RemoteOK"))
    return out


# --------------------------------------------------------------------------- #
# Filter / classify / score
# --------------------------------------------------------------------------- #

def relevant(title, text):
    t = title or ""
    return bool(TITLE_SIGNAL.search(t)) and not TITLE_BLOCK.search(t)


def classify(title, text):
    b = (title + " " + text).lower()
    if any(k in b for k in ("ai trainer", "ai tutor", "prompt", "annotation",
                            "data label", "llm trainer", "conversation design")):
        return "ai"
    if any(k in b for k in ("machine learning engineer", "ml engineer", "ai engineer",
                            "mlops")):
        return "mle"
    if any(k in b for k in ("data analyst", "business intelligence", "bi analyst",
                            "analytics analyst")):
        return "da"
    if "data scien" in b or "data science" in b:
        return "ds"
    if "machine learning" in b or "deep learning" in b:
        return "mle"
    if "analyst" in b or "analytics" in b:
        return "da"
    if "llm" in b or "nlp" in b:
        return "ai"
    return "ds"


GENERIC_REMOTE = ("", "remote", "anywhere", "worldwide", "global", "flexible",
                  "flexible / remote", "fully remote", "remote worldwide", "100% remote",
                  "remote - anywhere", "anywhere in the world")


def remote_eligible(region, location, text):
    """Eligibility from the LOCATION field only (description scanning is too noisy)."""
    loc = (location or "").lower().strip()
    if loc in GENERIC_REMOTE:
        return True
    for k in REGIONS[region]["remote_ok"]:
        if re.search(r"\b" + re.escape(k) + r"\b", loc):
            return True
    return False


def onsite_match(region, location):
    loc = location.lower()
    return any(city in loc for city in REGIONS[region]["onsite"])


def keep(region, r):
    if not r["title"] or not r["url"]:
        return False
    if not relevant(r["title"], r["text"]):
        return False
    if SENIOR.search(r["title"]):
        return False
    a = age_days(r["dt"])
    if a is not None and a > MAX_AGE_DAYS:
        return False
    if r["remote"]:
        return remote_eligible(region, r["location"], r["text"])
    return onsite_match(region, r["location"])


def score(r, cat):
    blob = (r["title"] + " " + r["text"]).lower()
    s = 50
    if JUNIOR.search(r["title"]) or JUNIOR.search(r["text"][:600]):
        s += 25
    elif MID.search(blob):
        s += 10
    hits = sum(1 for k in CV_SKILLS if k in blob)
    s += min(hits * 3, 25)
    if PARTTIME.search(blob):
        s += 8
    if r["remote"]:
        s += 6
    if cat == "ai":
        s += 10
    if VISA.search(blob):
        s += 10
    if MISMATCH.search(blob):
        s -= 15
    return max(0, min(100, s))


def keywords(r, cat):
    blob = (r["title"] + " " + r["text"]).lower()
    have, seen = [], set()
    for k, label in CV_SKILLS.items():
        if k in blob and label not in seen:
            have.append(label); seen.add(label)
        if len(have) >= 4:
            break
    if not have:
        have = ["Python", "SQL"]
    add, seen = [], set()
    for k, label in POOL_SKILLS.items():
        if k in blob and label not in seen:
            add.append(label); seen.add(label)
        if len(add) >= 3:
            break
    for d in DEFAULT_ADD[cat]:
        if len(add) >= 3:
            break
        if d not in add:
            add.append(d)
    return have[:4], add[:3]


def job_type(r):
    b = (r["title"] + " " + r["text"][:400]).lower()
    if "part-time" in b or "part time" in b:
        return "Part-time"
    if "contract" in b:
        return "Contract"
    if "freelance" in b:
        return "Freelance"
    if "intern" in b:
        return "Internship"
    if "graduate" in b:
        return "Graduate"
    return "Full-time"


# --------------------------------------------------------------------------- #
# Build + splice
# --------------------------------------------------------------------------- #

def build_jobs(region, records):
    seen, jobs = set(), []
    for r in records:
        if not keep(region, r):
            continue
        key = (r["title"].lower(), r["company"].lower())
        if key in seen:
            continue
        seen.add(key)
        cat = classify(r["title"], r["text"])
        have, add = keywords(r, cat)
        a = age_days(r["dt"])
        jobs.append({
            "t": r["title"][:90], "co": r["company"][:60] or "Company",
            "loc": (r["location"][:40] or ("Remote" if r["remote"] else region.upper())),
            "cat": cat, "remote": r["remote"],
            "commutable": (not r["remote"]) and onsite_match(region, r["location"]),
            "type": job_type(r), "posted": posted_str(r["dt"]),
            "age": a if a is not None else 1,
            "salary": r["salary"][:24], "src": r["source"], "url": r["url"],
            "like": score(r, cat), "have": have, "add": add,
        })
    return jobs


JOB_KEYS = ("t", "co", "loc", "cat", "remote", "commutable", "type", "posted",
            "age", "salary", "src", "url", "like", "have", "add")


def parse_existing(src):
    """Best-effort parse of the current `const JOBS = [...]` (handles unquoted keys)."""
    try:
        start, end = find_jobs_block(src)
    except SystemExit:
        return []
    block = src[start:end]
    arr_txt = block[block.index("["):block.rindex("]") + 1]
    # drop whole-line `//` comments (URLs keep their `//` since they are mid-line)
    arr_txt = re.sub(r"(?m)^\s*//.*$", "", arr_txt)
    # quote bare object keys so json can read the seed file's JS-object literals
    arr_txt = re.sub(r"([{,\s])(" + "|".join(JOB_KEYS) + r")\s*:",
                     r'\1"\2":', arr_txt)
    try:
        return json.loads(arr_txt)
    except Exception:
        return []


def last_updated_date(src):
    m = re.search(r'const\s+LAST_UPDATED\s*=\s*"([^"]*)"', src)
    if not m:
        return None
    return to_date(re.sub(r",.*$", "", m.group(1)).strip())  # "3 Aug 2026, .." -> date


def carry_forward(src):
    """Return existing jobs aged forward by days elapsed, pruned at MAX_AGE_DAYS."""
    prev = parse_existing(src)
    lu = last_updated_date(src)
    delta = (TODAY - lu).days if lu else 1
    delta = max(0, delta)
    out = []
    for j in prev:
        if not isinstance(j, dict) or "t" not in j:
            continue
        j = dict(j)
        j["age"] = int(j.get("age", 0) or 0) + delta
        if j["age"] > MAX_AGE_DAYS:
            continue
        j["posted"] = posted_from_age(j["age"])
        # normalise to the known key set (tolerate missing keys)
        for k in JOB_KEYS:
            j.setdefault(k, "" if k in ("salary", "url", "src") else
                         ([] if k in ("have", "add") else ""))
        out.append(j)
    return out


def posted_from_age(a):
    if a <= 0:
        return "today"
    if a == 1:
        return "1 day ago"
    return f"{a} days ago"


def merge(new_jobs, old_jobs):
    """Union new + carried jobs, new wins on dedupe, then cap per cat and overall."""
    by_key = {}
    for j in old_jobs + new_jobs:          # new_jobs last so they overwrite
        by_key[(j["t"].lower(), j["co"].lower())] = j
    merged = list(by_key.values())
    merged.sort(key=lambda j: (j["age"], -j["like"]))
    per, final = {}, []
    for j in merged:
        if per.get(j["cat"], 0) >= MAX_PER_CAT:
            continue
        per[j["cat"]] = per.get(j["cat"], 0) + 1
        final.append(j)
        if len(final) >= MAX_JOBS:
            break
    return final


def js_array(jobs):
    lines = []
    for j in jobs:
        lines.append("  " + json.dumps(j, ensure_ascii=True, separators=(",", ":")))
    return "const JOBS = [\n" + ",\n".join(lines) + "\n];"


def find_jobs_block(src):
    """Return (start, end) span of `const JOBS = [ ... ];` using a string-aware scan."""
    m = re.search(r"const\s+JOBS\s*=\s*\[", src)
    if not m:
        raise SystemExit("could not find `const JOBS = [` in index.html")
    i = src.index("[", m.start())
    depth, j, quote, esc = 0, i, None, False
    while j < len(src):
        c = src[j]
        if quote:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == quote:
                quote = None
        else:
            if c in "\"'`":
                quote = c
            elif c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    k = j + 1
                    while k < len(src) and src[k] in " \t":
                        k += 1
                    if k < len(src) and src[k] == ";":
                        k += 1
                    return m.start(), k
        j += 1
    raise SystemExit("unterminated JOBS array")


def splice(src, jobs, sources_label):
    start, end = find_jobs_block(src)
    src = src[:start] + js_array(jobs) + src[end:]
    stamp = datetime.now(timezone.utc).strftime("%-d %b %Y, %H:%M UTC")
    src = re.sub(r'const\s+LAST_UPDATED\s*=\s*"[^"]*";',
                 f'const LAST_UPDATED = "{stamp}";', src, count=1)
    src = re.sub(r'const\s+SOURCES\s*=\s*\[[^\]]*\];',
                 f'const SOURCES = {sources_label};', src, count=1)
    return src


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main():
    region = region_key()
    path = os.environ.get("INDEX_PATH", "index.html")
    fetchers = [("The Muse", lambda: fetch_muse(region)),
                ("Arbeitnow", fetch_arbeitnow),
                ("Remotive", fetch_remotive),
                ("Jobicy", fetch_jobicy),
                ("Himalayas", fetch_himalayas),
                ("RemoteOK", fetch_remoteok)]
    records, counts = [], {}
    for name, fn in fetchers:
        try:
            got = fn()
        except Exception as e:
            got = []
            print(f"  {name}: ERROR {e}")
        counts[name] = len(got)
        records.extend(got)

    with open(path, encoding="utf-8") as f:
        src = f.read()

    new_jobs = build_jobs(region, records)
    carried = carry_forward(src)
    jobs = merge(new_jobs, carried)

    new_keys = {(j["t"].lower(), j["co"].lower()) for j in new_jobs}
    n_new = sum(1 for j in jobs if (j["t"].lower(), j["co"].lower()) in new_keys)

    # per-source fetch counts + new-kept-per-source (GitHub step summary + stdout)
    new_by_src = {}
    for j in new_jobs:
        new_by_src[j["src"]] = new_by_src.get(j["src"], 0) + 1
    summary = [f"### {REGIONS[region]['label']} refresh - {TODAY.isoformat()}", "",
               "| Source | fetched | new kept |", "|---|---:|---:|"]
    for name, _ in fetchers:
        summary.append(f"| {name} | {counts.get(name,0)} | {new_by_src.get(name,0)} |")
    summary.append(f"| **TOTAL** | {sum(counts.values())} | **{len(new_jobs)}** |")
    summary.append("")
    summary.append(f"Board: **{len(jobs)}** jobs ({n_new} new today, "
                   f"{len(jobs) - n_new} carried forward).")
    report = "\n".join(summary)
    print(report)
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        with open(step, "a") as f:
            f.write(report + "\n")

    # Only bail on a genuine outage (no source returned anything). Low counts are a
    # normal consequence of the 3-day wipe, so we still write them.
    if sum(counts.values()) == 0:
        print("All sources returned nothing (likely a transient outage); "
              "leaving index.html unchanged so the board is not wiped by an API failure.")
        return
    if not jobs:
        print("No jobs <= 3 days old after filtering; leaving index.html unchanged "
              "to avoid an empty board.")
        return

    sources_label = json.dumps([n for n, _ in fetchers], ensure_ascii=True)
    out = splice(src, jobs, sources_label)
    with open(path, "w", encoding="utf-8") as f:
        f.write(out)
    print(f"Wrote {len(jobs)} jobs to {path} ({n_new} new, {len(jobs)-n_new} carried)")


if __name__ == "__main__":
    main()
