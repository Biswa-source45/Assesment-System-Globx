import { defineConfig } from "@playwright/test"

// Starts its own API (port 8001, throw-away database) and the Vite dev server (port 5174), then runs the browser tests.
export default defineConfig({
  testDir: "e2e",
  timeout: 120_000,
  workers: 1,
  fullyParallel: false,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:5174",
    permissions: ["camera"],
    // a fake camera, so the camera and face flow can run without hardware
    launchOptions: { args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"] },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: "..\\backend\\.venv\\Scripts\\python ..\\backend\\tests\\e2e_server.py e2e\\.creds.json",
      url: "http://localhost:8001/api/health",
      timeout: 120_000,
      reuseExistingServer: false,
    },
    {
      command: "npx vite --port 5174 --strictPort",
      env: { API_PORT: "8001" },
      url: "http://localhost:5174",
      reuseExistingServer: false,
    },
  ],
})
