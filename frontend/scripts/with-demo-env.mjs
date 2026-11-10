// Run a command with NEXT_PUBLIC_DEMO_MODE=1 set, on any OS (npm scripts use cmd.exe on
// Windows, where `VAR=1 cmd` does not work). Used by the Cloudflare build only.
import { spawnSync } from "node:child_process";

const args = process.argv.slice(2);
if (args.length === 0) {
  console.error("usage: node scripts/with-demo-env.mjs <command> [args...]");
  process.exit(2);
}
const result = spawnSync(args.join(" "), {
  stdio: "inherit",
  shell: true,
  env: { ...process.env, NEXT_PUBLIC_DEMO_MODE: "1" },
});
process.exit(result.status ?? 1);
