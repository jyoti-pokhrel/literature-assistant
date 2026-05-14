const { test, expect } = require("@playwright/test");

test.describe("explore feed", () => {
  test("first visit shows the feed directly, no onboarding form", async ({ page }) => {
    await page.goto("/workspace/explore");

    // The old cold-start onboarding heading must NOT appear.
    await expect(page.getByText(/Tell us what you're into/i)).toHaveCount(0, {
      timeout: 5_000,
    });

    // The page title / heading should render either way.
    await expect(async () => {
      const heading = await page.locator("h2.results-query-title").innerText();
      expect(heading.length).toBeGreaterThan(0);
    }).toPass({ timeout: 15_000 });

    // We expect either a list of papers OR the diagnostics empty-state.
    // Both are acceptable "first visit works" outcomes.
    const hasPapers = await page
      .locator("article.gap-card-premium")
      .first()
      .isVisible()
      .catch(() => false);
    const emptyState = await page
      .getByText("No recommendations yet.")
      .isVisible()
      .catch(() => false);
    expect(hasPapers || emptyState).toBe(true);
  });
});
