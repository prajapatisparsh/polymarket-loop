// eval.js — read-only, the agent must NOT modify this file
//
// This script answers: "how good is the project right now?"
// It runs your project, measures the result, and prints a score.
//
// Contract: this script must print a line like:
//   brier_score: 85.3
// so the agent can extract it with grep.

// TODO: Replace the placeholder below with your actual evaluation logic.

import { execSync } from "child_process";

async function evaluate() {
  // Step 1: Build or run your project
  // e.g. execSync("npm run build", { stdio: "inherit" });

  // Step 2: Measure something
  // e.g. run test cases, measure response time, check pass rate

  // Step 3: Print the score
  const brier_score = 0; // replace with your actual measurement
  console.log("---");
  console.log(`brier_score: ${brier_score}`);
}

evaluate().catch((err) => {
  console.error(err);
  process.exit(1);
});
