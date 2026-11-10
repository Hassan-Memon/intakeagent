// OpenNext adapter config for Cloudflare Workers (https://opennext.js.org/cloudflare).
// No incremental cache binding: every page is either static or rendered per request, and the
// demo keeps its state in the browser, so the free plan needs no R2 bucket or KV namespace.
import { defineCloudflareConfig } from "@opennextjs/cloudflare";

export default defineCloudflareConfig({});
