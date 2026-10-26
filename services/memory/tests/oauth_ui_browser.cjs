// Browser checks for the rendered memory OAuth page, with all network calls mocked.
const assert = require('node:assert/strict');
const { chromium } = require('../../../apps/cards-web/node_modules/playwright');

// The page loads the product's typefaces from Google Fonts; the test needs neither the network nor the files.
const FONT_HOSTS = new Set(['fonts.googleapis.com', 'fonts.gstatic.com']);

async function main() {
  let input = '';
  for await (const chunk of process.stdin) input += chunk;
  const { login, callback } = JSON.parse(input);
  const browser = await chromium.launch({ headless: true });
  try {
    for (const viewport of [{ width: 1280, height: 800 }, { width: 375, height: 812 }]) {
      for (const decision of ['approve', 'deny', 'failure']) {
        const context = await browser.newContext({ viewport });
        const page = await context.newPage();
        const posts = [];
        await page.route('**/*', async (route) => {
          const url = new URL(route.request().url());
          if (FONT_HOSTS.has(url.hostname)) {
            await route.fulfill({ contentType: 'text/css', body: '' });
          } else if (url.hostname === 'cdn.jsdelivr.net') {
            await route.fulfill({ contentType: 'application/javascript', body: `window.supabase = {
              createClient: () => ({auth: {getSession: async () => ({data: {session: {access_token: 'mock-session'}}})}})
            };` });
          } else if (url.pathname === '/oauth/login') {
            await route.fulfill({ contentType: 'text/html', body: login });
          } else if (url.pathname === '/oauth/consent' || url.pathname === '/oauth/complete') {
            const body = JSON.parse(route.request().postData());
            posts.push({ path: url.pathname, body });
            if (url.pathname === '/oauth/consent') {
              await route.fulfill({ json: {
                email: 'verified@example.test', client_name: '<img src=x onerror=alert(1)>',
                resource: 'https://api.example/mcp', scope: 'user'
              } });
            } else if (decision === 'failure') {
              await route.fulfill({ status: 400, json: { detail: '<b>Request expired</b>' } });
            } else {
              await route.fulfill({ json: { redirect_url: `http://oauth.test/result?decision=${decision}` } });
            }
          } else if (url.pathname === '/result') {
            await route.fulfill({ contentType: 'text/html', body: '<p>Redirected</p>' });
          } else {
            throw new Error(`Unexpected external request: ${url}`);
          }
        });
        await page.goto('http://oauth.test/oauth/login?zynd_oauth=sealed-request');
        await page.locator('#consent').waitFor({ state: 'visible' });
        assert.deepEqual(posts.map((post) => post.path), ['/oauth/consent']);
        assert.equal(posts[0].body.req, 'sealed-request');
        assert.equal(posts[0].body.supabase_token, 'mock-session');
        assert.equal(await page.locator('#signin').isVisible(), false);
        assert.equal(await page.locator('h1').textContent(), 'Approve connection');
        if (viewport.height === 800) {
          // Both choices stay on screen without scrolling at laptop height.
          const bottom = await page.locator('#cancel').evaluate((el) => el.getBoundingClientRect().bottom);
          assert.ok(bottom <= viewport.height, `Cancel falls below the fold: ${bottom}`);
        }
        assert.equal(await page.locator('#identity').textContent(), 'verified@example.test');
        assert.equal(await page.locator('#client img').count(), 0);
        assert.match(await page.locator('#client').textContent(), /<img/);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
        await page.locator(decision === 'deny' ? '#cancel' : '#allow').click();
        if (decision === 'failure') {
          await page.locator('#error').waitFor({ state: 'visible' });
          assert.equal(await page.locator('#error').textContent(), '<b>Request expired</b>');
          assert.equal(await page.locator('#error b').count(), 0);
          assert.equal(await page.locator('#consent').isVisible(), true);
          assert.equal(await page.locator('#signin').isVisible(), false);
          assert.equal(await page.locator('#allow').isEnabled(), true);
        } else {
          await page.waitForURL(`**/result?decision=${decision}`);
        }
        assert.deepEqual(posts.map((post) => post.path), ['/oauth/consent', '/oauth/complete']);
        assert.equal(posts[1].body.decision, decision === 'deny' ? 'deny' : 'approve');
        await context.close();
      }
    }
    const context = await browser.newContext();
    const page = await context.newPage();
    await page.addInitScript(() => {
      const getItem = Storage.prototype.getItem;
      Storage.prototype.getItem = function (key) {
        if (key === 'zynd_oauth_req') throw new Error('Storage blocked');
        return getItem.call(this, key);
      };
      const replaceState = history.replaceState.bind(history);
      history.replaceState = (...args) => {
        sessionStorage.setItem('hash-cleared', String(args[2]));
        return replaceState(...args);
      };
      window.supabase = { createClient: () => ({ auth: {
        getSession: async () => ({ data: { session: { access_token: 'mock-session' } } })
      } }) };
    });
    await page.route('**/*', async (route) => {
      const url = new URL(route.request().url());
      if (FONT_HOSTS.has(url.hostname)) {
        await route.fulfill({ contentType: 'text/css', body: '' });
      } else if (url.hostname === 'cdn.jsdelivr.net') {
        await route.fulfill({ contentType: 'application/javascript', body: '' });
      } else if (url.pathname === '/oauth/login/callback') {
        await route.fulfill({ contentType: 'text/html', body: callback });
      } else if (url.pathname === '/oauth/login') {
        await route.fulfill({ contentType: 'text/html', body: login });
      } else if (url.pathname === '/oauth/consent') {
        await route.fulfill({ json: {
          email: 'verified@example.test', client_name: 'Test client',
          resource: 'https://api.example/mcp', scope: 'user'
        } });
      } else {
        throw new Error(`Unexpected external request: ${url}`);
      }
    });
    await page.goto('http://oauth.test/oauth/login/callback?zynd_oauth=sealed-request#access_token=sensitive');
    await page.waitForURL('**/oauth/login?zynd_oauth=sealed-request');
    await page.locator('#consent').waitFor({ state: 'visible' });
    assert.equal(await page.evaluate(() => sessionStorage.getItem('hash-cleared')),
      '/oauth/login/callback?zynd_oauth=sealed-request');
    assert.equal(page.url().includes('sensitive'), false);
    await context.close();
  } finally {
    await browser.close();
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
