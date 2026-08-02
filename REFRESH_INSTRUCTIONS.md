# Daily Refresh Instructions - UK Job Tracker

You are a scheduled cloud agent. Your job: rebuild `index.html` in this repo with fresh UK job
listings for **Azeez Aleem** (Data Scientist / ML Engineer, junior-mid level), then commit & push so
GitHub Pages redeploys. Work only inside this repo. Keep the entire design/CSS/JS of `index.html`
unchanged. **Only** replace the `const JOBS = [ ... ];` array and the `const LAST_UPDATED = "...";`
line. In particular, DO NOT modify the `CV_BASE` object or the `buildCV` / `downloadCV` functions
(the per-job CV optimiser); leave that whole block exactly as-is. Never use em dashes anywhere.

## 0. Candidate profile (for scoring + keyword gaps)
CV skills he ALREADY has: Python, TypeScript, SQL, PyTorch, TensorFlow, scikit-learn, XGBoost, Pandas,
NumPy, FastAPI, REST APIs, React, Next.js, Tailwind, Git/GitHub, LLM application dev, Adversarial ML,
OCR, Data Analysis & Visualization. He is doing an MSc (Control & Optimization) at Imperial College
London. Targets: **junior / mid / graduate / early-career**. He wants part-time & remote first.

## 1. Collect jobs (6 sources)
For EACH of the 4 role tracks, collect listings (title, company, location, posted date, salary if
shown, detail URL). Role tracks: **Data Scientist, Machine Learning Engineer / AI Engineer, Data
Analyst, AI Trainer / LLM**.

**Indeed (use the Indeed MCP tool `search_jobs` FIRST if it is available to you).** Call it with
`country_code:"GB"` for each role track, once with `location:"London"` and once with
`location:"remote"`. Keep the `View Job URL` (the `to.indeed.com/...` link) intact as the job `url`
and set `src:"Indeed"`. If the Indeed tool is not available in this run, skip it and continue with the
web sources below (do not fail the run).

**Web sources (use the WebFetch tool):**
- **Jooble** (freshest; has recency param `date=2` = last 2 days):
  `https://uk.jooble.org/SearchResult?ukw=<ROLE>&date=3`
- **LinkedIn** (`f_TPR=r172800` = last 48h):
  `https://www.linkedin.com/jobs/search?keywords=<ROLE>&location=United%20Kingdom&f_TPR=r172800`
- **aijobs.net** (AI/ML specialist): `https://aijobs.net/?reg=6&loc=London`
- **Reed**: `https://www.reed.co.uk/jobs/<role-hyphenated>-jobs-in-london`
- **Himalayas** (remote): `https://himalayas.app/jobs?search=<ROLE>`

If any source returns 403/timeout/empty or is unavailable, skip it silently and continue (record it as
"checked · 0 today").

## 2. Filter
- **Location rule:** keep ALL remote/"UK"/"anywhere" jobs. For on-site jobs keep ONLY London or
  commutable hubs: Greater London, City of London, Reading, Slough, Watford, St Albans, Guildford,
  Brighton, Oxford, Cambridge, Chelmsford, Milton Keynes, Maidenhead. DROP on-site jobs elsewhere
  (Manchester, Leeds, Bristol, Liverpool, Edinburgh, Cardiff, etc.).
- **Seniority:** DROP clearly senior roles (title contains Senior, Staff, Lead, Principal, Head,
  Director, VP). Keep junior/mid/graduate/early-career/associate and untitled-level.
- **Freshness:** prefer posted ≤ 2 days, but KEEP older matches too (the UI badges their age). Skip
  anything older than ~35 days (likely closed).
- **Dedupe** across sources by title+company; keep the copy with a real posted date + working URL.
- Aim for ~25-40 good jobs total, spread across the 4 tracks.

## 3. Compute fields for each job
Convert posted date to `age` in whole days from today (UTC). "X hours ago" / "today" → 0.
`remote:true` if remote/anywhere/UK-wide. `commutable:true` if London or a hub above.
`type`: Full-time / Part-time / Contract / Freelance / Graduate / Permanent as stated.

### Likelihood score (integer 0-100)
Start at 50, then:
- +25 junior/graduate/entry/early-career · +10 mid-level
- +3 per CV skill the job clearly wants (cap +25)
- +8 part-time/contract/freelance · +6 remote · +10 AI-trainer/annotation/LLM-labelling (low barrier)
- +10 if it mentions visa sponsorship
- −15 heavy mismatch (pure data-engineering/DevOps, or "PhD required" / "5+ yrs")
Clamp 0-100. Band is derived in the UI: ≥70 High, 45-69 Medium, <45 Low.

### Keywords
- `have`: 3-4 CV skills this job values (from section 0).
- `add`: 2-3 in-demand skills the job wants that are NOT on his CV. Common pool: Docker, Kubernetes,
  AWS/GCP/Azure, SageMaker/Vertex AI, MLOps, CI/CD, Spark, Airflow, Kafka, Databricks, Snowflake, dbt,
  Tableau, Power BI, Looker, LangChain, RAG, Hugging Face, A/B testing, Experimentation, Statistics,
  NLP, Computer Vision, MLflow.

## 4. Write the job object (exact schema - match existing file)
```js
{t:"Title",co:"Company",loc:"London",cat:"ds|mle|da|ai",remote:false,commutable:true,
 type:"Full-time",posted:"1 day ago",age:1,salary:"£50k" or "-",src:"Jooble|LinkedIn|Reed|aijobs.net|Himalayas",
 url:"https://…direct apply/detail link…",like:72,have:["Python","SQL"],add:["Docker","MLOps"]}
```
`cat` mapping: Data Scientist→`ds`, ML/AI Engineer→`mle`, Data Analyst→`da`, AI Trainer/LLM→`ai`.
Keep every `url` intact (do not strip query params). If you only have a board search URL for a source
(e.g. aijobs.net), use that as the `url`.

## 5. Update index.html
- Replace the whole `const JOBS = [ ... ];` block with the new array.
- Set `const LAST_UPDATED = "<D Mon YYYY, HH:MM> UTC";` to today.
- Leave `SOURCES`, all CSS, and all functions unchanged.
- Sanity-check: the file still opens (balanced brackets), and tab counts add up.

## 6. Commit & push
```
git add index.html
git -c user.email="telaleem01@gmail.com" -c user.name="Azeez Aleem" commit -m "Daily refresh: UK job listings $(date -u +%Y-%m-%d)"
git push origin main
```
GitHub Pages redeploys automatically within ~1 minute → https://azleem01.github.io/uk-job-tracker/
