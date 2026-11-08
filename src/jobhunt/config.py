"""Load and merge global config + the selected profile."""
from __future__ import annotations
import os
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]


def _read_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


class Config:
    def __init__(self, config_path: str | None = None, profile_override: str | None = None):
        self.root = ROOT
        self.config_path = Path(config_path) if config_path else ROOT / "config" / "config.yaml"
        self.cfg = _read_yaml(self.config_path)
        private = next((p for p in (self.config_path.parent / "private.yaml", ROOT / "config" / "private.yaml")
                        if p.exists()), None)
        if private:  # personal values, decrypted from the vault in CI
            self.cfg = _merge(self.cfg, _read_yaml(private))
        profile_id = profile_override or self.cfg.get("run", {}).get("profile")
        if not profile_id:
            raise ValueError("No profile specified (run.profile in config or --profile).")
        self.profile_id = profile_id
        self.profile = _read_yaml(ROOT / "profiles" / f"{profile_id}.yaml")

    # convenience accessors
    @property
    def run(self) -> dict: return self.cfg.get("run", {})
    @property
    def sources(self) -> list: return [s for s in self.cfg.get("sources", []) if s.get("enabled")]
    @property
    def llm(self) -> dict: return self.cfg.get("llm", {})
    @property
    def email(self) -> dict: return self.cfg.get("email", {})

    def output_dir(self) -> Path:
        d = ROOT / self.run.get("output_dir", "output") / self.profile_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def state_path(self) -> Path:
        p = ROOT / self.run.get("state_file", "state/seen.json")
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def ledger_path(self) -> Path:
        return ROOT / self.run.get("ledger_file", f"state/ledger.{self.profile_id}.json")

    def runs_path(self) -> Path:
        return ROOT / self.run.get("runs_file", f"state/runs.{self.profile_id}.json")

    def registers_path(self) -> Path:
        return ROOT / self.run.get("registers_file", "state/registers.json")

    def answers_kit_path(self) -> Path:
        return ROOT / self.run.get("answers_kit_file", f"state/answers_kit.{self.profile_id}.json")

    def connections_path(self) -> Path:
        """LinkedIn Connections.csv export (private; decrypted from the vault in CI)."""
        return ROOT / self.profile.get("linkedin_connections_file", f"profiles/{self.profile_id}.connections.csv")

    def relocation_list_path(self) -> Path:
        return ROOT / self.run.get("relocation_list", "config/relocation_companies.txt")

    def resume_path(self) -> Path:
        # convention: profiles/<id>.resume.md ; overridable via profile key `resume_file`
        rp = self.profile.get("resume_file")
        return Path(rp) if rp else ROOT / "profiles" / f"{self.profile_id}.resume.md"

    def smtp_password(self) -> str | None:
        """Env var first (CI secrets), then the git-ignored root .env file (local runs)."""
        return os.environ.get("JOBHUNT_SMTP_PASS") or _dotenv(ROOT / ".env").get("JOBHUNT_SMTP_PASS")


def _dotenv(path: Path) -> dict:
    """Minimal KEY=VALUE parser. Never logs values."""
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out
