const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  page.on('console', msg => console.log('BROWSER LOG:', msg.text()));
  page.on('pageerror', err => console.log('BROWSER ERROR:', err));
  
  await page.goto('http://localhost:8000');
  
  // Wait a bit
  await page.waitForTimeout(2000);
  await browser.close();
})();
