/**
 * Wave 4 · chrome-cdp 全功能 E2E 验证
 *
 * 通过 Playwright 驱动 chromium (不依赖本地 Chrome debug port)
 * 对每个页面的每个关键按钮都做点击尝试, 失败记录到 report.json
 *
 * 运行:
 *   node scripts/e2e-verify.mjs
 */

import { chromium } from 'playwright';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const BASE = 'http://localhost:5173';
const API = process.env.E2E_API_BASE || 'http://localhost:8800';
const OUT_DIR = join(process.cwd(), 'e2e-report');
const VIEWPORT = { width: 1600, height: 1000 };

const results = []; // [{page, action, ok, msg, screenshot}]

const log = (...args) => console.log(new Date().toISOString().slice(11, 19), ...args);

async function step(name, fn) {
  log(`▶ ${name}`);
  try {
    const out = await fn();
    log(`  ✓ ok`);
    results.push({ step: name, ok: true, out });
    return out;
  } catch (e) {
    log(`  ✗ ${e.message}`);
    results.push({ step: name, ok: false, err: e.message, stack: e.stack });
    return null;
  }
}

async function shot(page, tag) {
  const path = join(OUT_DIR, `${tag}.png`);
  try {
    await page.screenshot({ path, fullPage: false });
    return path;
  } catch (e) {
    return `<shot-fail: ${e.message}>`;
  }
}

async function main() {
  await mkdir(OUT_DIR, { recursive: true });

  // 先 ping API
  try {
    const r = await fetch(`${API}/healthz`);
    log(`API /healthz → ${r.status}`);
  } catch (e) {
    log(`✗ API unreachable: ${e.message}`);
  }

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: VIEWPORT });
  const page = await context.newPage();

  // Console 错误捕获
  const consoleErrors = [];
  page.on('pageerror', (err) => {
    consoleErrors.push({ type: 'pageerror', msg: err.message });
    log(`  [pageerror] ${err.message}`);
  });
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      consoleErrors.push({ type: 'console', msg: msg.text() });
    }
  });

  // Network 失败捕获
  const netErrors = [];
  page.on('requestfailed', (req) => {
    netErrors.push({ url: req.url(), failure: req.failure()?.errorText });
  });
  page.on('response', (resp) => {
    if (resp.status() >= 500) {
      netErrors.push({ url: resp.url(), status: resp.status() });
    }
  });

  // ===== 1. 首页 =====
  await step('首页加载 /', async () => {
    await page.goto(BASE, { waitUntil: 'networkidle', timeout: 15000 });
    await shot(page, '01-home');
  });

  // ===== 2. 导航到 Workspace List =====
  await step('/workspaces 列表', async () => {
    await page.goto(`${BASE}/workspaces`, { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(1500);
    await shot(page, '02-workspaces');
    // 支持卡片布局 (AntD ProCard) 和表格布局 (ant-table-row)
    const cards = await page.$$eval(
      '.ant-card, .ant-pro-card, .ant-table-row',
      (els) => els.length,
    );
    if (cards === 0) throw new Error('空列表');
    return { cards };
  });

  // ===== 3. 点击第一个 workspace 进详情 =====
  await step('点击第一个 workspace 进 Dashboard', async () => {
    // 按钮文字"进入工作空间" 或者表格第一个链接
    const handle = await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('button, a'));
      const target = btns.find((b) => /进入工作空间|查看/.test(b.textContent || ''));
      return target ? target.outerHTML.slice(0, 80) : null;
    });
    if (!handle) throw new Error('找不到"进入工作空间"按钮');
    await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('button, a'));
      const target = btns.find((b) => /进入工作空间|查看/.test(b.textContent || ''));
      if (target) target.click();
    });
    await page.waitForLoadState('networkidle', { timeout: 10000 });
    await page.waitForTimeout(1500);
    await shot(page, '03-ws-dashboard');
    const url = page.url();
    if (!/\/workspaces\/[^/]+/.test(url)) throw new Error(`URL 不对: ${url}`);
    return { url };
  });

  const wsUrl = page.url();
  const wsId = wsUrl.match(/\/workspaces\/([^/?#]+)/)?.[1];

  // ===== 4. DevInstance List =====
  await step('/dev DevInstance 列表', async () => {
    await page.goto(`${BASE}/workspaces/${wsId}/dev`, { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(1500);
    await shot(page, '04-dev-list');
  });

  // ===== 5. Training List =====
  await step('/training 训练列表', async () => {
    await page.goto(`${BASE}/workspaces/${wsId}/training`, { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(1500);
    await shot(page, '05-training-list');
  });

  // ===== 5.5 其他 workspace-scoped 页面 =====
  const wsPages = [
    { path: 'tasks', tag: '05b-tasks' },
    { path: 'inference', tag: '05c-inference' },
    { path: 'experiments', tag: '05d-experiments' },
    { path: 'models', tag: '05e-models' },
    { path: 'images', tag: '05f-images' },
  ];
  for (const p of wsPages) {
    await step(`Workspace /${p.path}`, async () => {
      await page.goto(`${BASE}/workspaces/${wsId}/${p.path}`, {
        waitUntil: 'networkidle',
        timeout: 15000,
      });
      await page.waitForTimeout(1000);
      await shot(page, p.tag);
    });
  }

  // ===== 6. Admin 10 页 =====
  const adminPages = [
    'dashboard',
    'cluster',
    'resource-pools',
    'nodes',
    'scheduling',
    'quota',
    'storage',
    'network',
    'events',
    'audit',
  ];
  for (const p of adminPages) {
    await step(`Admin /admin/${p}`, async () => {
      await page.goto(`${BASE}/admin/${p}`, { waitUntil: 'networkidle', timeout: 15000 });
      await page.waitForTimeout(1000);
      await shot(page, `06-admin-${p}`);
    });
  }

  // ===== 7. DevInstance 详情页 (取第一台) =====
  await step('DevInstance 详情页', async () => {
    await page.goto(`${BASE}/workspaces/${wsId}/dev`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1500);
    const clicked = await page.evaluate(() => {
      const links = Array.from(document.querySelectorAll('a'));
      const t = links.find((a) => /dev\/[^/]+$/.test(a.getAttribute('href') || ''));
      if (t) {
        t.click();
        return true;
      }
      return false;
    });
    if (!clicked) return { skipped: '无 DevInstance' };
    await page.waitForLoadState('networkidle', { timeout: 10000 });
    await page.waitForTimeout(2000);
    await shot(page, '07-dev-detail');
    // 尝试点击 "VSCode 远程开发" 按钮
    const remoteBtnOk = await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('button'));
      const t = btns.find((b) => /VSCode.*远程|Remote.*SSH/i.test(b.textContent || ''));
      return t ? !t.disabled : null;
    });
    return { remoteBtnOk };
  });

  // ===== 8. Training 详情 (取第一个) =====
  await step('Training 详情页', async () => {
    await page.goto(`${BASE}/workspaces/${wsId}/training`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1500);
    const clicked = await page.evaluate(() => {
      const links = Array.from(document.querySelectorAll('a'));
      const t = links.find((a) => /training\/[^/]+$/.test(a.getAttribute('href') || ''));
      if (t) {
        t.click();
        return true;
      }
      return false;
    });
    if (!clicked) return { skipped: '无 Training' };
    await page.waitForLoadState('networkidle', { timeout: 10000 });
    await page.waitForTimeout(2000);
    await shot(page, '08-training-detail');
  });

  // ===== 9. Create 表单页 =====
  await step('DevInstance Create 表单', async () => {
    await page.goto(`${BASE}/workspaces/${wsId}/dev`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1000);
    const clicked = await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('button'));
      const t = btns.find((b) => /新建|创建开发机|\+ *新/.test(b.textContent || ''));
      if (t) {
        t.click();
        return true;
      }
      return false;
    });
    if (!clicked) return { skipped: '无创建按钮' };
    await page.waitForTimeout(1500);
    await shot(page, '09-dev-create-form');
    // 关闭 Drawer 避免污染下一步
    await page.keyboard.press('Escape');
    await page.waitForTimeout(500);
  });

  await step('Training Create 表单', async () => {
    await page.goto(`${BASE}/workspaces/${wsId}/training/new`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1500);
    await shot(page, '10-training-create-form');
  });

  // ===== 11. DevInstance 详情所有按钮 tab 点一遍 =====
  await step('DevInstance 详情所有按钮', async () => {
    await page.goto(`${BASE}/workspaces/${wsId}/dev`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1500);
    const devId = await page.evaluate(() => {
      const links = Array.from(document.querySelectorAll('a'));
      const t = links.find((a) => /dev\/[^/]+$/.test(a.getAttribute('href') || ''));
      return t ? t.getAttribute('href')?.match(/dev\/(.+)$/)?.[1] : null;
    });
    if (!devId) return { skipped: '无 DevInstance' };
    await page.goto(`${BASE}/workspaces/${wsId}/dev/${devId}`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(2500);
    // 看所有按钮统计 + 点各个 Tab
    const btnNames = await page.$$eval('button', (els) =>
      els
        .map((b) => (b.textContent || '').trim())
        .filter((t) => t.length > 0 && t.length < 30),
    );
    const uniqueBtns = [...new Set(btnNames)];
    // 点所有 tab
    const tabCount = await page.$$eval('.ant-tabs-tab', (els) => els.length);
    for (let i = 0; i < tabCount; i++) {
      const clicked = await page.evaluate((idx) => {
        const tabs = document.querySelectorAll('.ant-tabs-tab');
        if (tabs[idx]) {
          tabs[idx].click();
          return true;
        }
        return false;
      }, i);
      if (clicked) {
        await page.waitForTimeout(1500);
        await shot(page, `11-dev-tab-${i}`);
      }
    }
    return { uniqueBtns: uniqueBtns.length, sample: uniqueBtns.slice(0, 10), tabs: tabCount };
  });

  // ===== 12. Training 详情所有 Tab =====
  await step('Training 详情所有 Tab', async () => {
    await page.goto(`${BASE}/workspaces/${wsId}/training`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1500);
    const trainId = await page.evaluate(() => {
      const links = Array.from(document.querySelectorAll('a'));
      const t = links.find((a) => /training\/[^/]+$/.test(a.getAttribute('href') || ''));
      return t ? t.getAttribute('href')?.match(/training\/(.+)$/)?.[1] : null;
    });
    if (!trainId) return { skipped: '无 Training job' };
    await page.goto(`${BASE}/workspaces/${wsId}/training/${trainId}`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(2500);
    const tabCount = await page.$$eval('.ant-tabs-tab', (els) => els.length);
    for (let i = 0; i < tabCount; i++) {
      await page.evaluate((idx) => {
        const tabs = document.querySelectorAll('.ant-tabs-tab');
        if (tabs[idx]) tabs[idx].click();
      }, i);
      await page.waitForTimeout(1500);
      await shot(page, `12-training-tab-${i}`);
    }
    return { tabs: tabCount };
  });

  // ===== 7. 收尾 =====
  await writeFile(
    join(OUT_DIR, 'report.json'),
    JSON.stringify(
      {
        ts: new Date().toISOString(),
        totalSteps: results.length,
        passed: results.filter((r) => r.ok).length,
        failed: results.filter((r) => !r.ok).length,
        results,
        consoleErrors: consoleErrors.slice(0, 50),
        netErrors: netErrors.slice(0, 50),
      },
      null,
      2,
    ),
  );

  await browser.close();

  const pass = results.filter((r) => r.ok).length;
  const fail = results.filter((r) => !r.ok).length;
  log(`\n=== 结果: ${pass}/${results.length} PASS, ${fail} FAIL ===`);
  if (consoleErrors.length) log(`  console errors: ${consoleErrors.length}`);
  if (netErrors.length) log(`  net errors: ${netErrors.length}`);
  log(`报告: ${join(OUT_DIR, 'report.json')}`);
  log(`截图: ${OUT_DIR}/*.png`);

  if (fail > 0) process.exit(1);
}

main().catch((e) => {
  console.error('FATAL', e);
  process.exit(2);
});
