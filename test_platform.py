"""Reproduce platform checks; live Azure and payment providers are not exercised."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--postgres', action='store_true', help='Use disposable Docker PostgreSQL integration tests')
parser.add_argument('--frontend', action='store_true', help='Typecheck and build the dashboard after npm ci')
args = parser.parse_args()
env = None
if args.postgres:
    command = [sys.executable, 'scripts/test_postgres.py', 'tests', 'platform/tests']
else:
    command = [sys.executable, '-m', 'pytest', '-q', 'tests', 'platform/tests']
    env = {**os.environ, 'PYTHONPATH': str(root / 'platform')}
subprocess.run(command, cwd=root, check=True, env=env)
if args.frontend:
    for script in ('typecheck', 'build'):
        subprocess.run(['npm', 'run', script], cwd=root / 'web-dashboard', check=True)
print('Requested checks passed. See TEST_REPORT.md for coverage and live-provider limits.')
