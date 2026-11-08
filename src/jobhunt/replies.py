"""The reply feedback loop (2026-11-08).

Every job in a newsletter carries a short code, e.g. [K7QX], that never changes. The candidate
replies to the newsletter with the codes of the jobs they applied to:

    K7QX M2XA P9DB

Those become `applied`; every other job from that letter (and from any earlier letter still
waiting for a reply) becomes `skipped`. No reply means nothing changes: the jobs wait. Optional
later lines record outcomes: `interview K7QX`, `rejected M2XA`, `offer P9DB`.

Replies are read over IMAP from the sending account (the reply lands in its inbox), with the same
Gmail app password used for SMTP. Processed Message-IDs are remembered so nothing counts twice.
"""
from __future__ import annotations
import email, hashlib, imaplib, re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"   # no 0/O, 1/I/L: readable in any font
CODE_LEN = 4
OUTCOMES = {"interview": "interview", "rejected": "rejected", "reject": "rejected",
            "offer": "offer", "ghosted": "no_response"}
CODE_RE = re.compile(rf"\b[{ALPHABET}{ALPHABET.lower()}]{{{CODE_LEN}}}\b")


def make_code(job_hash: str, taken: set[str]) -> str:
    """Deterministic 4-character code from the job's hash; salted until unique in the ledger."""
    salt = 0
    while True:
        digest = hashlib.sha1(f"{job_hash}:{salt}".encode()).digest()
        code = "".join(ALPHABET[b % len(ALPHABET)] for b in digest[:CODE_LEN])
        if code not in taken:
            return code
        salt += 1


def ensure_codes(ledger: dict) -> None:
    taken = {e["code"] for e in ledger.values() if e.get("code")}
    for h, e in ledger.items():
        if not e.get("code"):
            e["code"] = make_code(h, taken)
            taken.add(e["code"])


def parse_reply(text: str) -> tuple[list[str], dict[str, str]]:
    """Returns (applied codes, {code: outcome}). Reads only the new text above the quoted letter;
    anything after '#' on a line is ignored."""
    lines = []
    for line in (text or "").splitlines():
        if line.startswith(">") or re.match(r"^\s*On .+ wrote:\s*$", line) or line.strip().startswith("-----"):
            break
        lines.append(line.split("#", 1)[0])
    applied, outcomes = [], {}
    for line in lines:
        words = line.strip().split()
        if not words:
            continue
        verb = words[0].lower().rstrip(":")
        codes = [w.upper() for w in words if CODE_RE.fullmatch(w)]
        if verb in OUTCOMES:
            for c in codes:
                outcomes[c] = OUTCOMES[verb]
        else:
            applied += codes
    return list(dict.fromkeys(applied)), outcomes


def apply_reply(ledger: dict, letter_date: str, applied: list[str], outcomes: dict[str, str],
                reply_date: str) -> dict:
    """Update the ledger from one reply. letter_date: the newsletter it answers (YYYY-MM-DD).
    Returns counts plus any codes that matched nothing."""
    by_code = {e.get("code"): e for e in ledger.values() if e.get("code")}
    res = {"applied": 0, "skipped": 0, "outcomes": 0, "unknown": []}
    for c in applied:
        e = by_code.get(c)
        if not e:
            res["unknown"].append(c)
            continue
        if e.get("status") != "applied":
            e.update(status="applied", applied_on=reply_date)
            res["applied"] += 1
    for c, outcome in outcomes.items():
        e = by_code.get(c)
        if not e:
            res["unknown"].append(c)
            continue
        e.setdefault("applied_on", reply_date)
        e.update(status="applied", outcome=outcome, outcome_on=reply_date)
        res["outcomes"] += 1
    for e in ledger.values():  # everything else this letter (or an earlier one) offered: skipped
        if e.get("status") == "sent" and (e.get("sent_on") or "") <= letter_date:
            e["status"] = "skipped"
            res["skipped"] += 1
    return res


# ---------- IMAP ----------
def _body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
        return ""
    return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", "replace")


def fetch_replies(email_cfg: dict, password: str, since: str, processed: set[str]) -> list[dict]:
    """Unprocessed replies to our newsletters since `since` (YYYY-MM-DD). Each: {msgid, date,
    in_reply_to, text}. Only messages from the newsletter's recipient are read."""
    host = email_cfg.get("imap_host", "imap.gmail.com")
    want_from = (email_cfg.get("to_addr") or "").lower()
    prefix = email_cfg.get("subject_prefix", "[JobHunt]")
    out = []
    imap = imaplib.IMAP4_SSL(host)
    try:
        imap.login(email_cfg["smtp_user"], password)
        imap.select("INBOX", readonly=True)
        since_imap = datetime.fromisoformat(since).strftime("%d-%b-%Y")
        _, data = imap.search(None, f'(SINCE {since_imap} SUBJECT "{prefix}")')
        for num in (data[0] or b"").split():
            _, raw = imap.fetch(num, "(RFC822)")
            msg = email.message_from_bytes(raw[0][1])
            msgid = (msg.get("Message-ID") or "").strip()
            if not msgid or msgid in processed:
                continue
            if want_from and want_from not in (msg.get("From") or "").lower():
                continue  # our own sent newsletter, or someone else
            try:
                date = parsedate_to_datetime(msg.get("Date")).astimezone(timezone.utc).date().isoformat()
            except Exception:
                date = datetime.now(timezone.utc).date().isoformat()
            out.append({"msgid": msgid, "date": date, "text": _body(msg),
                        "in_reply_to": (msg.get("In-Reply-To") or msg.get("References") or "").strip()})
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    return out


def letter_for(reply: dict, letters: list[dict]) -> str | None:
    """Which newsletter a reply answers: by In-Reply-To, else the latest letter sent before it."""
    for lt in letters:
        if lt.get("msgid") and lt["msgid"] in reply.get("in_reply_to", ""):
            return lt["date"]
    earlier = [lt["date"] for lt in letters if lt["date"] <= reply["date"]]
    return max(earlier) if earlier else None
