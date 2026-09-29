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

test('reviewer save retry, progress, and completion flow', async ({ page }) => {
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

test('preview failure never downloads the source until inspection is requested', async ({
  page,
}) => {
  const images: string[] = [];
  await routeSyntheticImages(page, images);
  await page.route('https://images.example.invalid/review-001.svg', (route) =>
    route.abort('failed'),
  );
  await page.goto('/veritaxa/?repository=synthetic');
  await expect(page.getByText('No preview is available.', { exact: false })).toBeVisible();
  expect(images.some((url) => url.includes('original'))).toBe(false);
  await page.getByText('Plant', { exact: true }).click();
  await page.getByLabel('Comment').fill('Synthetic retained edit');
  await page.getByRole('button', { name: 'Inspect source image' }).click();
  const source = page.locator('img.review-image');
  await expect(source).toHaveAttribute('src', /review-001-original\.svg/);
  const retained = await source.elementHandle();
  await page.getByRole('button', { name: 'Return to preview' }).click();
  await expect(page.locator('img')).toHaveCount(0);
  expect(await retained.getAttribute('src')).toBeNull();
  await retained.dispose();
  await expect(page.getByLabel('Comment')).toHaveValue('Synthetic retained edit');
  await expect(page.locator('input[value="plant"]')).toBeChecked();
  await page.getByRole('button', { name: 'Next image' }).click();
  await expect(page.locator('img')).toHaveAttribute('src', /review-002\.svg/);
  await expect(page.getByRole('button', { name: 'Inspect source image' })).toBeVisible();
  expect(images.filter((url) => url.includes('original'))).toHaveLength(1);
});

test('an oversized supplied preview is released but can be inspected explicitly', async ({
  page,
}) => {
  await page.route('https://images.example.invalid/**', (route) =>
    route.fulfill({
      contentType: 'image/svg+xml',
      body: syntheticImage.replace('width="960" height="640"', 'width="3200" height="2400"'),
    }),
  );
  await page.goto('/veritaxa/?repository=synthetic');
  await expect(page.getByText('Preview exceeded 1,600 pixels', { exact: false })).toBeVisible();
  await expect(page.locator('img')).toHaveCount(0);
  await page.getByRole('button', { name: 'Inspect source image' }).click();
  await expect
    .poll(() => page.locator('img').evaluate((image: HTMLImageElement) => image.naturalWidth))
    .toBe(3200);
  await expect(page.locator('img')).toHaveCount(1);
  await page.getByRole('button', { name: 'Return to preview' }).click();
  await expect(page.getByText('Preview exceeded 1,600 pixels', { exact: false })).toBeVisible();
  await expect(page.locator('img')).toHaveCount(0);
});

test('ordinary edits preserve real browser nodes, focus, caret and the loaded image', async ({
  page,
}) => {
  const images: string[] = [];
  await routeSyntheticImages(page, images);
  await page.goto('/veritaxa/?repository=synthetic');
  const image = page.locator('img.review-image');
  await expect(image).toHaveAttribute('src', /review-001\.svg/);
  await expect
    .poll(() => image.evaluate((node: HTMLImageElement) => node.complete && node.naturalWidth > 0))
    .toBe(true);
  const count = images.length;
  const nodes = await page.evaluateHandle(() =>
    Array.from(
      document.querySelectorAll(
        '.app-shell, .site-header, #batch-select, .review-main, img.review-image, .classification-panel, input[name="review-label"], #review-comment, .send-button',
      ),
    ),
  );
  try {
    await page.getByRole('button', { name: 'Zoom in' }).click();
    const radio = page.locator('input[value="plant"]');
    await radio.focus();
    await page.keyboard.press('Space');
    await expect(radio).toBeChecked();
    await expect(radio).toBeFocused();
    const comment = page.getByLabel('Comment');
    await comment.fill('Synthetic edit');
    await comment.evaluate((node: HTMLTextAreaElement) => node.setSelectionRange(5, 5));
    await page.keyboard.type('🦋');
    await expect(comment).toBeFocused();
    expect(
      await comment.evaluate((node: HTMLTextAreaElement) => [
        node.selectionStart,
        node.selectionEnd,
      ]),
    ).toEqual([7, 7]);
    await expect(image).toHaveAttribute('data-zoom', '1.25');
    expect(
      await page.evaluate((retained) => retained.every((node) => node.isConnected), nodes),
    ).toBe(true);
    expect(images).toHaveLength(count);
  } finally {
    await nodes.dispose();
  }
});

for (const budget of ['count', 'bytes'] as const) {
  test(`unsaved draft ${budget} limit requires explicit resolution in the browser`, async ({
    page,
  }) => {
    await routeSyntheticImages(page, []);
    await page.goto('/veritaxa/tests/fixtures/synthetic-only/long-session.html');
    await expect(page.locator('.image-position')).toHaveText('1 / 1000');
    const position = await page.evaluate(async (limit) => {
      const radio = document.querySelector<HTMLInputElement>('input[value="plant"]');
      const comment = document.querySelector<HTMLTextAreaElement>('#review-comment');
      const next = document.querySelector<HTMLButtonElement>('[aria-label="Next image"]');
      const warning = document.querySelector<HTMLElement>('.draft-limit');
      if (!radio || !comment || !next || !warning) throw new Error('Missing review controls');
      for (let position = 1; position <= 256; position += 1) {
        radio.click();
        comment.value = limit === 'bytes' ? '\u0001'.repeat(1000) : `Unsaved ${String(position)}`;
        comment.dispatchEvent(new Event('input', { bubbles: true }));
        next.click();
        await new Promise<void>((resolve) => queueMicrotask(resolve));
        if (!warning.hidden) return position;
      }
      throw new Error('Draft budget did not stop navigation');
    }, budget);
    if (budget === 'count') expect(position).toBe(256);
    else expect(position).toBeLessThan(256);
    await expect(page.getByRole('region', { name: 'Unsaved draft limit' })).toBeVisible();
    await expect(page.getByLabel('Comment')).toHaveValue(
      budget === 'bytes' ? '\u0001'.repeat(1000) : `Unsaved ${String(position)}`,
    );
    await page.getByRole('button', { name: 'Discard local edits' }).click();
    await expect(page.getByLabel('Comment')).toHaveValue('');
    await page.getByRole('button', { name: 'Next image' }).click();
    await expect(page.locator('.image-position')).toHaveText(`${String(position + 1)} / 1000`);
    await page.getByRole('button', { name: 'Previous image' }).click();
    await expect(page.getByLabel('Comment')).toHaveValue('');
    await page.getByRole('button', { name: 'Previous image' }).click();
    await expect(page.getByLabel('Comment')).toHaveValue(
      budget === 'bytes' ? '\u0001'.repeat(1000) : `Unsaved ${String(position - 1)}`,
    );
    await expect(page.locator('input[value="plant"]')).toBeChecked();
  });
}

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
  await expect(page.getByText('No preview is available.', { exact: false })).toBeVisible();
  await expect(page.locator('img.review-image')).toHaveCount(0);
  await page.getByRole('button', { name: 'Inspect source image' }).click();
  await expect(page.locator('img.review-image')).toHaveAttribute('src', /review-003\.svg/);
  await expect(page.locator('input[name="review-label"]:checked')).toHaveCount(0);
  await expect(page.getByLabel('Comment')).toHaveValue('');

  await page.reload();
  await expect(page.getByLabel('Review batch')).toHaveValue('30000000-0000-0000-0000-000000000002');
  await expect(page.locator('img.review-image')).toHaveCount(0);
  await page.getByRole('button', { name: 'Inspect source image' }).click();
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
