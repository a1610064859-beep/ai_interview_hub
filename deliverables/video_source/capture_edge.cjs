/** Capture the running app in Microsoft Edge for the demo video. */
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");

const root = path.resolve(__dirname, "..", "..");
const out = path.join(root, "deliverables", "video_assets");
const base = process.env.VIDEO_APP_URL || "http://127.0.0.1:3010";
const edge = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";

async function main() {
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({
    executablePath: edge,
    headless: true,
    args: ["--no-sandbox", "--disable-gpu", "--no-first-run"],
  });
  try {
    const context = await browser.newContext({
      viewport: { width: 1600, height: 900 },
      deviceScaleFactor: 1,
      colorScheme: "dark",
    });
    await context.addCookies([{ name: "ai-interview-hub-theme", value: "night", url: base }]);
    let role = "student";
    await context.route("**/api/auth/me", async (route) => {
      const user = role === "student"
        ? { id: 3, role: "student", name_masked: "王*明", organization_name: null }
        : { id: 2, role: "recruiter", name_masked: "企业评审", organization_name: "演示企业" };
      await route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ authenticated: true, user }) });
    });
    const page = await context.newPage();
    const captures = [
      ["/", "edge_jobs.png", "student", 0],
      ["/", "edge_interview.png", "student", 0],
      ["/reports/6?user_id=3&job_id=1", "edge_report_top.png", "student", 0],
      ["/reports/6?user_id=3&job_id=1", "edge_report_detail.png", "student", 640],
      ["/growth?user_id=3&job_id=1", "edge_growth.png", "student", 0],
      ["/learn", "edge_learn.png", "student", 0],
      ["/counsel", "edge_counsel.png", "student", 0],
      ["/counsel", "edge_counsel_result.png", "student", 380],
      ["/recruiter", "edge_recruiter.png", "recruiter", 0],
      ["/recruiter", "edge_recruiter_candidates.png", "recruiter", 520],
    ];
    for (const [route, name, captureRole, scrollY] of captures) {
      role = captureRole;
      if (name === "edge_interview.png") {
        const response = await context.request.post(new URL("/api/sessions", base).href,
          { data: { job_id: 1, user_id: 3, mode: "毕业生" } });
        if (!response.ok()) throw new Error(`Session creation failed: HTTP ${response.status()}`);
        const { sid } = await response.json();
        await page.evaluate((sessionId) => {
          localStorage.setItem("ai-interview-active-session-v1", JSON.stringify({
            sid: sessionId, userId: 3, jobId: 1, mode: "毕业生", startedAtMs: Date.now(),
          }));
        }, sid);
      }
      await page.goto(new URL(route, base).href, { waitUntil: "domcontentloaded", timeout: 45000 });
      await page.waitForTimeout(1800);
      if (name === "edge_counsel_result.png") {
        await page.locator("input").fill("智能驾驶，车辆测试");
        await page.getByRole("button", { name: "生成岗位路径" }).click();
        await page.getByText("进入该岗位训练").first().waitFor({ timeout: 40000 });
      }
      if (name === "edge_recruiter_candidates.png") {
        const cohort = page.locator("label").filter({ hasText: "评分口径" }).locator("select");
        if (await cohort.locator("option").count() > 1) {
          await cohort.selectOption({ index: 1 });
          await page.waitForTimeout(600);
        }
      }
      await page.addStyleTag({ content: "nextjs-portal { display: none !important; }" });
      await page.evaluate((y) => window.scrollTo(0, y), scrollY);
      await page.waitForTimeout(250);
      const text = (await page.locator("body").innerText()).replace(/\s+/g, " ").slice(0, 130);
      const file = path.join(out, name);
      await page.screenshot({ path: file });
      process.stdout.write(`${name}: ${text}\n`);
    }
    await context.close();
  } finally {
    await browser.close();
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
