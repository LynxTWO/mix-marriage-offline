import fs from "node:fs"

import { defineConfig } from "@playwright/test"

const localFirefox = [
  process.env.PLAYWRIGHT_FIREFOX_EXECUTABLE,
].find((candidate) => typeof candidate === "string" && candidate.length > 0 && fs.existsSync(candidate))

export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  workers: 1,
  expect: {
    timeout: 10_000,
  },
  use: {
    baseURL: "http://127.0.0.1:1420",
    trace: "on-first-retry",
  },
  webServer: {
    command: "npm run dev -- --host 127.0.0.1",
    url: "http://127.0.0.1:1420",
    timeout: 120_000,
    reuseExistingServer: !process.env.CI,
  },
  projects: [
    {
      name: "firefox",
      use: {
        browserName: "firefox",
        launchOptions: localFirefox ? { executablePath: localFirefox } : undefined,
      },
    },
  ],
})
