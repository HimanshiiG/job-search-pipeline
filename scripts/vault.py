"""Encrypt / decrypt the private parts of this public repo with one key (Fernet: AES + HMAC).

What's private: the candidate profile and resumes (profiles/), the LinkedIn connections export,
config/private.yaml (profile id, email addresses), CLAUDE.md (the project brief) and pilot/
(past letters). They are gitignored; `vault/private.bin` is the committed, encrypted copy.
The pipeline's state (seen jobs, ledger, replies) is encrypted the same way on the bot-only
`jobhunt-state` branch, so the public can't see what was applied to.

Key: env JOBHUNT_VAULT_KEY (GitHub secret in CI; `.env` locally). Create one with `keygen`.

  py scripts/vault.py keygen             print a new key (store it as JOBHUNT_VAULT_KEY)
  py scripts/vault.py seal               private files -> vault/private.bin   (run after editing them)
  py scripts/vault.py unseal             vault/private.bin -> private files
  py scripts/vault.py seal-state DIR     DIR/*.json -> DIR/state.bin (and removes the plain files)
  py scripts/vault.py unseal-state DIR   DIR/state.bin -> DIR/*.json
"""
from __future__ import annotations
import io, os, sys, tarfile
from pathlib import Path

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ["profiles", "config/private.yaml", "CLAUDE.md", "pilot"]
VAULT = ROOT / "vault" / "private.bin"


def _key() -> bytes:
    k = os.environ.get("JOBHUNT_VAULT_KEY")
    if not k and (ROOT / ".env").exists():
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("JOBHUNT_VAULT_KEY="):
                k = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not k:
        sys.exit("JOBHUNT_VAULT_KEY is not set (env or .env)")
    return k.encode()


def _pack(paths: list[Path], base: Path) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for p in paths:
            if p.exists():
                tar.add(p, arcname=str(p.relative_to(base)).replace("\\", "/"))
    return buf.getvalue()


def _unpack(blob: bytes, base: Path) -> list[str]:
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        members = [m for m in tar.getmembers() if not (m.name.startswith("/") or ".." in Path(m.name).parts)]
        tar.extractall(base, members=members, filter="data")
        return [m.name for m in members if m.isfile()]


def seal() -> None:
    blob = _pack([ROOT / p for p in PRIVATE], ROOT)
    VAULT.parent.mkdir(exist_ok=True)
    VAULT.write_bytes(Fernet(_key()).encrypt(blob))
    print(f"sealed {VAULT.relative_to(ROOT)} ({VAULT.stat().st_size // 1024} KB)")


def unseal() -> None:
    names = _unpack(Fernet(_key()).decrypt(VAULT.read_bytes()), ROOT)
    print(f"unsealed {len(names)} private file(s)")


def seal_state(d: Path) -> None:
    files = sorted(d.glob("*.json"))
    (d / "state.bin").write_bytes(Fernet(_key()).encrypt(_pack(files, d)))
    for f in files:
        f.unlink()
    print(f"sealed {len(files)} state file(s) into {d / 'state.bin'}")


def unseal_state(d: Path) -> None:
    if not (d / "state.bin").exists():
        print("no state.bin yet: starting with empty state")
        return
    names = _unpack(Fernet(_key()).decrypt((d / "state.bin").read_bytes()), d)
    print(f"unsealed {len(names)} state file(s)")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "keygen":
        print(Fernet.generate_key().decode())
    elif cmd == "seal":
        seal()
    elif cmd == "unseal":
        unseal()
    elif cmd in ("seal-state", "unseal-state"):
        (seal_state if cmd == "seal-state" else unseal_state)(Path(sys.argv[2]))
    else:
        sys.exit(__doc__)
