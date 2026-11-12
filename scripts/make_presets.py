"""Build the 3 general-purpose resume presets as LaTeX (+ PDF when a LaTeX engine is available).

Fills each preset's {{HEADLINE}} / {{LOCATION_LINE}} with general values (tailored applications fill
them per job instead). Output: output/presets/<label>.tex and .pdf (private: output/ is gitignored).

Usage:  py scripts/make_presets.py [--tectonic PATH]
"""
from __future__ import annotations
import argparse, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from jobhunt import latex  # noqa: E402
from jobhunt.config import Config  # noqa: E402

HEADLINES = {
    "data-engineer": "Data Engineer | Streaming & CDC | Kafka, Snowflake, Kubernetes",
    "data-platform": "Data Platform Engineer | Streaming & CDC | Kafka Connect, Kubernetes, GitOps",
    "ai-data": "Data Engineer | LLM Systems & Streaming Data | Kafka, Snowflake, LLM Agents",
}
GENERAL_LOCATION = "Mumbai, India | Open to relocation | EU Blue Card eligible"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tectonic", default=shutil.which("tectonic"))
    args = ap.parse_args()
    profile = Config().profile
    out = ROOT / "output" / "presets"
    out.mkdir(parents=True, exist_ok=True)
    for p in profile.get("resume_presets") or profile.get("resumes") or []:
        md = (ROOT / p["path"]).read_text(encoding="utf-8")
        md = md.replace("{{HEADLINE}}", HEADLINES.get(p["label"], "Data Engineer")).replace(
            "{{LOCATION_LINE}}", GENERAL_LOCATION)
        who = (profile.get("name") or "Resume").replace(" ", "_")
        tex = out / f"{who}_{p['label'].replace('-', '_').title()}.tex"
        tex.write_text(latex.md_to_tex(md), encoding="utf-8")
        status = "tex only"
        if args.tectonic:
            r = subprocess.run([args.tectonic, "-X", "compile", "--keep-logs", str(tex)], capture_output=True, text=True)
            status = "pdf ok" if r.returncode == 0 else f"pdf FAILED: {r.stderr[-400:]}"
        print(f"{tex.name}: {status}")


if __name__ == "__main__":
    main()
