import { chromium } from 'playwright';
import { mkdir } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { join } from 'node:path';

const BASE = 'http://localhost:5173';
const OUT_DIR = join(process.cwd(), 'screenshots');
const VIEWPORT = { width: 1600, height: 1000 };
const WS = 'ws-001'; // workspace.id

async function switchTheme(page, mode) {
  await page.evaluate((targetMode) => {
    const current = document.documentElement.getAttribute('data-theme') || 'light';
    if (current !== targetMode) {
      const btns = Array.from(document.querySelectorAll('button'));
      const themeBtn = btns.find((b) => b.querySelector('[aria-label="sun"], [aria-label="moon"]'));
      if (themeBtn) themeBtn.click();
    }
  }, mode);
  await page.waitForTimeout(400);
}

async function grabFirstLinkFromList(page, listPath, hrefPattern) {
  await page.goto(`${BASE}${listPath}`, { waitUntil: 'networkidle', timeout: 30000 });
  try {
    await page.waitForSelector('.ant-table-row', { timeout: 10000 });
  } catch {}
  await page.waitForTimeout(1000);
  const href = await page.evaluate((pat) => {
    const re = new RegExp(pat.replace(/\//g, '\\/'));
    const links = Array.from(document.querySelectorAll('a[href]'));
    const match = links.find((a) => re.test(a.getAttribute('href') || ''));
    return match ? match.getAttribute('href') : null;
  }, hrefPattern);
  return href;
}

async function shoot(page, outPath) {
  await page.waitForTimeout(1500);
  await page.screenshot({ path: outPath, fullPage: false });
}

async function clickTabByLabel(page, label) {
  await page.evaluate((txt) => {
    const tabs = Array.from(document.querySelectorAll('[role="tab"], .ant-tabs-tab'));
    const tab = tabs.find((t) => t.textContent?.trim().includes(txt));
    if (tab) tab.click();
  }, label);
  await page.waitForTimeout(800);
}

async function runForTheme(browser, mode) {
  const context = await browser.newContext({
    viewport: VIEWPORT,
    deviceScaleFactor: 2,
  });
  const page = await context.newPage();
  const outMode = join(OUT_DIR, mode);
  if (!existsSync(outMode)) await mkdir(outMode, { recursive: true });

  await page.goto(`${BASE}/workspaces`, { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(800);
  if (mode === 'dark') await switchTheme(page, 'dark');

  let ok = 0;

  // 静态路径页面
  const tasks = [
    // === 算法工程师侧 ===
    ['01-login', '/login'],
    ['02-workspace-list', '/workspaces'],
    [`03-workspace-dashboard`, `/workspaces/${WS}`],
    [`04-tasks-overview`, `/workspaces/${WS}/tasks`],          // 5-C 新
    [`05-dev-list`, `/workspaces/${WS}/dev`],
    [`06-training-list`, `/workspaces/${WS}/training`],
    [`07-training-create`, `/workspaces/${WS}/training/new`],  // 5-C 改造
    [`08-inference-list`, `/workspaces/${WS}/inference`],
    [`09-inference-create`, `/workspaces/${WS}/inference/new`],// 5-C 改造
    [`10-experiments`, `/workspaces/${WS}/experiments`],
    [`11-models`, `/workspaces/${WS}/models`],                 // 5-C 新
    [`12-datasets`, `/workspaces/${WS}/datasets`],             // 5-C 新
    [`13-images`, `/workspaces/${WS}/images`],                 // 5-C 新
    // === 管理员侧 ===
    ['20-admin-dashboard', '/admin/dashboard'],
    ['21-admin-cluster', '/admin/cluster'],                    // 5-B 新
    ['22-admin-resource-pools', '/admin/resource-pools'],      // 5-B 新
    ['23-admin-nodes', '/admin/nodes'],                        // 5-B 新
    ['24-admin-scheduling', '/admin/scheduling'],              // 5-B 新
    ['25-admin-quota', '/admin/quota'],                        // 5-B 新
    ['26-admin-storage', '/admin/storage'],                    // 5-B 改版
    ['27-admin-network', '/admin/network'],                    // 5-B 新
    ['28-admin-events', '/admin/events'],                      // 5-B 新
    ['29-admin-audit', '/admin/audit'],                        // 5-B 新
  ];

  for (const [name, path] of tasks) {
    try {
      await page.goto(`${BASE}${path}`, { waitUntil: 'networkidle', timeout: 30000 });
      await shoot(page, join(outMode, `${name}.png`));
      console.log(`  ✓ ${name}`);
      ok++;
    } catch (e) {
      console.log(`  ✗ ${name}: ${e.message.split('\n')[0]}`);
    }
  }

  // 详情页（从列表 <a href> 拿真实 ID）
  // Dev Detail
  try {
    const url = await grabFirstLinkFromList(page, `/workspaces/${WS}/dev`, '/dev/dev-');
    if (url) {
      await page.goto(`${BASE}${url}`, { waitUntil: 'networkidle', timeout: 30000 });
      await shoot(page, join(outMode, '14-dev-detail.png'));
      console.log(`  ✓ 14-dev-detail`);
      ok++;
    }
  } catch (e) { console.log(`  ✗ 14-dev-detail: ${e.message.split('\n')[0]}`); }

  // Training Detail + Tabs
  try {
    const url = await grabFirstLinkFromList(page, `/workspaces/${WS}/training`, '/training/tj-');
    if (url) {
      await page.goto(`${BASE}${url}`, { waitUntil: 'networkidle', timeout: 30000 });
      await shoot(page, join(outMode, '15-training-detail-overview.png'));
      console.log(`  ✓ 15-training-detail-overview`);
      ok++;

      await clickTabByLabel(page, '监控');
      await shoot(page, join(outMode, '16-training-detail-monitoring.png'));
      console.log(`  ✓ 16-training-detail-monitoring`);
      ok++;

      await clickTabByLabel(page, '日志');
      await shoot(page, join(outMode, '17-training-detail-logs.png'));
      console.log(`  ✓ 17-training-detail-logs`);
      ok++;

      await clickTabByLabel(page, '检查点');
      await shoot(page, join(outMode, '18-training-detail-checkpoints.png'));
      console.log(`  ✓ 18-training-detail-checkpoints`);
      ok++;
    }
  } catch (e) { console.log(`  ✗ 15-training-detail: ${e.message.split('\n')[0]}`); }

  // Inference Detail + Tabs
  try {
    const url = await grabFirstLinkFromList(page, `/workspaces/${WS}/inference`, '/inference/inf-');
    if (url) {
      await page.goto(`${BASE}${url}`, { waitUntil: 'networkidle', timeout: 30000 });
      await shoot(page, join(outMode, '19-inference-detail.png'));
      console.log(`  ✓ 19-inference-detail`);
      ok++;

      await clickTabByLabel(page, 'LLM');
      await shoot(page, join(outMode, '19b-inference-llm-monitoring.png'));
      console.log(`  ✓ 19b-inference-llm-monitoring`);
      ok++;
    }
  } catch (e) { console.log(`  ✗ 19-inference-detail: ${e.message.split('\n')[0]}`); }

  await context.close();
  return ok;
}

async function run() {
  if (!existsSync(OUT_DIR)) await mkdir(OUT_DIR, { recursive: true });
  const browser = await chromium.launch({ headless: true });

  console.log('\n=== Theme: light ===');
  const lightOk = await runForTheme(browser, 'light');
  console.log('\n=== Theme: dark ===');
  const darkOk = await runForTheme(browser, 'dark');

  await browser.close();
  console.log(`\nDone. Light: ${lightOk}, Dark: ${darkOk}, Total: ${lightOk + darkOk}`);
  console.log(`Output: ${OUT_DIR}`);
}

run().catch((e) => {
  console.error(e);
  process.exit(1);
});
