import { expect, test, type Page } from '@playwright/test';

const syntheticImage = `
<svg xmlns="http://www.w3.org/2000/svg" width="960" height="640" viewBox="0 0 960 640">
  <rect width="960" height="640" fill="#202620"/>
  <circle cx="480" cy="300" r="150" fill="#b9dc82"/>
  <path d="M480 160C390 95 290 145 300 255c8 86 105 108 180 45 75 63 172 41 180-45 10-110-90-160-180-95Z" fill="#46593b"/>
  <text x="480" y="520" text-anchor="middle" fill="#eef2ed" font-family="sans-serif" font-size="34">Synthetic review image</text>
</svg>`;

async function routeSyntheticImages(page: Page, requested: string[]): Promise<void> {
  await page.route('https://images.example.invalid/**', async (route) => {
    requested.push(route.request().url());
    if (route.request().url().includes('display-fail')) {
      await route.abort('failed');
      return;
    }
    await route.fulfill({ contentType: 'image/svg+xml', body: syntheticImage });
  });
}

test('signed-out shell fetches no task or image data', async ({ page }) => {
  const requests: string[] = [];
  page.on('request', (request) => requests.push(request.url()));

  await page.goto('/veritaxa/');

  await expect(page.getByLabel('Name')).toBeVisible();
  await expect(page.getByLabel('Email address')).toBeVisible();
  await expect(page.locator('input[type="password"]')).toHaveCount(0);
  await expect(page.getByRole('tab')).toHaveCount(0);
  await expect(page.locator('nav')).toHaveCount(0);
  await expect(page.locator('img')).toHaveCount(0);
  expect(requests.some((url) => url.includes('/rest/v1/rpc/'))).toBe(false);
  expect(requests.some((url) => url.includes('images.example.invalid'))).toBe(false);
});

test('reviewer fallback, save retry, progress, and completion flow', async ({ page }) => {
  const images: string[] = [];
  await routeSyntheticImages(page, images);
  await page.goto('/veritaxa/?repository=synthetic');

  const reviewImage = page.locator('img.review-image');
  await expect(reviewImage).toHaveAttribute('alt', 'Image under review');
  await expect(reviewImage).toHaveAttribute('src', /review-001\.svg/);
  await expect(page.locator('img.review-image')).toHaveCount(1);
  await expect(page.locator('input[name="review-label"]')).toHaveCount(15);
  await expect(page.locator('body')).not.toContainText('model output');
  await expect(page.locator('body')).not.toContainText('scientific name');

  await page.getByText('Adult butterfly', { exact: true }).click();
  await page.getByLabel('Comment').fill('Synthetic note');
  await page.getByRole('button', { name: 'Save this classification' }).click();
  await expect(reviewImage).toHaveAttribute('src', /review-002\.svg/);
  await expect(page.locator('.header-progress')).toHaveText('1 / 2');
  await expect(page.locator('.classification-panel')).toBeFocused();

  await page.getByText('Moth', { exact: true }).click();
  await page.getByLabel('Comment').fill('force-save-failure');
  await page.getByRole('button', { name: 'Save this classification' }).click();
  await expect(page.getByText('Synthetic save failure')).toBeVisible();
  await expect(reviewImage).toHaveAttribute('src', /review-002\.svg/);
  await expect(page.getByLabel('Comment')).toHaveValue('force-save-failure');
  await expect(page.getByRole('button', { name: 'Save this classification' })).toHaveText(
    'Retry save',
  );

  await page.getByRole('button', { name: 'Save this classification' }).click();
  await expect(page.getByRole('heading', { name: 'Batch complete' })).toBeVisible();
  await expect(page.getByText('2 / 2 reviewed')).toBeVisible();

  const nextImageRequests = images.filter((url) => url.includes('review-002'));
  expect(new Set(nextImageRequests).size).toBeLessThanOrEqual(1);
});

test('keyboard shortcuts ignore editable fields and batch selection survives reload', async ({
  page,
}) => {
  await routeSyntheticImages(page, []);
  await page.goto('/veritaxa/?repository=synthetic');
  await expect(page.locator('img.review-image')).toBeVisible();

  await page.keyboard.press('b');
  await expect(page.locator('input[value="adult_butterfly"]')).toBeChecked();
  await page.getByLabel('Comment').focus();
  await page.keyboard.press('m');
  await expect(page.locator('input[value="moth"]')).not.toBeChecked();

  await page.getByLabel('Review batch').selectOption('30000000-0000-0000-0000-000000000002');
  await expect(page.locator('img.review-image')).toHaveAttribute('src', /review-003\.svg/);
  await expect(page.locator('input[name="review-label"]:checked')).toHaveCount(0);
  await expect(page.getByLabel('Comment')).toHaveValue('');

  await page.reload();
  await expect(page.getByLabel('Review batch')).toHaveValue('30000000-0000-0000-0000-000000000002');
  await expect(page.locator('img.review-image')).toHaveCount(1);
});

test('layout stays within the mobile viewport', async ({ page }) => {
  await routeSyntheticImages(page, []);
  await page.goto('/veritaxa/?repository=synthetic');

  const widths = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    content: document.documentElement.scrollWidth,
  }));
  expect(widths.content).toBeLessThanOrEqual(widths.viewport);
  await expect(page.getByRole('button', { name: 'Save this classification' })).toBeVisible();
});
