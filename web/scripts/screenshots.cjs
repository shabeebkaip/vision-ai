#!/usr/bin/env node
/*
 * Takes the README screenshots from a running build (mock data).
 *
 *   npm run build && npx vite preview --port 4173 &
 *   node scripts/screenshots.cjs [baseUrl] [outDir]
 *
 * Needs Playwright with Chromium (not a project dependency: `npm i -g playwright` or similar).
 */
/* global document */ // used inside page.evaluate() callbacks, which run in the browser
const path = require('node:path');
const fs = require('node:fs');
const { chromium } = require('playwright');

const BASE = process.argv[2] || 'http://localhost:4173';
const OUT = path.resolve(
  process.argv[3] || path.join(__dirname, '..', '..', 'docs', 'screenshots'),
);
const CAMERA_ID = 'ngm-cashier';

const VIEWPORTS = {
  desktop: { viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 },
  phone: {
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
  },
};

async function signIn(page, lang) {
  await page.goto(`${BASE}/sign-in`);
  await page.evaluate((l) => localStorage.setItem('vision.lang', l), lang);
  await page.reload();
  await page.fill('input[type=email]', 'store.owner@example.sa');
  await page.fill('input[type=password]', 'demo1234');
  await page.click('button[type=submit]');
  await page.waitForURL((u) => !u.pathname.startsWith('/sign-in'));
}

async function settle(page) {
  await page.waitForLoadState('networkidle');
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(700);
}

async function shoot(page, name, fullPage = true) {
  await settle(page);
  const file = path.join(OUT, `${name}.png`);
  const vp = page.viewportSize();
  if (fullPage) {
    // Grow the viewport to the page height instead of Playwright's fullPage stitching, so
    // fixed and sticky bars (side nav, phone tab bar) render where a user would see them.
    const height = await page.evaluate(() => document.documentElement.scrollHeight);
    await page.setViewportSize({ width: vp.width, height: Math.max(vp.height, height) });
    await page.waitForTimeout(400);
  }
  await page.screenshot({ path: file });
  if (fullPage) await page.setViewportSize(vp);
  console.log('saved', file);
}

async function run() {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch();
  const only = process.env.ONLY ? process.env.ONLY.split(',') : null;
  for (const lang of ['en', 'ar']) {
    for (const [vpName, vp] of Object.entries(VIEWPORTS)) {
      const ctx = await browser.newContext({
        ...vp,
        timezoneId: 'Asia/Riyadh',
        locale: lang === 'ar' ? 'ar-SA' : 'en-GB',
      });
      const page = await ctx.newPage();
      page.on('pageerror', (e) => console.error(`[${lang}/${vpName}] page error:`, e.message));
      page.on(
        'console',
        (m) => m.type() === 'error' && console.error(`[${lang}/${vpName}] console:`, m.text()),
      );
      const want = (s) => !only || only.includes(s);
      const suffix = `${lang}-${vpName}`;

      if (want('signin')) {
        await page.goto(`${BASE}/sign-in`);
        await page.evaluate((l) => localStorage.setItem('vision.lang', l), lang);
        await page.reload();
        await shoot(page, `sign-in-${suffix}`, false);
      }
      await signIn(page, lang);

      if (want('overview')) {
        await page.goto(`${BASE}/`);
        await page.waitForSelector('.recharts-bar-rectangle', { timeout: 15000 }).catch(() => {});
        await shoot(page, `overview-${suffix}`);
      }
      if (want('feed')) {
        await page.goto(`${BASE}/events`);
        await page.waitForSelector('ul[aria-label] li');
        await shoot(page, `event-feed-${suffix}`, false);
      }
      if (want('detail')) {
        // An unreviewed queue alert, so the Correct / False alarm buttons are visible.
        await page.goto(`${BASE}/events?site=najd-grill-malqa&type=queue_length_over&verdict=none`);
        await page.locator('ul[aria-label] li a').first().click();
        await page.waitForSelector('text=/Correct|صحيح/');
        await shoot(page, `event-detail-${suffix}`);
      }
      if (want('zones')) {
        await page.goto(`${BASE}/cameras/${CAMERA_ID}/zones`);
        await page.waitForSelector('canvas');
        // Select the first zone from the side panel so its handles are visible.
        await page.locator('aside ul li button').first().click();
        await shoot(page, `zone-editor-${suffix}`);
      }
      if (want('rule')) {
        await page.goto(`${BASE}/rules/new?site=najd-grill-malqa&camera=ngm-cashier`);
        await page.waitForSelector('[data-testid=rule-preview]');
        await page.fill(
          '#rule-name',
          lang === 'ar' ? 'طابور الكاشير طويل' : 'Checkout queue too long',
        );
        await shoot(page, `rule-builder-${suffix}`);
      }
      await ctx.close();
    }
  }
  await browser.close();
}

run().catch((e) => {
  console.error(e);
  process.exit(1);
});
