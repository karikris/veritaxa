import { expect, test, type Page } from '@playwright/test';

// Exercise the built application and its production CSP. Every auth, RPC and
// image response is synthetic, including when checking the deployed Pages URL.
async function openSyntheticReview(page: Page): Promise<void> {
  const user = {
    id: '00000000-0000-4000-8000-000000000001',
    aud: 'authenticated',
    role: 'authenticated',
    user_metadata: { identified_by: 'Synthetic test' },
    app_metadata: {},
    created_at: new Date().toISOString(),
  };
  const expires = Math.floor(Date.now() / 1000) + 3600;
  const accessToken = [
    { alg: 'HS256', typ: 'JWT' },
    { sub: user.id, role: 'authenticated', exp: expires },
    'synthetic-signature',
  ]
    .map((value) =>
      Buffer.from(typeof value === 'string' ? value : JSON.stringify(value)).toString('base64url'),
    )
    .join('.');
  await page.route('https://*.supabase.co/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown;
    if (path === '/auth/v1/signup') {
      data = {
        access_token: accessToken,
        refresh_token: 'synthetic-refresh-token',
        expires_in: 3600,
        expires_at: expires,
        token_type: 'bearer',
        user,
      };
    } else if (path === '/auth/v1/user') data = user;
    else if (path === '/rest/v1/rpc/list_review_batches') {
      data = [
        {
          batch_id: '00000000-0000-4000-8000-000000000002',
          reviewer_name: 'Synthetic dataset',
          batch_code: 'DEMO-A-001',
          reviewed_count: 0,
          total_count: 1,
          complete: false,
        },
      ];
    } else if (path === '/rest/v1/rpc/get_review_cursor') {
      data = [
        {
          item_id: '00000000-0000-4000-8000-000000000003',
          image_id: 'synthetic',
          target_scientific_name: null,
          display_url: 'https://images.example.invalid/preview.svg',
          fallback_image_url: 'https://images.example.invalid/original.svg',
          position: 1,
          current_label: null,
          current_comment: null,
          current_version: 0,
          reviewed_count: 0,
          total_count: 1,
          complete: false,
        },
      ];
    } else {
      await route.abort();
      throw new Error(`Unexpected synthetic API call: ${path}`);
    }
    await route.fulfill({ json: data });
  });
  await page.route('https://images.example.invalid/**', (route) =>
    route.fulfill({
      contentType: 'image/svg+xml',
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800"><rect width="1200" height="800" fill="#263927"/><circle cx="100" cy="100" r="30" fill="#e4d947"/></svg>',
    }),
  );
  await page.goto('./');
  await page.getByLabel('Name', { exact: true }).fill('Synthetic test');
  await page.getByRole('button', { name: 'Start reviewing' }).click();
  await expect
    .poll(() =>
      page.locator('.review-image').evaluate((image: HTMLImageElement) => image.naturalWidth),
    )
    .toBe(1200);
}

async function picture(page: Page) {
  return page.locator('.review-image').evaluate((image: HTMLImageElement) => {
    const box = image.getBoundingClientRect();
    const fit = Math.min(box.width / image.naturalWidth, box.height / image.naturalHeight);
    const width = image.naturalWidth * fit;
    const height = image.naturalHeight * fit;
    const transform = new DOMMatrixReadOnly(getComputedStyle(image).transform);
    return {
      left: box.left + (box.width - width) / 2,
      top: box.top + (box.height - height) / 2,
      width,
      height,
      zoom: transform.a,
      x: transform.m41,
      y: transform.m42,
    };
  });
}

test('production picture supports pointer-focused wheel zoom and dragging to every corner', async ({
  page,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await openSyntheticReview(page);
  const image = page.locator('.review-image');
  const stage = page.locator('.image-stage');
  const reset = page.getByRole('button', { name: /Reset image zoom/ });
  await expect(page.locator('.image-gesture-help')).toBeVisible();
  for (const [fx, fy] of [
    [0.2, 0.2],
    [0.8, 0.2],
    [0.8, 0.8],
    [0.2, 0.8],
  ]) {
    if (await reset.isEnabled()) await reset.click();
    await stage.scrollIntoViewIfNeeded();
    const before = await picture(page);
    const point = { x: before.left + before.width * fx, y: before.top + before.height * fy };
    const scroll = await page.evaluate(() => window.scrollY);
    await page.mouse.move(point.x, point.y);
    await page.mouse.wheel(0, -240);
    await expect.poll(async () => (await picture(page)).zoom).toBeGreaterThan(1);
    const after = await picture(page);
    // The same image point remains under the pointer, including near corners.
    expect((point.x - after.left) / after.width).toBeCloseTo(fx, 2);
    expect((point.y - after.top) / after.height).toBeCloseTo(fy, 2);
    expect(await page.evaluate(() => window.scrollY)).toBe(scroll);
    await page.mouse.down();
    await page.mouse.move(point.x + 30, point.y + 25, { steps: 3 });
    await page.mouse.up();
    const panned = await picture(page);
    expect(panned.x).toBeCloseTo(after.x + 30, 1);
    expect(panned.y).toBeCloseTo(after.y + 25, 1);
    await expect(stage).not.toHaveClass(/dragging/);
  }
  await reset.click();
  await stage.scrollIntoViewIfNeeded();
  const start = await picture(page);
  await page.mouse.dblclick(start.left + start.width * 0.3, start.top + start.height * 0.3);
  await expect(image).toHaveAttribute('data-zoom', '2');
  await page.getByRole('button', { name: 'Zoom in', exact: true }).click();
  await expect(image).toHaveAttribute('data-zoom', '2.25');
  await reset.click();
  expect(await picture(page)).toMatchObject({ x: 0, y: 0, zoom: 1 });
  await page.getByRole('button', { name: 'Inspect source image' }).click();
  await expect(image).toHaveAttribute('src', /original.svg/);
  expect(await picture(page)).toMatchObject({ x: 0, y: 0, zoom: 1 });
  expect(errors).toEqual([]);
});
