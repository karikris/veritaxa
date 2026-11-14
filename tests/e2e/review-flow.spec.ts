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

test('Yes and No submit immediately and preserve answers for corrections', async ({ page }) => {
  const images: string[] = [];
  await routeSyntheticImages(page, images);
  await page.goto('/veritaxa/?repository=synthetic');
  const image = page.locator('img.review-image');
  await expect(image).toHaveAttribute('src', /review-001\.svg/);
  await expect(page.locator('.answer-button')).toHaveCount(5);
  await expect(page.getByRole('heading', { name: 'Is this Papilio exemplaris?' })).toBeVisible();
  await expect(page.locator('input[name="review-label"]')).toHaveCount(0);
  await expect(page.getByLabel('Comment')).toHaveCount(0);
  await expect(page.getByLabel('Choose a dataset ↓')).toBeVisible();
  await expect(page.locator('.dataset-label')).toBeVisible();
  await expect(page.locator('.image-review-status')).toHaveText('Needs review in this dataset');
  await expect(page.getByRole('button', { name: 'Send', exact: true })).toHaveCount(0);
  await expect(page.locator('body')).not.toContainText('model output');
  await expect(page.locator('body')).not.toContainText('synthetic lepidoptera keyword');

  await page.getByRole('button', { name: 'Zoom in', exact: true }).click();
  await expect(image).toHaveAttribute('data-zoom', '1.25');
  await page.getByRole('button', { name: 'Papilio exemplaris', exact: true }).click();
  await expect(image).toHaveAttribute('src', /review-002\.svg/);
  await expect(image).toHaveAttribute('data-zoom', '1');
  await expect(page.locator('.header-progress')).toHaveText('1 / 2');
  await expect(page.locator('.classification-panel')).toBeFocused();

  await page.getByRole('button', { name: 'Other', exact: true }).click();
  await expect(page.getByText('All reviewed—answers can still be updated.')).toBeVisible();
  await expect(image).toHaveAttribute('src', /review-001\.svg/);
  await expect(
    page.getByText('Your saved answer: Papilio exemplaris. Choose again to update it.'),
  ).toBeVisible();
  await expect(page.locator('.image-review-status')).toHaveText(
    '✓ Reviewed by you in this dataset',
  );
  await page.getByRole('button', { name: 'Next image' }).click();
  await expect(
    page.getByText('Your saved answer: Other. Choose again to update it.'),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Papilio exemplaris', exact: true }).click();
  await expect(image).toHaveAttribute('src', /review-001\.svg/);
  await expect(page.locator('.header-progress')).toHaveText('2 / 2');
  await page.getByRole('button', { name: 'Next image' }).click();
  await expect(
    page.getByText('Your saved answer: Papilio exemplaris. Choose again to update it.'),
  ).toBeVisible();
  expect(new Set(images.filter((url) => url.includes('review-002'))).size).toBe(1);
});

test('a failed automatic save keeps the image until the reviewer retries', async ({ page }) => {
  await routeSyntheticImages(page, []);
  await page.goto('/veritaxa/?repository=synthetic&saveFailure=once');
  const image = page.locator('img.review-image');
  await expect(image).toHaveAttribute('src', /review-001\.svg/);
  await page.getByRole('button', { name: 'Other', exact: true }).click();
  await expect(page.getByText('Synthetic save failure')).toBeVisible();
  await expect(image).toHaveAttribute('src', /review-001\.svg/);
  await expect(page.locator('.header-progress')).toHaveText('0 / 2');
  await page.getByRole('button', { name: 'Retry save', exact: true }).click();
  await expect(image).toHaveAttribute('src', /review-002\.svg/);
  await expect(page.locator('.header-progress')).toHaveText('1 / 2');
  await page.getByRole('button', { name: 'Previous image' }).click();
  await expect(
    page.getByText('Your saved answer: Other. Choose again to update it.'),
  ).toBeVisible();
});

test('previous and next navigate without recording an answer', async ({ page }) => {
  await routeSyntheticImages(page, []);
  await page.goto('/veritaxa/?repository=synthetic');
  await page.getByRole('button', { name: 'Next image' }).click();
  await expect(page.locator('.image-position')).toHaveText('2 / 2');
  await page.getByRole('button', { name: 'Previous image' }).click();
  await expect(page.locator('.image-position')).toHaveText('1 / 2');
  await expect(page.locator('.header-progress')).toHaveText('0 / 2');
});

test('Y/N submit outside editable controls and batch selection survives reload', async ({
  page,
}) => {
  await routeSyntheticImages(page, []);
  await page.goto('/veritaxa/?repository=synthetic');
  await expect(page.locator('img.review-image')).toBeVisible();
  await page.getByLabel('Choose a dataset ↓').focus();
  await page.keyboard.press('y');
  await expect(page.locator('.header-progress')).toHaveText('0 / 2');
  await page.locator('.classification-panel').focus();
  await page.keyboard.press('y');
  await expect(page.locator('.image-position')).toHaveText('2 / 2');
  await page.keyboard.press('n');
  await expect(page.locator('.header-progress')).toHaveText('2 / 2');
  await page.getByLabel('Choose a dataset ↓').selectOption('30000000-0000-0000-0000-000000000002');
  await expect(page.getByRole('heading', { name: 'Is this Danaus exemplaris?' })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel('Choose a dataset ↓')).toHaveValue(
    '30000000-0000-0000-0000-000000000002',
  );
  await expect(page.locator('img.review-image')).toHaveCount(1);
});

test('model prediction and caterpillar both save immediately with corrections', async ({
  page,
}) => {
  await routeSyntheticImages(page, []);
  await page.goto('/veritaxa/?repository=synthetic');
  await page
    .getByRole('button', { name: 'Papilio testensis · cosine 0.6789', exact: true })
    .click();
  await expect(page.locator('.image-position')).toHaveText('2 / 2');
  await page.getByRole('button', { name: 'Previous image' }).click();
  await expect(
    page.getByText('Your saved answer: Papilio testensis. Choose again to update it.'),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Caterpillar', exact: true }).click();
  await expect(page.locator('.image-position')).toHaveText('2 / 2');
  await page.getByRole('button', { name: 'Previous image' }).click();
  await expect(
    page.getByText('Your saved answer: Caterpillar. Choose again to update it.'),
  ).toBeVisible();
});

test('five choices fit within the viewport and remain visible on mobile', async ({ page }) => {
  await routeSyntheticImages(page, []);
  await page.goto('/veritaxa/?repository=synthetic');
  const widths = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    content: document.documentElement.scrollWidth,
  }));
  expect(widths.content).toBeLessThanOrEqual(widths.viewport);
  for (const answer of [
    'Papilio testensis · cosine 0.6789',
    'Papilio exemplaris',
    'Other',
    'No butterfly',
    'Caterpillar',
  ]) {
    const choice = page.getByRole('button', { name: answer, exact: true });
    await expect(choice).toBeInViewport();
    const box = await choice.boundingBox();
    expect(box?.height).toBeGreaterThanOrEqual(44);
  }
});

test('No butterfly saves immediately, can be corrected, and supports the zero shortcut', async ({
  page,
}) => {
  await routeSyntheticImages(page, []);
  await page.goto('/veritaxa/?repository=synthetic');
  await page.getByRole('button', { name: 'No butterfly', exact: true }).click();
  await expect(page.locator('.image-position')).toHaveText('2 / 2');
  await page.getByRole('button', { name: 'Previous image' }).click();
  await expect(
    page.getByText('Your saved answer: No butterfly. Choose again to update it.'),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Papilio exemplaris', exact: true }).click();
  await expect(page.locator('.image-position')).toHaveText('2 / 2');
  await page.keyboard.press('0');
  await expect(page.getByText('All reviewed—answers can still be updated.')).toBeVisible();
  await page.getByRole('button', { name: 'Next image' }).click();
  await expect(
    page.getByText('Your saved answer: No butterfly. Choose again to update it.'),
  ).toBeVisible();
});
