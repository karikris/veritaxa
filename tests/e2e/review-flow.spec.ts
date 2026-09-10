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
  await expect(page.locator('input[type="email"]')).toHaveCount(0);
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
  await expect(page.locator('input[name="review-label"]')).toHaveCount(16);
  await expect(page.getByText('Target scientific name')).toBeVisible();
  await expect(page.getByText('Papilio exemplaris', { exact: true })).toBeVisible();
  await expect(page.locator('body')).not.toContainText('model output');
  await expect(page.locator('body')).not.toContainText('synthetic lepidoptera keyword');

  const stageBox = await page.locator('.image-stage').boundingBox();
  const imageBox = await reviewImage.boundingBox();
  expect(stageBox).not.toBeNull();
  expect(imageBox).not.toBeNull();
  expect(imageBox?.width ?? Infinity).toBeLessThanOrEqual(stageBox?.width ?? 0);
  expect(imageBox?.height ?? Infinity).toBeLessThanOrEqual(stageBox?.height ?? 0);
  await expect(page.getByRole('button', { name: 'Zoom out' })).toBeDisabled();
  await expect(page.getByRole('button', { name: /Reset image zoom/ })).toHaveText('100%');
  await page.getByRole('button', { name: 'Zoom in' }).click();
  await page.getByRole('button', { name: 'Zoom in' }).click();
  await expect(reviewImage).toHaveAttribute('data-zoom', '1.5');
  await expect(page.getByRole('button', { name: /Reset image zoom/ })).toHaveText('150%');
  await page.getByRole('button', { name: /Reset image zoom/ }).click();
  await expect(reviewImage).toHaveAttribute('data-zoom', '1');

  await page.getByText('Papilio exemplaris', { exact: true }).click();
  await page.getByRole('button', { name: 'Zoom in' }).click();
  await page.getByLabel('Comment').fill('Synthetic note');
  await page.getByRole('button', { name: 'Save this classification' }).click();
  await expect(reviewImage).toHaveAttribute('src', /review-002\.svg/);
  await expect(reviewImage).toHaveAttribute('data-zoom', '1');
  await expect(page.locator('input[name="review-label"]')).toHaveCount(15);
  await expect(page.getByText('Target scientific name')).toHaveCount(0);
  await expect(page.locator('.header-progress')).toHaveText('1 / 2');
  await expect(page.locator('.classification-panel')).toBeFocused();

  await page.getByText('Moth', { exact: true }).click();
  await page.getByLabel('Comment').fill('force-save-failure');
  await page.getByRole('button', { name: 'Save this classification' }).click();
  await expect(page.getByText('Synthetic save failure')).toBeVisible();
  await expect(reviewImage).toHaveAttribute('src', /review-002\.svg/);
  await expect(page.getByLabel('Comment')).toHaveValue('force-save-failure');
  await expect(page.getByRole('button', { name: 'Retry original save' })).toHaveText('Retry save');

  await page.getByRole('button', { name: 'Retry original save' }).click();
  await expect(page.getByText('All reviewed—answers can still be updated.')).toBeVisible();
  await expect(reviewImage).toHaveAttribute('src', /review-001\.svg/);
  await expect(page.getByRole('button', { name: 'Previous image' })).toBeEnabled();
  await expect(page.getByRole('button', { name: 'Next image' })).toBeEnabled();
  await expect(page.locator('input[value="target_scientific_name"]')).toBeChecked();
  await expect(page.getByLabel('Comment')).toHaveValue('Synthetic note');

  const nextImageRequests = images.filter((url) => url.includes('review-002'));
  expect(new Set(nextImageRequests).size).toBeLessThanOrEqual(1);
});

test('previous and next skip without saving and restore unsaved drafts', async ({ page }) => {
  await routeSyntheticImages(page, []);
  await page.goto('/veritaxa/?repository=synthetic');

  await page.getByText('Adult butterfly', { exact: true }).click();
  await page.getByLabel('Comment').fill('Unsaved browser draft');
  await page.getByRole('button', { name: 'Next image' }).click();
  await expect(page.locator('.image-position')).toHaveText('2 / 2');
  await expect(page.locator('input[name="review-label"]:checked')).toHaveCount(0);
  await expect(page.getByLabel('Comment')).toHaveValue('');

  await page.getByRole('button', { name: 'Previous image' }).click();
  await expect(page.locator('.image-position')).toHaveText('1 / 2');
  await expect(page.locator('input[value="adult_butterfly"]')).toBeChecked();
  await expect(page.getByLabel('Comment')).toHaveValue('Unsaved browser draft');
  await expect(page.locator('.header-progress')).toHaveText('0 / 2');
});

test('retry confirms the original write without losing edits made after failure', async ({
  page,
}) => {
  await routeSyntheticImages(page, []);
  await page.goto('/veritaxa/?repository=synthetic');
  await page.getByText('Plant', { exact: true }).click();
  await page.getByLabel('Comment').fill('force-save-failure');
  await page.getByRole('button', { name: 'Save this classification' }).click();
  await expect(page.getByText('Synthetic save failure')).toBeVisible();
  await page.getByText('Bird', { exact: true }).click();
  await page.getByLabel('Comment').fill('Newer draft');
  await page.getByRole('button', { name: 'Retry original save' }).click();
  await expect(
    page.getByText('Original save confirmed. Your newer changes are still unsaved.'),
  ).toBeVisible();
  await expect(page.locator('.image-position')).toHaveText('1 / 2');
  await expect(page.locator('input[value="bird"]')).toBeChecked();
  await expect(page.getByLabel('Comment')).toHaveValue('Newer draft');
  await page.getByRole('button', { name: 'Save this classification' }).click();
  await expect(page.locator('.image-position')).toHaveText('2 / 2');
  await page.getByRole('button', { name: 'Previous image' }).click();
  await expect(page.locator('input[value="bird"]')).toBeChecked();
  await expect(page.getByLabel('Comment')).toHaveValue('Newer draft');
});

test('compares a stale answer and reapplies only after an explicit choice', async ({ page }) => {
  await routeSyntheticImages(page, []);
  await page.goto('/veritaxa/tests/fixtures/synthetic-only/conflict.html');
  await page.getByText('Plant', { exact: true }).click();
  await page.getByLabel('Comment').fill('My draft');
  await page.getByRole('button', { name: 'Save this classification' }).click();
  await page.getByRole('button', { name: 'Compare saved answer' }).click();
  const comparison = page.getByRole('region', { name: 'Saved answer comparison' });
  await expect(comparison).toContainText('Saved elsewhere');
  await expect(comparison).toContainText('Bird');
  await expect(page.locator('input[value="plant"]')).toBeChecked();
  await expect(page.getByLabel('Comment')).toHaveValue('My draft');
  await page.getByRole('button', { name: 'Reapply my changes' }).click();
  await expect(page.locator('.image-position')).toHaveText('1 / 2');
  await page.getByRole('button', { name: 'Save this classification' }).click();
  await expect(page.locator('.image-position')).toHaveText('2 / 2');
  await page.getByRole('button', { name: 'Previous image' }).click();
  await expect(page.locator('input[value="plant"]')).toBeChecked();
  await expect(page.getByLabel('Comment')).toHaveValue('My draft');
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
  await page.keyboard.press('ArrowRight');
  await expect(page.locator('.image-position')).toHaveText('1 / 2');

  await page.locator('.classification-panel').focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.locator('.image-position')).toHaveText('2 / 2');

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
