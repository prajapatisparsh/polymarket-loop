"""Commit exp25, run eval, log result, revert if needed."""
import subprocess, sys, os, re

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Commit
subprocess.run(['git', 'add', '-A'], capture_output=True, text=True)
subprocess.run(['git', 'commit', '-m', 'exp25: decisiveness rule - push past 0.75/0.25 when evidence is clear'], capture_output=True, text=True)
commit = subprocess.run(['git','rev-parse','--short','HEAD'], capture_output=True, text=True).stdout.strip()

# Run eval
result = subprocess.run(
    [sys.executable, "eval.py", "--check-mutation"],
    capture_output=True, text=True, timeout=1800
)

stdout = result.stdout or ""
stderr = result.stderr or ""
combined = stdout + "\n" + stderr

# Extract brier_score
brier = None
for line in combined.splitlines():
    m = re.search(r'Brier score\s*:\s*([\d.]+)', line)
    if m:
        brier = float(m.group(1))
    if "brier_score:" in line and brier is None:
        parts = line.split("brier_score:")
        if len(parts) > 1:
            try:
                brier = float(parts[1].strip())
            except ValueError:
                pass

# Extract gate
gate = None
for line in combined.splitlines():
    if "Mutation gate:" in line:
        gate = "ACCEPT" if "ACCEPT" in line else "REJECT"

# Extract confidence bands
bands = []
for line in combined.splitlines():
    m = re.search(r'([\d.]+)-([\d.]+):\s*n=(\d+),\s*accuracy=(\d+)%', line)
    if m:
        bands.append(f"  {m.group(1)}-{m.group(2)}: n={m.group(3)}, accuracy={m.group(4)}%")

# Extract n markets
n_markets = None
for line in combined.splitlines():
    m = re.search(r'n=(\d+)', line)
    if m:
        n_markets = int(m.group(1))

BEST = 0.0561
improved = brier is not None and brier < BEST
status = "keep" if improved else ("crash" if brier is None else "discard")

# Log to results.tsv
desc = f"exp25: decisiveness rule - push past 0.75/0.25"
if brier is not None:
    with open('results.tsv', 'a', encoding='utf-8') as f:
        f.write(f"{commit}\t{brier}\t{status}\t{desc}\n")
else:
    with open('results.tsv', 'a', encoding='utf-8') as f:
        f.write(f"crash\t0\tcrash\t{desc}\n")

# Revert if not improved
if not improved:
    subprocess.run(['git', 'reset', '--hard', 'HEAD~1'], capture_output=True, text=True)
    action = "REVERTED"
else:
    action = "KEPT"

new_head = subprocess.run(['git','rev-parse','--short','HEAD'], capture_output=True, text=True).stdout.strip()

with open('_exp_result.md', 'w', encoding='utf-8') as f:
    f.write(f"# Exp25 Result\n\n")
    f.write(f"- **commit**: {commit}\n")
    f.write(f"- **brier_score**: {brier}\n")
    f.write(f"- **best_so_far**: {BEST}\n")
    f.write(f"- **improved**: {improved}\n")
    f.write(f"- **gate**: {gate}\n")
    f.write(f"- **status**: {status}\n")
    f.write(f"- **action**: {action}\n")
    f.write(f"- **current_head**: {new_head}\n")
    f.write(f"- **n_markets**: {n_markets}\n\n")
    if bands:
        f.write(f"## Confidence Bands\n\n")
        for b in bands:
            f.write(f"{b}\n")
        f.write("\n")
    f.write(f"## Last 30 lines\n\n```\n")
    for line in combined.splitlines()[-30:]:
        line = line.encode('ascii', 'replace').decode('ascii')
        f.write(line + "\n")
    f.write("```\n")
