import subprocess, sys, re

result = subprocess.run(
    [sys.executable, "eval.py", "--check-mutation"],
    capture_output=True, text=True, encoding='utf-8', errors='replace'
)

combined = (result.stdout or "") + "\n" + (result.stderr or "")

brier = None
for line in combined.splitlines():
    m = re.search(r'Brier score\s*:\s*([0-9.]+)', line)
    if m:
        brier = float(m.group(1))

with open('_baseline.md', 'w', encoding='utf-8') as f:
    f.write(f"New Baseline Brier: {brier}\n\n```\n")
    for line in combined.splitlines()[-50:]:
        f.write(line + "\n")
    f.write("```\n")
