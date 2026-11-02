#!/usr/bin/env python3
"""Export RULE_DISPLAY_NAMES for the web dashboard (run after catalog changes)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))
from app.resource_catalog import RULE_DISPLAY_NAMES  # noqa: E402

out = ROOT / 'web-dashboard' / 'lib' / 'rule-labels.json'
out.write_text(json.dumps(RULE_DISPLAY_NAMES, indent=2, sort_keys=True) + '\n')
print(f'Wrote {len(RULE_DISPLAY_NAMES)} labels to {out.relative_to(ROOT)}')
