"""Commit exp, run eval, log result, revert if needed."""
import subprocess, sys, os, re

EXP_NUM = 32
EXP_MSG = "exp32: remove edge and place_paper_bet from output"
EXP_DESC = "exp32: remove edge+place_paper_bet, focus on prob only"
BEST = 0.0484

os.chdir(os.path.dirname(os.path.abspath(__file__)))

subprocess.run(['git', 'add', '-A'], capture_output=True, text=True)
subprocess.run(['git', 'commit', '-m', EXP_MSG], capture_output=True, text=True)
commit = subprocess.run(['git','rev-parse','--short','HEAD'], capture_output=True, text=True).stdout.strip()

result = subprocess.run(
    [sys.executable, "eval.py", "--check-mutation"],
    capture_output=True, text=True, timeout=1800
)

stdout = result.stdout or ""
stderr = result.stderr or ""
combined = stdout + "\n" + stderr

brier = None
for line in combined.splitlines():
    m = re.search(r'Brier score\s*:\s*([\d.]+)', line)
    if m: brier = float(m.group(1))
    if "brier_score:" in line and brier is None:
        parts = line.split("brier_score:")
        if len(parts) > 1:
            try: brier = float(parts[1].strip())
            except ValueError: pass

gate = None
for line in combined.splitlines():
    if "Mutation gate:" in line:
        gate = "ACCEPT" if "ACCEPT" in line else "REJECT"

bands = []
for line in combined.splitlines():
    m = re.search(r'([\d.]+)-([\d.]+):\s*n=(\d+),\s*accuracy=(\d+)%', line)
    if m: bands.append(f"  {m.group(1)}-{m.group(2)}: n={m.group(3)}, accuracy={m.group(4)}%")

improved = brier is not None and brier < BEST
status = "keep" if improved else ("crash" if brier is None else "discard")

with open('results.tsv', 'a', encoding='utf-8') as f:
    if brier is not None:
        f.write(f"{commit}\t{brier}\t{status}\t{EXP_DESC}\n")
    else:
        f.write(f"crash\t0\tcrash\t{EXP_DESC}\n")

if not improved:
    subprocess.run(['git', 'reset', '--hard', 'HEAD~1'], capture_output=True, text=True)
    action = "REVERTED"
else:
    action = "KEPT"

new_head = subprocess.run(['git','rev-parse','--short','HEAD'], capture_output=True, text=True).stdout.strip()

with open('_exp_result.md', 'w', encoding='utf-8') as f:
    f.write(f"# Exp{EXP_NUM} Result\n\n")
    f.write(f"- **commit**: {commit}\n- **brier_score**: {brier}\n- **best_so_far**: {BEST}\n")
    f.write(f"- **improved**: {improved}\n- **gate**: {gate}\n- **status**: {status}\n")
    f.write(f"- **action**: {action}\n- **current_head**: {new_head}\n\n")
    if bands:
        f.write(f"## Confidence Bands\n\n")
        for b in bands: f.write(f"{b}\n")
        f.write("\n")
    f.write(f"## Last 30 lines\n\n```\n")
    for line in combined.splitlines()[-30:]:
        f.write(line.encode('ascii','replace').decode('ascii') + "\n")
    f.write("```\n")
