import importlib.metadata as md
import json
from pathlib import Path
import subprocess
import tempfile



def installed_git_commits() -> dict[str, str]:
    """{url_git: commit_id} pour tous les packages installés depuis un dépôt git."""
    result = {}
    for dist in md.distributions():
        raw = dist.read_text("direct_url.json")
        if not raw:
            continue
        try:
            info = json.loads(raw)
        except ValueError:
            continue
        commit = info.get("vcs_info", {}).get("commit_id")
        if commit and "url" in info:
            result[info["url"].removesuffix(".git")] = commit
    return result



def remote_commit(url: str, ref: str = "HEAD") -> str | None:
    try:
        out = subprocess.run(
            ["git", "ls-remote", url, ref],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout
    except Exception:
        return None  # réseau KO : on laisse pip décider
    return out.split()[0] if out.strip() else None



def split_git_requirement(line: str) -> tuple[str, str]:
    """'git+https://x/y.git@branch' -> ('https://x/y.git', 'branch')"""
    url = line.removeprefix("git+")
    head, _, tail = url.rpartition("/")
    if "@" in tail:
        tail, _, ref = tail.partition("@")
        return f"{head}/{tail}", ref
    return url, "HEAD"



def is_git_up_to_date(line: str, installed: dict[str, str]) -> bool:
    url, ref = split_git_requirement(line)
    local = installed.get(url.removesuffix(".git"))
    if local is None:
        return False
    remote = remote_commit(url, ref)
    return remote is not None and remote == local



_PATH_OPT_RE = re.compile(r"^(-r|--requirement|-c|--constraint|-e|--editable)[\s=]+(\S.*)$")
def _absolutize(line: str, base: Path) -> str:
    """Rend absolus les chemins locaux des options -r / -c / -e (pas les URL)."""
    m = _PATH_OPT_RE.match(line.strip())
    if not m:
        return line
    opt, value = m.groups()
    if "://" not in value:  # ne touche pas à "-e git+https://..."
        p = Path(value)
        if not p.is_absolute():
            value = str((base / p).resolve())
    return f"{opt} {value}"



def filter_requirements(req_file: Path, installed: dict[str, str], out_dir: Path) -> Path:
    """Copie filtrée dans out_dir, sans les git+ déjà à jour.
    Les chemins relatifs (-r, -e) sont convertis en absolus."""
    kept = []
    for raw in req_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("git+") and is_git_up_to_date(line, installed):
            print(f"  = {line} : déjà à jour, ignoré")
        else:
            kept.append(_absolutize(raw, req_file.parent))

    out = out_dir / f"{req_file.stem}.filtered.txt"
    out.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return out
