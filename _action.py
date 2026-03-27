"""Log exp24 result, revert the commit."""
import subprocess, os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Get commit hash
h = subprocess.run(['git','rev-parse','--short','HEAD'], capture_output=True, text=True).stdout.strip()

# Append to results.tsv
with open('results.tsv', 'a', encoding='utf-8') as f:
    f.write(f"{h}\t0.074\tdiscard\texp24: market extremes rule — match extreme prices when evidence agrees, 75% at 0.50-0.60\n")

# Revert the commit
subprocess.run(['git', 'reset', '--hard', 'HEAD~1'], capture_output=True, text=True)

# Confirm revert
h2 = subprocess.run(['git','rev-parse','--short','HEAD'], capture_output=True, text=True).stdout.strip()

with open('_action_log.md', 'w', encoding='utf-8') as f:
    f.write(f"# Action Log\n\n")
    f.write(f"- Logged exp24 commit {h} with brier=0.074, status=discard\n")
    f.write(f"- Reverted to commit {h2}\n")
