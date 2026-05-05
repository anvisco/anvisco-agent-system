import { existsSync, mkdirSync, appendFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

type StepName = "all" | "scraper" | "validate" | "drafts" | "replies" | "followups";

type CliOptions = {
  dryRun: boolean;
  write: boolean;
  step: StepName;
};

type Phase = {
  name: string;
  args: string[];
};

const ROOT_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const LOG_DIR = join(ROOT_DIR, "logs");
const LOG_PATH = join(LOG_DIR, `outreach_daily_${new Date().toISOString().slice(0, 10)}.log`);

function parseArgs(argv: string[]): CliOptions {
  const options: CliOptions = { dryRun: false, write: false, step: "all" };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--dry-run") {
      options.dryRun = true;
    } else if (arg === "--write") {
      options.write = true;
    } else if (arg === "--step") {
      const value = argv[index + 1] as StepName | undefined;
      if (!value || !["all", "scraper", "validate", "drafts", "replies", "followups"].includes(value)) {
        throw new Error("--step must be one of: all, scraper, validate, drafts, replies, followups");
      }
      options.step = value;
      index += 1;
    }
  }
  return options;
}

function pythonExecutable(): string {
  const windowsVenvPython = join(ROOT_DIR, ".venv", "Scripts", "python.exe");
  const unixVenvPython = join(ROOT_DIR, ".venv", "bin", "python");
  if (existsSync(windowsVenvPython)) {
    return windowsVenvPython;
  }
  if (existsSync(unixVenvPython)) {
    return unixVenvPython;
  }
  return process.platform === "win32" ? "py" : "python3";
}

function log(message: string): void {
  mkdirSync(LOG_DIR, { recursive: true });
  const line = `[${new Date().toISOString()}] ${message}`;
  console.log(line);
  appendFileSync(LOG_PATH, `${line}\n`, "utf8");
}

function childEnv(options: CliOptions): NodeJS.ProcessEnv {
  const env = { ...process.env };
  if (options.dryRun && !options.write) {
    env.DRY_RUN = "true";
    env.CREATE_GMAIL_DRAFTS = "false";
  } else if (options.dryRun && options.write) {
    env.DRY_RUN = "false";
    env.CREATE_GMAIL_DRAFTS = "false";
  } else if (options.write) {
    env.DRY_RUN = "false";
  }
  if (!env.CREATE_GMAIL_DRAFTS) env.CREATE_GMAIL_DRAFTS = "true";
  if (!env.SEND_MODE) env.SEND_MODE = "auto_draft";
  if (!env.AUTO_SEND_FIRST_EMAILS) env.AUTO_SEND_FIRST_EMAILS = "false";
  if (!env.REQUIRE_ADMIN_APPROVAL_FOR_SEND) env.REQUIRE_ADMIN_APPROVAL_FOR_SEND = "true";
  if (!env.GMAIL_LABEL) env.GMAIL_LABEL = "Anvis/Leads";
  if (!env.GMAIL_SEND_AS_EMAIL) env.GMAIL_SEND_AS_EMAIL = "brian@anvisco.com";
  if (!env.COUNTRY_SCOPE) env.COUNTRY_SCOPE = "Canada";
  if (!env.ACTIVE_PROVINCE) env.ACTIVE_PROVINCE = "Ontario";
  if (!env.ACTIVE_CITY) env.ACTIVE_CITY = "Toronto";
  if (!env.ONE_CITY_PER_RUN) env.ONE_CITY_PER_RUN = "true";
  return env;
}

function phasesForStep(step: StepName): Phase[] {
  const phases: Record<Exclude<StepName, "all">, Phase[]> = {
    scraper: [{ name: "Lead scraper", args: ["agents/run_lead_scraper.py"] }],
    validate: [{ name: "Notion validation", args: ["agents/validate_outreach_notion.py"] }],
    drafts: [{ name: "Email 1 draft creation", args: ["agents/generate_drafts_from_notion.py", "--mode", "email1"] }],
    replies: [{ name: "Gmail reply checker", args: ["agents/check_gmail_replies.py"] }],
    followups: [{ name: "Follow-up draft checker", args: ["agents/generate_drafts_from_notion.py", "--mode", "followups"] }],
  };
  if (step === "all") {
    return [...phases.scraper, ...phases.validate, ...phases.drafts, ...phases.replies, ...phases.followups];
  }
  return phases[step];
}

function runPhase(phase: Phase, options: CliOptions): boolean {
  log(`START | ${phase.name}`);
  const result = spawnSync(pythonExecutable(), phase.args, {
    cwd: ROOT_DIR,
    env: childEnv(options),
    encoding: "utf8",
  });

  if (result.stdout) {
    appendFileSync(LOG_PATH, result.stdout, "utf8");
    process.stdout.write(result.stdout);
  }
  if (result.stderr) {
    appendFileSync(LOG_PATH, result.stderr, "utf8");
    process.stderr.write(result.stderr);
  }

  if (result.error) {
    log(`ERROR | ${phase.name} | ${result.error.message}`);
    return false;
  }
  if (result.status !== 0) {
    log(`ERROR | ${phase.name} | exited with code ${result.status}`);
    return false;
  }
  log(`DONE | ${phase.name}`);
  return true;
}

function main(): void {
  const options = parseArgs(process.argv.slice(2));
  mkdirSync(LOG_DIR, { recursive: true });
  log(`Outreach daily automation started | step=${options.step} | dryRun=${options.dryRun} | write=${options.write}`);
  log("Safety policy: Gmail drafts by default. Auto-send is gated and disabled unless explicitly configured.");

  let failures = 0;
  for (const phase of phasesForStep(options.step)) {
    const ok = runPhase(phase, options);
    if (!ok) {
      failures += 1;
    }
  }

  log(`Outreach daily automation complete | failures=${failures} | log=${LOG_PATH}`);
  if (failures > 0) {
    process.exitCode = 1;
  }
}

main();
