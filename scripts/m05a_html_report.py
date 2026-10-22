"""Build an offline, static comparison report for the M05A evaluation."""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CASE_FILES = {
    "original": ROOT / "docs/milestones/M05A/cases.jsonl",
    "unseen": ROOT / "docs/milestones/M05A/unseen-cases.jsonl",
}
MODEL_SOURCES = (
    (
        "local",
        "Local Qwen3.5 9B Q4_K_M",
        "qwen-full-v2-20261022",
        "qwen-unseen-v2-20261022",
    ),
    ("groq-qwen", "Groq Qwen3.8 27B", "groq-qwen3.8-27b-v2-requests-20261022", None),
    ("groq-gpt", "Groq GPT-OSS 120B", "groq-gpt-oss-120b-v2-requests-20261022", None),
)
REVIEW_PATH = ROOT / "docs/milestones/M05A/groq-semantic-review.md"
LOCAL_REVIEW_PATH = ROOT / "docs/milestones/M05A/prompt-refinement.md"
OUTPUT = ROOT / "private/m05a/model-comparison.html"

# These IDs and descriptions are transcribed from the M05A v2 case-level
# semantic review. They are review notes, not automated model assessments.
LOCAL_CRITICAL = {
    "sv-01",
    "sv-02",
    "sv-03",
    "sv-04",
    "sv-05",
    "sv-08",
    "sv-09",
    "ru-01",
    "ru-02",
    "mix-04",
    "en-03",
    "en-11",
    "ru-03",
    "mix-02",
    "mix-03",
    "perf-medium",
    "perf-long",
    "u-sv-negation",
    "u-ru-complaint",
    "u-ru-uncertain",
}
LOCAL_AMBIGUOUS = {"en-01", "en-02", "en-08", "mix-01"}
LOCAL_FINDINGS = {
    "sv-01": "Critical: Swedish output switched to English without a translation request.",
    "sv-02": "Critical: Swedish output switched to English without a translation request.",
    "sv-03": "Critical: Swedish output switched to English without a translation request; v2 fixed the earlier negation reversal.",
    "sv-04": "Critical: Swedish output switched to English without a translation request.",
    "sv-05": "Critical: switched to English; also adds an unsupported day and mistranslates the host reference.",
    "sv-08": "Critical: Swedish output switched to English without a translation request.",
    "sv-09": "Critical: switched to English and adds “minor issue” while preserving rejection of “resolved.”",
    "ru-01": "Critical: Russian output switched to English without a translation request.",
    "ru-02": "Critical: Russian output switched to English without a translation request.",
    "mix-04": "Critical: multilingual input collapsed into Swedish without a translation request.",
    "en-03": "Critical: weakens “ignored” to “did not address,” changing the criticism's implication.",
    "en-11": "Critical: changes first-person unconfirmed status into confirmation not received.",
    "ru-03": "Critical: changes clients receiving an incorrect price into clients being billed an incorrect price; Russian is also ungrammatical.",
    "mix-02": "Critical: changes identifier v2.8 and translates healthz into generic wording.",
    "mix-03": "Critical: rewrites identifier deploy-17 as a generic deployment/version phrase.",
    "perf-medium": "Critical: changes “checked” to “verified,” overstating the verification status.",
    "perf-long": "Critical: adds UTC to a deadline that had no time zone in the input.",
    "u-sv-negation": "Critical: Swedish output switched to English without a translation request.",
    "u-ru-complaint": "Critical: replaces the complaint with an invented service-provider response and added commitments.",
    "u-ru-uncertain": "Critical: strengthens “probably related” to “most likely caused by” and adds details.",
    "en-01": "Judgment: “a disaster” becomes “highly problematic,” reducing complaint intensity.",
    "en-02": "Judgment: equivalent date format; v2 adds an actor not explicit in the input.",
    "en-08": "Judgment: “I think” becomes “appears,” changing grammatical viewpoint.",
    "mix-01": "Judgment: “rejection” changes to “failure,” a potentially material nuance.",
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{number}: invalid JSON: {exc}") from exc
    return rows


def unique_index(
    rows: list[dict[str, Any]], id_key: str, source: str
) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        case_id = row.get(id_key)
        if not isinstance(case_id, str) or not case_id:
            raise ValueError(f"{source}: row has no valid {id_key}")
        if case_id in indexed:
            raise ValueError(f"{source}: duplicate case ID {case_id}")
        indexed[case_id] = row
    return indexed


def _groq_findings() -> dict[str, dict[str, dict[str, str]]]:
    text = REVIEW_PATH.read_text(encoding="utf-8")
    findings: dict[str, dict[str, dict[str, str]]] = {"groq-qwen": {}, "groq-gpt": {}}
    for line in text.splitlines():
        if not line.startswith("|") or "|---" in line or "Case |" in line:
            continue
        cols = [part.strip() for part in line.strip().strip("|").split("|")]
        if len(cols) != 3 or not re.fullmatch(r"`?[-a-z0-9]+`?", cols[0]):
            continue
        case_id = cols[0].strip("`")
        for model_key, cell in zip(("groq-qwen", "groq-gpt"), cols[1:]):
            clean = re.sub(r"\*\*|`", "", cell).strip()
            if not clean or clean in {"—", "-"}:
                continue
            categories = []
            if re.search(r"\bCritical\b", clean, re.I):
                categories.append("critical")
            if re.search(r"\b(?:Judgment|Ambiguous)\b", clean, re.I):
                categories.append("ambiguous")
            if re.search(r"\bMinor\b", clean, re.I):
                categories.append("minor")
            category = categories[0] if categories else "no documented issue"
            # The case table is the source of association; skip other tables.
            if category != "no documented issue" or re.search(
                r"no (?:confirmed )?issue|no meaning issue|no clear meaning failure",
                clean,
                re.I,
            ):
                findings[model_key][case_id] = {
                    "category": category,
                    "categories": categories or [category],
                    "text": clean,
                }
    # The review explicitly documents this minor finding outside its case table.
    findings["groq-gpt"]["en-13-politeness-complaint"] = {
        "category": "minor",
        "categories": ["minor"],
        "text": "Minor: adds an explicit correction request consistent with polite mode, although the input did not phrase a direct request.",
    }
    return findings


def _local_finding(case_id: str, assessed: bool) -> dict[str, str]:
    critical_key = next(
        (
            key
            for key in LOCAL_CRITICAL
            if case_id == key or case_id.startswith(key + "-")
        ),
        None,
    )
    if critical_key:
        categories = ["critical"]
        if critical_key in LOCAL_AMBIGUOUS or case_id in {
            "mix-02-sv-en",
            "perf-long",
        }:
            categories.append("ambiguous")
        return {
            "category": "critical",
            "categories": categories,
            "text": LOCAL_FINDINGS.get(
                critical_key, "Critical: documented language-preservation failure."
            ),
        }
    ambiguous_key = next(
        (
            key
            for key in LOCAL_AMBIGUOUS
            if case_id == key or case_id.startswith(key + "-")
        ),
        None,
    )
    if ambiguous_key:
        return {
            "category": "ambiguous",
            "categories": ["ambiguous"],
            "text": LOCAL_FINDINGS[ambiguous_key],
        }
    if assessed:
        return {
            "category": "no documented issue",
            "categories": ["no documented issue"],
            "text": "No individual issue recorded in the v2 case review.",
        }
    return {
        "category": "not individually assessed",
        "categories": ["not individually assessed"],
        "text": "Not individually assessed",
    }


def load_report_data(root: Path = ROOT) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for corpus, path in CASE_FILES.items():
        source_path = root / path.relative_to(ROOT)
        for case in read_jsonl(source_path):
            item = dict(case)
            item["corpus"] = corpus
            cases.append(item)
    case_index = unique_index(cases, "id", "source corpus")
    result_indices: dict[str, dict[str, dict[str, Any]]] = {}
    for model_key, _label, original_dir, unseen_dir in MODEL_SOURCES:
        result_indices[model_key] = {}
        sources = (
            [("all", original_dir)]
            if unseen_dir is None
            else [("original", original_dir), ("unseen", unseen_dir)]
        )
        for corpus, dirname in sources:
            rows = read_jsonl(root / "private/m05a" / dirname / "results.jsonl")
            indexed = unique_index(rows, "case_id", dirname)
            for case_id, result in indexed.items():
                if case_id not in case_index:
                    raise ValueError(f"{dirname}: response for unknown case {case_id}")
                expected = case_index[case_id]
                if corpus != "all" and expected["corpus"] != corpus:
                    raise ValueError(
                        f"{dirname}: case {case_id} belongs to the wrong corpus"
                    )
                transform = result.get("transformation", {})
                for field in (
                    "input_language",
                    "mode",
                    "formatting",
                    "target_language",
                    "text",
                ):
                    if transform.get(field) != expected.get(field):
                        raise ValueError(
                            f"{dirname}: source {field} mismatch for {case_id}"
                        )
                result_indices[model_key][case_id] = result
    groq_reviews = _groq_findings()
    original_ids = {case["id"] for case in cases if case["corpus"] == "original"}
    unseen_ids = {case["id"] for case in cases if case["corpus"] == "unseen"}
    local_assessed = original_ids | unseen_ids
    for case in cases:
        case["models"] = {}
        for model_key, label, *_ in MODEL_SOURCES:
            result = result_indices[model_key].get(case["id"])
            if model_key == "local":
                review = _local_finding(case["id"], case["id"] in local_assessed)
            else:
                review = groq_reviews[model_key].get(
                    case["id"],
                    {
                        "category": "not individually assessed",
                        "categories": ["not individually assessed"],
                        "text": "Not individually assessed",
                    },
                )
            timing = (result or {}).get("timing", {})
            latency = timing.get("request_seconds", timing.get("wall_clock_seconds"))
            case["models"][model_key] = {
                "label": label,
                "response": (result or {}).get("response"),
                "latency": latency,
                "finding": review,
                "error": (result or {}).get("error"),
            }
    return cases


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def case_html(case: dict[str, Any]) -> str:
    model_html = []
    for key, _label, *_ in MODEL_SOURCES:
        model = case["models"][key]
        finding = model["finding"]
        latency = (
            f" · {model['latency']:.2f}s"
            if isinstance(model["latency"], (int, float))
            else ""
        )
        response = model["response"]
        response_html = (
            esc(response) if response is not None else "No response available"
        )
        model_html.append(
            f'<section class="model {esc(key)}"><header><h3>{esc(model["label"])}</h3>'
            f'<button type="button" class="copy" data-copy="response-{esc(case["id"])}-{esc(key)}">Copy</button></header>'
            f'<div class="finding {esc(finding["category"].replace(" ", "-"))}"><strong>{esc(finding["category"].title())}</strong>'
            f'<p>{esc(finding["text"])}</p></div><pre id="response-{esc(case["id"])}-{esc(key)}">{response_html}</pre>'
            f"<small>Latency{esc(latency) if latency else ': unavailable'}</small></section>"
        )
    target = case.get("target_language") or "No translation"
    language = (
        "Mixed-language"
        if "+" in case["input_language"]
        else {"en": "English", "sv": "Swedish", "ru": "Russian"}.get(
            case["input_language"], case["input_language"]
        )
    )
    searchable = " ".join((case["id"], case["text"], case["review_constraints"]))
    return (
        f'<article class="case" data-id="{esc(case["id"])}" data-language="{esc(language)}" '
        f'data-mode="{esc(case["mode"])}" data-format="{esc(case["formatting"])}" '
        f'data-translation="{"yes" if case.get("target_language") else "no"}" '
        f'data-corpus="{esc(case["corpus"])}" data-search="{esc(searchable.casefold())}" '
        f'data-status="{esc("|".join(category for m in case["models"].values() for category in m["finding"]["categories"]))}">'
        f'<details open><summary><span class="case-id">{esc(case["id"])}</span> · {esc(case["mode"])} · {esc(case["formatting"])} · {esc(target)}</summary>'
        f'<div class="case-meta"><span>{esc(language)}</span><span>{esc("Unseen regression corpus" if case["corpus"] == "unseen" else "Original corpus")}</span></div>'
        f'<section class="source"><h3>Original input</h3><pre>{esc(case["text"])}</pre>'
        f"<h4>Expected preservation constraints</h4><p>{esc(case['review_constraints'])}</p></section>"
        f'<div class="models">{"".join(model_html)}</div></details></article>'
    )


def build_html(cases: list[dict[str, Any]]) -> str:
    groups: dict[str, list[dict[str, Any]]] = {
        name: [] for name in ("English", "Swedish", "Russian", "Mixed-language")
    }
    for case in cases:
        language = (
            "Mixed-language"
            if "+" in case["input_language"]
            else {"en": "English", "sv": "Swedish", "ru": "Russian"}.get(
                case["input_language"], "English"
            )
        )
        groups[language].append(case)
    group_html = "".join(
        f'<details class="language-group" open><summary>{name} <span>({len(items)})</span></summary>'
        f'<div class="group-cases">{"".join(case_html(item) for item in items)}</div></details>'
        for name, items in groups.items()
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>M05A model comparison</title><style>
:root{{font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;color:#202833;background:#f4f6f8}}*{{box-sizing:border-box}}body{{margin:0}}header.top{{background:#172637;color:white;padding:1.25rem max(1rem,calc((100vw - 1500px)/2))}}main{{max-width:1500px;margin:auto;padding:1rem}}h1{{font-size:1.5rem;margin:0}}.notice{{margin:.3rem 0 0;color:#dce6ef}}.filters{{position:sticky;top:0;background:#fff;border:1px solid #d5dce3;border-radius:10px;padding:1rem;z-index:2;box-shadow:0 3px 12px #1b2b3915}}.filter-grid{{display:flex;flex-wrap:wrap;gap:.65rem;align-items:end}}label{{display:grid;gap:.2rem;font-size:.82rem;color:#45515d}}input,select,button{{font:inherit;padding:.45rem .6rem;border:1px solid #b9c3cc;border-radius:6px;background:white;color:inherit}}input[type=search]{{min-width:240px}}button{{cursor:pointer}}#count{{font-weight:650;margin:.75rem 0 0}}.language-group{{margin:1rem 0}}.language-group>summary{{position:sticky;top:130px;background:#e7edf2;padding:.65rem .8rem;border-radius:7px;font-size:1.1rem;font-weight:700;cursor:pointer;z-index:1}}.group-cases{{padding:.35rem 0}}.case{{margin:.8rem 0;border:1px solid #d4dce3;border-radius:9px;background:white;overflow:hidden}}.case>details>summary{{padding:.75rem 1rem;background:#fbfcfd;font-weight:600;cursor:pointer}}.case-id{{font-family:ui-monospace,monospace}}.case-meta{{display:flex;gap:.5rem;padding:.5rem 1rem 0}}.case-meta span{{font-size:.8rem;background:#edf1f4;padding:.15rem .5rem;border-radius:20px}}.source{{margin:.5rem 1rem 1rem;padding:1rem;border-left:4px solid #405b74;background:#f7f9fb;border-radius:4px}}h3,h4,p{{margin:.15rem 0 .45rem}}.source pre,.model pre{{white-space:pre-wrap;overflow-wrap:anywhere;font: .95rem/1.55 ui-monospace,"SFMono-Regular",Consolas,monospace;margin:.35rem 0}}.source pre{{font-size:1rem}}.models{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.75rem;padding:0 1rem 1rem}}.model{{min-width:0;border:1px solid #d7dfe6;border-radius:8px;padding:.8rem;background:#fff}}.model header{{display:flex;justify-content:space-between;align-items:center;gap:.4rem;margin-bottom:.6rem}}.model h3{{font-size:1rem}}.model.local{{border-top:4px solid #557d9e}}.model.groq-qwen{{border-top:4px solid #548675}}.model.groq-gpt{{border-top:4px solid #927aa9}}.finding{{padding:.5rem .6rem;border-radius:5px;background:#f0f3f5;margin-bottom:.65rem;font-size:.88rem}}.finding p{{margin:.15rem 0 0}}.finding.critical{{background:#fbe9e7;color:#70251f}}.finding.minor{{background:#fff3d8;color:#664b0b}}.finding.ambiguous{{background:#e9eef9;color:#273d69}}.finding.not-individually-assessed{{background:#f0f0f0;color:#454545}}small{{color:#596672}}.hidden{{display:none!important}}@media(max-width:900px){{.models{{grid-template-columns:1fr}}.language-group>summary{{top:180px}}}}@media(max-width:600px){{main{{padding:.6rem}}.filters{{position:static}}.filter-grid>*{{flex:1 1 145px}}input[type=search]{{min-width:0;width:100%}}.language-group>summary{{position:static}}}}
</style></head><body><header class="top"><h1>M05A model comparison</h1><p class="notice">Synthetic evaluation data · documented findings are human review notes, not pass/fail scores. No documented failure does not establish a pass.</p></header><main>
<section class="filters"><div class="filter-grid"><label>Search cases<input id="search" type="search" placeholder="Case ID or input text"></label>
<label>View<select id="view"><option value="all">All cases</option><option value="critical">Documented critical failures</option><option value="judgment">Requires operator judgment</option></select></label>
<label>Mode<select id="mode"><option value="">All modes</option><option>raw</option><option>written</option><option>polite</option><option>diplomatic</option></select></label>
<label>Formatting<select id="format"><option value="">All formats</option><option>normal</option><option>concise</option><option>structured</option></select></label>
<label>Translation<select id="translation"><option value="">Any</option><option value="yes">Requested</option><option value="no">Not requested</option></select></label>
<label>Corpus<select id="corpus"><option value="">All corpora</option><option value="original">Original</option><option value="unseen">Unseen regression</option></select></label>
<label>Semantic finding<select id="status"><option value="">Any status</option><option value="critical">Critical</option><option value="minor">Minor</option><option value="ambiguous">Ambiguous</option><option value="no documented issue">No documented issue</option></select></label>
<button id="reset" type="button">Reset</button></div><div id="count" aria-live="polite"></div></section>
<section id="groups">{group_html}</section></main><script>
(()=>{{const qs=s=>document.querySelector(s), cases=[...document.querySelectorAll('.case')], groups=[...document.querySelectorAll('.language-group')];
function update(){{let n=0;for(const c of cases){{const d=c.dataset,s=qs('#search').value.trim().toLocaleLowerCase();const finding=d.status.split('|');const view=qs('#view').value;
const viewOk=view==='all'||(view==='critical'?finding.includes('critical'):finding.some(x=>x==='ambiguous'||x==='not individually assessed'));
const ok=(!s||d.search.includes(s)||d.id.toLocaleLowerCase().includes(s))&&(!qs('#mode').value||d.mode===qs('#mode').value)&&(!qs('#format').value||d.format===qs('#format').value)&&(!qs('#translation').value||d.translation===qs('#translation').value)&&(!qs('#corpus').value||d.corpus===qs('#corpus').value)&&(!qs('#status').value||finding.includes(qs('#status').value))&&viewOk;
c.classList.toggle('hidden',!ok);if(ok)n++}}for(const g of groups)g.classList.toggle('hidden',![...g.querySelectorAll('.case')].some(c=>!c.classList.contains('hidden')));qs('#count').textContent=`${{n}} matching cases`}}
document.querySelectorAll('.filters input,.filters select').forEach(x=>x.addEventListener('input',update));qs('#reset').addEventListener('click',()=>{{document.querySelectorAll('.filters input,.filters select').forEach(x=>x.value='');update()}});
document.addEventListener('click',async e=>{{const b=e.target.closest('[data-copy]');if(!b)return;const el=document.getElementById(b.dataset.copy);if(el&&el.textContent!=='No response available'){{await navigator.clipboard.writeText(el.textContent);b.textContent='Copied';setTimeout(()=>b.textContent='Copy',900)}}}});update()}})();
</script></body></html>"""


def generate(root: Path = ROOT, output: Path | None = None) -> tuple[int, int, Path]:
    cases = load_report_data(root)
    destination = output or (root / "private/m05a/model-comparison.html")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(build_html(cases), encoding="utf-8")
    responses = sum(
        model["response"] is not None
        for case in cases
        for model in case["models"].values()
    )
    return len(cases), responses, destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    count, responses, path = generate(output=args.output)
    print(f"Generated {path}: {count} cases, {responses} model responses")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
