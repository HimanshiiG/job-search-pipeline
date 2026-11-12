"""Resume Markdown -> LaTeX, in the layout of the candidate's own resume (centered name, small-caps
section rules, company + dates on one line, title + location in italics). Plain code, no LLM.

The .tex goes into each application email so it can be opened in Overleaf (or any LaTeX tool) and
turned into a PDF. Single column, standard headings, real-text contact details, ASCII dates: the
layout an ATS parses cleanly.

Input format (what the presets and the tailor step produce):
  # Name
  headline line            (optional)
  contact | contact | ...
  location line            (optional)
  ## Section
  - **Label:** items       (skills)
  ### Company | Title | Location | Dates
  - bullet (continuation lines indented)
"""
from __future__ import annotations
import re

PREAMBLE = r"""\documentclass[a4paper,10pt]{article}
\usepackage[margin=0.5in,top=0.4in,bottom=0.4in]{geometry}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage{titlesec}
\usepackage{enumitem}
\usepackage[hidelinks]{hyperref}
\usepackage{tabularx}
\pagestyle{empty}
\setlength{\parindent}{0pt}
\titleformat{\section}{\scshape\large}{}{0em}{}[\vspace{-6pt}\rule{\linewidth}{0.4pt}]
\titlespacing*{\section}{0pt}{6pt}{3pt}
\setlist[itemize]{leftmargin=1.2em,itemsep=0pt,topsep=1pt,parsep=0pt}
\newcommand{\entry}[4]{%
  \noindent\begin{tabularx}{\linewidth}{@{}X r@{}}\textbf{#1} & #4 \\ \textit{#2} & \textit{#3}\end{tabularx}\par\vspace{1pt}}
\begin{document}
"""

_SPECIAL = {"&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
            "~": r"\textasciitilde{}", "^": r"\textasciicircum{}", "\\": r"\textbackslash{}"}
_UNICODE = {"–": "-", "—": ", ", "×": "x", "∼": "~", "’": "'", "‘": "'", "“": '"', "”": '"', "…": "...",
            "→": "->", "•": "-", "\u00a0": " "}


def esc(text: str) -> str:
    for u, a in _UNICODE.items():
        text = text.replace(u, a)
    out = "".join(_SPECIAL.get(c, c) for c in text)
    return re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", out)   # **bold** survives escaping (no * in _SPECIAL)


def _link(text: str) -> str:
    """Contact items: e-mail and bare domains become links, shown as plain text (ATS-readable)."""
    t = text.strip()
    if "@" in t:
        return rf"\href{{mailto:{t}}}{{{esc(t)}}}"
    if re.match(r"^(https?://)?[\w.-]+\.(com|io|dev|me|org|net)(/\S*)?$", t):
        url = t if t.startswith("http") else "https://" + t
        return rf"\href{{{url}}}{{{esc(t)}}}"
    return esc(t)


def md_to_tex(md: str) -> str:
    md = re.sub(r"<!--.*?-->", "", md, flags=re.S)
    lines = [l.rstrip() for l in md.splitlines()]
    out, header, in_list = [PREAMBLE], [], False
    i = 0
    # header: name + up to 3 lines before the first section
    while i < len(lines) and not lines[i].startswith("## "):
        if lines[i].strip():
            header.append(lines[i].strip())
        i += 1
    if header:
        name = header[0].lstrip("# ").strip()
        out.append(r"\begin{center}" + "\n" + rf"{{\LARGE\textbf{{{esc(name)}}}}}\\[4pt]" + "\n")
        for h in header[1:]:
            if "|" in h and ("@" in h or "linkedin" in h.lower()):
                out.append(" $|$ ".join(_link(p) for p in h.split("|")) + r"\\" + "\n")
            else:
                out.append(esc(h) + r"\\" + "\n")
        out.append(r"\end{center}" + "\n\\vspace{-8pt}\n")

    def close_list():
        nonlocal in_list
        if in_list:
            out.append(r"\end{itemize}" + "\n")
            in_list = False

    bullet, section_is_skills = None, False
    for line in lines[i:] + [""]:
        stripped = line.strip()
        if bullet is not None and line.startswith("  ") and stripped and not stripped.startswith("- "):
            bullet += " " + stripped
            continue
        if bullet is not None:
            if not in_list:
                out.append(r"\begin{itemize}" + "\n")
                in_list = True
            skill = re.match(r"\*\*(.+?):\*\*\s*(.*)", bullet)
            if skill and section_is_skills:
                out.append(rf"\item[] \textbf{{{esc(skill.group(1))}}}: {esc(skill.group(2))}" + "\n")
            else:
                out.append(rf"\item {esc(bullet)}" + "\n")
            bullet = None
        if stripped.startswith("## "):
            close_list()
            title = stripped[3:].strip()
            section_is_skills = "skill" in title.lower()
            out.append(rf"\section{{{esc(title)}}}" + "\n")
        elif stripped.startswith("### "):
            close_list()
            parts = [p.strip() for p in re.split(r"\s*\|\s*|\s+·\s+|\s+—\s+", stripped[4:])]
            parts += [""] * (4 - len(parts))
            company, title, place, dates = (parts + [""] * 4)[:4]
            out.append(rf"\entry{{{esc(company)}}}{{{esc(title)}}}{{{esc(place)}}}{{{esc(dates)}}}" + "\n")
        elif stripped.startswith("- "):
            bullet = stripped[2:]
        elif stripped:
            close_list()
            row = [p.strip() for p in stripped.split("|")]
            if len(row) == 4 and re.search(r"\d{4}", row[3]):   # education line in the presets' format
                out.append(rf"\entry{{{esc(row[0])}}}{{{esc(row[1])}}}{{{esc(row[2])}}}{{{esc(row[3])}}}" + "\n")
            elif out[-1].endswith(PARA):                      # continue the same paragraph
                out[-1] = out[-1][:-len(PARA)] + " " + esc(stripped) + PARA
            else:
                out.append(esc(stripped) + PARA)
    close_list()
    out.append(r"\end{document}" + "\n")
    return "".join(out).replace(PARA, "\n\n")


PARA = "%para\n"
