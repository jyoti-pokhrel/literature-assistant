const { test, expect } = require("@playwright/test");

test.describe("explore feed", () => {
  test("cold-start onboarding renders, accepts seeds, transitions to feed", async ({ page }) => {
    await page.goto("/workspace/explore");

    // Cold-start panel should be visible at first
    await expect(page.getByText(/Tell us what you're into/i)).toBeVisible({ timeout: 10_000 });

    // Type three seed topics
    const inputs = page.locator('input[placeholder^="Topic"]');
    await inputs.nth(0).fill("graph neural networks");
    await inputs.nth(1).fill("attention mechanisms");
    await inputs.nth(2).fill("self-supervised learning");

    await page.getByRole("button", { name: /Build my feed/i }).click();

    // Either we land on a populated feed OR the diagnostics-driven empty state
    // (both are acceptable end states for this smoke).
    await expect(async () => {
      const heading = await page.locator("h2.results-query-title").innerText();
      expect(heading.length).toBeGreaterThan(0);
    }).toPass({ timeout: 30_000 });
  });
});
