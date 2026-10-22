"""Check required Linux commands and local Ollama availability."""
import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request

BINARIES = {
    "useradd": "passwd",
    "usermod": "passwd",
    "groupadd": "passwd",
    "mkdir": "coreutils",
    "id": "coreutils",
    "getent": "libc-bin",
    "runuser": "util-linux",
}
SEARCH_PATH = "/usr/sbin:/usr/bin:/sbin:/bin"


def _dpkg_installed(pkg):
    try:
        r = subprocess.run(
            ["dpkg-query", "-W", "-f=${Status}", pkg],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return r.returncode == 0 and "install ok installed" in r.stdout


def ollama_host():
    from .ollama_client import normalize_host
    return normalize_host(os.environ.get("OLLAMA_HOST"))


def _ollama_status():
    request = urllib.request.Request(ollama_host() + "/api/tags")
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            data = json.loads(response.read().decode("utf-8"))
        models = [item.get("name", "") for item in data.get("models", [])]
        return True, models
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return False, []


def check(model=None):
    missing_bins = [
        b for b in BINARIES
        if not shutil.which(b, path=SEARCH_PATH)
    ]
    apt_pkgs = sorted({
        BINARIES[b] for b in BINARIES
        if _dpkg_installed(BINARIES[b]) is False
    } | {BINARIES[b] for b in missing_bins})

    ollama_ok, models = _ollama_status()
    from . import config
    default_model = model or os.environ.get("OLLAMA_MODEL") or config.DEFAULT_MODEL
    model_ok = any(
        name == default_model or name.startswith(default_model + ":")
        for name in models
    )

    commands = []
    if apt_pkgs:
        commands += [
            "sudo apt update",
            "sudo apt install -y " + " ".join(apt_pkgs),
        ]
    if not ollama_ok:
        commands.append("Start the local Ollama service and retry.")
    elif not model_ok:
        commands.append(f"ollama pull {default_model}")

    return {
        "missing_binaries": missing_bins,
        "missing_apt": apt_pkgs,
        "ollama_ok": ollama_ok,
        "models": models,
        "model": default_model,
        "model_ok": model_ok,
        "commands": commands,
        "ok": not missing_bins and ollama_ok and model_ok,
    }


def report(result=None):
    r = result or check()
    lines = ["Dependency check:"]

    for binary in BINARIES:
        mark = "MISSING" if binary in r["missing_binaries"] else "ok"
        lines.append(f"  [{mark:>7}] {binary}")

    lines.append(
        f"  [{'ok' if r['ollama_ok'] else 'MISSING':>7}] local Ollama API"
    )
    lines.append(
        f"  [{'ok' if r['model_ok'] else 'MISSING':>7}] "
        f"model ({r['model']})"
    )

    if r["models"]:
        lines.append("  Available models: " + ", ".join(r["models"]))

    if r["commands"]:
        lines.append("Suggested actions:")
        lines.extend("  " + command for command in r["commands"])
    else:
        lines.append("All dependencies present.")

    return "\n".join(lines)
