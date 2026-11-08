"""Config-driven European job-hunt pipeline.

Stages (see pipeline.py): fetch -> dedupe -> hard-filter -> tier1 score (claude -p)
-> tier2 research/dossier (claude -p) -> tailor resume + cover letter (claude -p) -> email.
"""
__version__ = "0.1.0"
