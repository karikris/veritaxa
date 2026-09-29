import { expect, test, type Page } from '@playwright/test';

async function openImage(page: Page, width = 800, height = 800): Promise<string[]> {
  const requests: string[] = [];
  await page.route('https://images.example.invalid/**', async (route) => {
    requests.push(route.request().url());
    await route.fulfill({
      contentType: 'image/svg+xml',
      body: `<svg xmlns="http://www.w3.org/2000/svg" width="${String(width)}" height="${String(height)}">
        <rect width="100%" height="100%" fill="#243025"/>
        <circle cx="20" cy="20" r="20" fill="#f00"/>
        <circle cx="${String(width - 20)}" cy="20" r="20" fill="#0f0"/>
        <circle cx="20" cy="${String(height - 20)}" r="20" fill="#00f"/>
        <circle cx="${String(width - 20)}" cy="${String(height - 20)}" r="20" fill="#ff0"/>
      </svg>`,
    });
  });
  await page.goto('/veritaxa/?repository=synthetic');
  await page.addStyleTag({
    content: '.image-stage { width: min(100%, 480px); height: 320px; }',
  });
  await expect
    .poll(() =>
      page.locator('img.review-image').evaluate((image: HTMLImageElement) => image.naturalWidth),
    )
    .toBe(width);
  return requests;
}

async function zoomTo(page: Page, zoom: number): Promise<void> {
  const reset = page.getByRole('button', { name: /Reset image zoom/ });
  if (await reset.isEnabled()) await reset.click();
  for (let value = 1; value < zoom; value += 0.25)
    await page.getByRole('button', { name: 'Zoom in' }).click();
}

async function geometry(page: Page) {
  return page.locator('img.review-image').evaluate((image: HTMLImageElement) => {
    const stage = image.parentElement;
    if (!stage) throw new Error('Missing image frame');
    const frame = stage.getBoundingClientRect();
    const box = image.getBoundingClientRect();
    const fit = Math.min(box.width / image.naturalWidth, box.height / image.naturalHeight);
    const width = image.naturalWidth * fit;
    const height = image.naturalHeight * fit;
    const transform = new DOMMatrixReadOnly(getComputedStyle(image).transform);
    return {
      x: transform.m41,
      y: transform.m42,
      zoom: transform.a,
      left: box.left + (box.width - width) / 2,
      right: box.right - (box.width - width) / 2,
      top: box.top + (box.height - height) / 2,
      bottom: box.bottom - (box.height - height) / 2,
      frame: {
        left: frame.left,
        right: frame.left + stage.clientWidth,
        top: frame.top,
        bottom: frame.top + stage.clientHeight,
      },
    };
  });
}

async function beginDrag(page: Page) {
  await page.locator('.image-stage').scrollIntoViewIfNeeded();
  const { frame } = await geometry(page);
  const start = { x: (frame.left + frame.right) / 2, y: (frame.top + frame.bottom) / 2 };
  await page.mouse.move(start.x, start.y);
  await page.mouse.down();
  return start;
}

async function drag(page: Page, dx: number, dy: number): Promise<void> {
  const start = await beginDrag(page);
  await page.mouse.move(start.x + dx, start.y + dy, { steps: 2 });
  await page.mouse.up();
}

for (const [shape, width, height] of [
  ['landscape', 1200, 600],
  ['portrait', 600, 1200],
  ['square', 800, 800],
] as const) {
  test(`${shape} images reveal every corner and stop at their edges`, async ({ page }) => {
    await openImage(page, width, height);
    await drag(page, 70, 50);
    expect(await geometry(page)).toMatchObject({ x: 0, y: 0, zoom: 1 });
    // At 400%, every fixture overflows both axes on desktop and mobile.
    for (const [dx, dy] of [
      [1, 1],
      [-1, 1],
      [-1, -1],
      [1, -1],
    ] as const) {
      await zoomTo(page, 4);
      await drag(page, dx * 10000, dy * 10000);
      const result = await geometry(page);
      expect(dx > 0 ? result.left : result.right).toBeCloseTo(
        dx > 0 ? result.frame.left : result.frame.right,
        1,
      );
      expect(dy > 0 ? result.top : result.bottom).toBeCloseTo(
        dy > 0 ? result.frame.top : result.frame.bottom,
        1,
      );
      await expect(page.locator('.image-stage')).not.toHaveClass(/dragging/);
    }
    await expect(page.locator('img.review-image')).toHaveAttribute('draggable', 'false');
    await expect(page.locator('.image-position')).toHaveText('1 / 2');
  });
}

test('panning preserves edits and image ownership, and resets on navigation and source changes', async ({
  page,
}) => {
  const requests = await openImage(page);
  const image = page.locator('img.review-image');
  const originalNode = await image.elementHandle();
  const initialRequests = requests.length;
  await zoomTo(page, 2);
  await drag(page, 40, 30);
  expect(await geometry(page)).toMatchObject({ x: 40, y: 30, zoom: 2 });
  await page.getByText('Plant', { exact: true }).click();
  await page.getByLabel('Comment').fill('Synthetic pan review');
  expect(await geometry(page)).toMatchObject({ x: 40, y: 30, zoom: 2 });
  expect(
    await originalNode.evaluate((node) => node === document.querySelector('.review-image')),
  ).toBe(true);
  expect(requests).toHaveLength(initialRequests);

  await page.getByRole('button', { name: 'Zoom in' }).click();
  expect(await geometry(page)).toMatchObject({ x: 45, y: 33.75, zoom: 2.25 });
  await page.getByRole('button', { name: /Reset image zoom/ }).click();
  expect(await geometry(page)).toMatchObject({ x: 0, y: 0, zoom: 1 });
  await zoomTo(page, 2);
  await drag(page, 40, 30);
  await page.getByRole('button', { name: 'Save this classification' }).click();
  await expect(image).toHaveAttribute('src', /review-002\.svg/);
  expect(await geometry(page)).toMatchObject({ x: 0, y: 0, zoom: 1 });
  await page.getByRole('button', { name: 'Previous image' }).click();
  await expect(image).toHaveAttribute('src', /review-001\.svg/);
  await expect(page.locator('input[value="plant"]')).toBeChecked();
  await expect(page.getByLabel('Comment')).toHaveValue('Synthetic pan review');

  await zoomTo(page, 2);
  await drag(page, 40, 30);
  await page.getByRole('button', { name: 'Inspect source image' }).click();
  await expect(image).toHaveAttribute('src', /review-001-original\.svg/);
  expect(await geometry(page)).toMatchObject({ x: 0, y: 0, zoom: 1 });
  await zoomTo(page, 2);
  await drag(page, 40, 30);
  await page.getByRole('button', { name: 'Return to preview' }).click();
  await expect(image).toHaveAttribute('src', /review-001\.svg/);
  expect(await geometry(page)).toMatchObject({ x: 0, y: 0, zoom: 1 });
  await originalNode.dispose();
});

test('resizing keeps the actual picture within its new pan limits', async ({ page }) => {
  await openImage(page, 1200, 600);
  await zoomTo(page, 2);
  await drag(page, 10000, 10000);
  await page.locator('.image-stage').evaluate((stage) => {
    stage.style.width = '240px';
    stage.style.height = '400px';
  });
  await expect.poll(async () => (await geometry(page)).x).toBeCloseTo(120, 1);
  expect((await geometry(page)).y).toBe(0);
  await drag(page, -10000, -10000);
  expect(await geometry(page)).toMatchObject({ x: -120, y: 0 });
});

test('capture, cancellation and image replacement cannot leave a stuck drag', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await openImage(page);
  await zoomTo(page, 2);
  const stage = page.locator('.image-stage');
  for (const ending of ['pointercancel', 'lostpointercapture'] as const) {
    const start = await beginDrag(page);
    await page.mouse.move(start.x + 25, start.y + 20);
    await expect(stage).toHaveClass(/dragging/);
    if (ending === 'pointercancel') await stage.dispatchEvent(ending, { pointerId: 1 });
    else await stage.evaluate((node) => node.releasePointerCapture(1));
    await page.mouse.move(start.x + 40, start.y + 30);
    await expect(stage).not.toHaveClass(/dragging/);
    expect(await geometry(page)).toMatchObject({ x: 25, y: 20 });
    await page.mouse.up();
    await zoomTo(page, 2);
  }
  const start = await beginDrag(page);
  await page.mouse.move(start.x + 30, start.y + 20);
  await page.keyboard.press('ArrowRight');
  await expect(page.locator('.image-position')).toHaveText('2 / 2');
  await page.mouse.move(start.x + 60, start.y + 40);
  await page.mouse.up();
  await expect(stage).not.toHaveClass(/dragging/);
  expect(await geometry(page)).toMatchObject({ x: 0, y: 0, zoom: 1 });
  expect(errors).toEqual([]);
});

test('one-finger touch pans when zoomed and scrolls the page at 100%', async ({
  page,
  isMobile,
}) => {
  test.skip(!isMobile, 'Uses the mobile touch device');
  await openImage(page);
  await zoomTo(page, 2);
  const client = await page.context().newCDPSession(page);
  const image = page.locator('img.review-image');
  const stage = page.locator('.image-stage');
  await stage.scrollIntoViewIfNeeded();
  const { frame } = await geometry(page);
  const point = { x: (frame.left + frame.right) / 2, y: (frame.top + frame.bottom) / 2, id: 1 };
  const scrollBefore = await page.evaluate(() => window.scrollY);
  await expect(image).toHaveCSS('touch-action', 'pinch-zoom');
  await client.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [point] });
  await client.send('Input.dispatchTouchEvent', {
    type: 'touchMove',
    touchPoints: [{ ...point, x: point.x + 60, y: point.y + 40 }],
  });
  await client.send('Input.dispatchTouchEvent', { type: 'touchCancel', touchPoints: [] });
  expect(await geometry(page)).toMatchObject({ x: 60, y: 40 });
  await expect(stage).not.toHaveClass(/dragging/);
  expect(await page.evaluate(() => window.scrollY)).toBe(scrollBefore);

  await page.getByRole('button', { name: /Reset image zoom/ }).click();
  await stage.scrollIntoViewIfNeeded();
  await expect(image).toHaveCSS('touch-action', 'manipulation');
  const next = (await geometry(page)).frame;
  const start = { x: (next.left + next.right) / 2, y: (next.top + next.bottom) / 2, id: 1 };
  const scrollAtReset = await page.evaluate(() => window.scrollY);
  await client.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [start] });
  for (const dy of [30, 60, 90, 120]) {
    await client.send('Input.dispatchTouchEvent', {
      type: 'touchMove',
      touchPoints: [{ ...start, y: start.y - dy }],
    });
  }
  await client.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(scrollAtReset);
  expect(await geometry(page)).toMatchObject({ x: 0, y: 0, zoom: 1 });
  await client.detach();
});
