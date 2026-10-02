const path = require('path');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '..');
const out = path.join(root, 'deliverables', 'video_assets');
const base = process.env.VIDEO_APP_URL || 'http://127.0.0.1:3000';
const edgePath = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';

const studentToken = '9OR5TWkQXEBhGpsWanY3Soznz-G9XSTgewFi8pdmfks'; // User 55
const recruiterToken = 'MRB6MoPCVLVgRNlObT9qG77_24Kwh_VtKc3c1weDTrM'; // User 56

async function main() {
  const browser = await chromium.launch({
    executablePath: edgePath,
    headless: true,
    args: [
      '--no-sandbox',
      '--disable-gpu',
      '--no-first-run',
      '--use-fake-ui-for-media-stream',
      '--use-fake-device-for-media-stream'
    ],
  });

  try {
    // ==========================================
    // 1. STUDENT PAGES (DAY MODE)
    // ==========================================
    const studentContext = await browser.newContext({
      viewport: { width: 1600, height: 900 },
      deviceScaleFactor: 1,
      colorScheme: 'light',
    });
    await studentContext.addCookies([
      { name: 'ai-interview-hub-theme', value: 'day', url: base },
      { name: 'aihub_session', value: studentToken, url: base }
    ]);
    await studentContext.route('**/api/auth/me', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          authenticated: true,
          user: { id: 55, role: 'student', name_masked: '演示学生', organization_name: null }
        })
      });
    });

    const studentPage = await studentContext.newPage();

    // 1. edge_report_top.png
    console.log('Capturing edge_report_top.png...');
    await studentPage.setViewportSize({ width: 1600, height: 900 });
    await studentPage.goto(new URL('/reports/6?user_id=55&job_id=1', base).href, { waitUntil: 'domcontentloaded', timeout: 45000 });
    await studentPage.waitForTimeout(2500);
    await studentPage.evaluate(() => { document.documentElement.dataset.theme = 'day'; });
    await studentPage.addStyleTag({ content: 'nextjs-portal { display: none !important; }' });
    await studentPage.evaluate(() => window.scrollTo(0, 0));
    await studentPage.waitForTimeout(400);
    await studentPage.screenshot({ path: path.join(out, 'edge_report_top.png') });
    console.log('edge_report_top.png saved.');

    // 2. edge_report_detail.png
    console.log('Capturing edge_report_detail.png...');
    await studentPage.evaluate(() => window.scrollTo(0, 600));
    await studentPage.waitForTimeout(400);
    await studentPage.screenshot({ path: path.join(out, 'edge_report_detail.png') });
    console.log('edge_report_detail.png saved.');

    // 3. edge_counsel_result.png
    console.log('Capturing edge_counsel_result.png...');
    await studentPage.setViewportSize({ width: 1920, height: 1080 });
    await studentPage.goto(new URL('/counsel', base).href, { waitUntil: 'domcontentloaded', timeout: 45000 });
    await studentPage.waitForTimeout(2000);
    await studentPage.evaluate(() => { document.documentElement.dataset.theme = 'day'; });
    await studentPage.locator('input').fill('智能驾驶，车辆测试');
    const submitBtn = studentPage.getByRole('button', { name: '生成岗位路径' });
    await submitBtn.waitFor({ state: 'visible', timeout: 10000 });
    await submitBtn.click();
    console.log('Clicked 生成岗位路径, waiting for results...');
    await studentPage.getByText('进入该岗位训练').first().waitFor({ timeout: 45000 });
    await studentPage.waitForTimeout(1000);
    await studentPage.addStyleTag({ content: 'nextjs-portal { display: none !important; }' });
    await studentPage.evaluate(() => window.scrollTo(0, 0));
    await studentPage.screenshot({ path: path.join(out, 'edge_counsel_result.png') });
    console.log('edge_counsel_result.png saved.');

    await studentContext.close();

    // ==========================================
    // 2. RECRUITER PAGE (DAY MODE) - PAGE 25 UI
    // ==========================================
    console.log('Capturing edge_recruiter_candidates.png...');
    const recruiterContext = await browser.newContext({
      viewport: { width: 1600, height: 900 },
      deviceScaleFactor: 1,
      colorScheme: 'light',
    });
    await recruiterContext.addCookies([
      { name: 'ai-interview-hub-theme', value: 'day', url: base },
      { name: 'aihub_session', value: recruiterToken, url: base }
    ]);
    await recruiterContext.route('**/api/auth/me', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          authenticated: true,
          user: { id: 56, role: 'recruiter', name_masked: '企业评审', organization_name: '智能网联车企测评中心' }
        })
      });
    });

    const recruiterPage = await recruiterContext.newPage();
    await recruiterPage.goto(new URL('/recruiter', base).href, { waitUntil: 'domcontentloaded', timeout: 45000 });
    await recruiterPage.waitForTimeout(2500);
    await recruiterPage.evaluate(() => { document.documentElement.dataset.theme = 'day'; });

    const cohort = recruiterPage.locator('label').filter({ hasText: '评分口径' }).locator('select');
    if (await cohort.locator('option').count() > 1) {
      await cohort.selectOption({ index: 1 });
      await recruiterPage.waitForTimeout(1500);
    }

    const candidateBtn = recruiterPage.locator('button').filter({ hasText: '查看原报告' }).first();
    if (await candidateBtn.isVisible()) {
      await candidateBtn.click();
      await recruiterPage.waitForTimeout(1500);
    }

    await recruiterPage.addStyleTag({ content: 'nextjs-portal { display: none !important; }' });
    await recruiterPage.evaluate(() => window.scrollTo(0, 160));
    await recruiterPage.waitForTimeout(500);
    await recruiterPage.screenshot({ path: path.join(out, 'edge_recruiter_candidates.png') });
    console.log('edge_recruiter_candidates.png saved.');

    await recruiterContext.close();

    console.log('All 4 day-mode screenshots successfully captured and saved!');
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
