"""Load voice samples from RTF files in voice-samples/."""

from __future__ import annotations

from pathlib import Path

from striprtf.striprtf import rtf_to_text

from outreach.config import VOICE_SAMPLES_DIR


def load_voice_samples(samples_dir: Path | None = None) -> list[str]:
    """Iterate RTF files in ``samples_dir`` and return cleaned message text.

    OS noise (.DS_Store, hidden files, non-RTF files) is silently skipped.
    Files that fail to parse print a warning but don't abort the load.
    """
    target_dir = samples_dir or VOICE_SAMPLES_DIR
    if not target_dir.exists():
        return []

    samples: list[str] = []
    for path in sorted(target_dir.iterdir()):
        if path.suffix.lower() != ".rtf":
            continue
        if path.name.startswith("."):
            continue
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
            cleaned = rtf_to_text(raw).strip()
        except Exception as exc:  # noqa: BLE001 — operator-friendly fallthrough
            print(f"⚠️  Could not parse {path.name}: {exc}")
            continue
        if cleaned:
            samples.append(cleaned)
    return samples


def verify() -> bool:
    """Print a summary of voice samples loaded. Returns True if any loaded."""
    samples = load_voice_samples()
    if not samples:
        print(f"❌ No voice samples found in {VOICE_SAMPLES_DIR}")
        print("   Add RTF files to that folder and try again.")
        return False
    print(f"✅ Loaded {len(samples)} voice samples from {VOICE_SAMPLES_DIR}")
    print()
    for i, sample in enumerate(samples, 1):
        char_count = len(sample)
        preview = sample[:80].replace("\n", " ")
        if len(sample) > 80:
            preview += "…"
        print(f"  {i:2d}. ({char_count:4d} chars) {preview}")
    return True
