"""Helper to log experiment results and revert git."""
import subprocess, sys, os

def log_and_revert(commit_hash, score, status, description, revert_to="870cf84"):
    line = f"{commit_hash}\t{score}\t{status}\t{description}\n"
    with open("results.tsv", "a", encoding="utf-8") as f:
        f.write(line)
    print(f"LOGGED: {description}")
    subprocess.run(["git", "reset", "--hard", revert_to], capture_output=True, text=True)
    r = subprocess.run(["git", "log", "--oneline", "-1"], capture_output=True, text=True)
    print(f"HEAD: {r.stdout.strip()}")

def run_eval():
    if os.path.exists("run.log"):
        os.remove("run.log")
    r = subprocess.run([sys.executable, "eval.py", "--check-mutation"], capture_output=True, text=True)
    with open("run.log", "w", encoding="utf-8") as f:
        f.write(r.stdout + r.stderr)
    print("EVAL DONE")

def read_results():
    with open("run.log", "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if any(k in line for k in ["Brier", "n=", "ACCEPT", "REJECT", "accuracy", "Prompt hash", "skipped", "WEAK"]):
                print(line)

def commit_exp(msg):
    subprocess.run(["git", "add", "-A"], capture_output=True, text=True)
    r = subprocess.run(["git", "commit", "-m", msg], capture_output=True, text=True)
    h = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    print(f"COMMITTED: {h.stdout.strip()} - {msg}")
    return h.stdout.strip()

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "log_revert":
        log_and_revert(sys.argv[2], sys.argv[3], sys.argv[4], " ".join(sys.argv[5:]))
    elif cmd == "eval":
        run_eval()
    elif cmd == "results":
        read_results()
    elif cmd == "commit":
        commit_exp(" ".join(sys.argv[2:]))
    else:
        print("Usage: exp_helper.py [log_revert|eval|results|commit] ...")
