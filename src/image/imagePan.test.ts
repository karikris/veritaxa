import { describe, expect, it } from 'vitest';
import { imagePanBounds } from './imagePan';

describe('contained image pan limits', () => {
  it('keeps every image centered at 100%', () => {
    expect(imagePanBounds(1200, 600, 600, 600, 1)).toEqual({ x: 0, y: 0 });
    expect(imagePanBounds(600, 1200, 600, 600, 1)).toEqual({ x: 0, y: 0 });
  });

  it('lets letterboxed picture edges reach the center on both axes', () => {
    expect(imagePanBounds(1200, 600, 600, 600, 1.5)).toEqual({ x: 450, y: 225 });
    expect(imagePanBounds(600, 1200, 600, 600, 1.5)).toEqual({ x: 225, y: 450 });
    expect(imagePanBounds(600, 600, 600, 600, 1.5)).toEqual({ x: 450, y: 450 });
  });

  it('keeps a picture edge visible at maximum pan and zoom', () => {
    expect(imagePanBounds(1200, 600, 600, 600, 4)).toEqual({ x: 1200, y: 600 });
    expect(imagePanBounds(600, 1200, 600, 600, 4)).toEqual({ x: 600, y: 1200 });
  });

  it('recalculates the fit for a resized frame', () => {
    expect(imagePanBounds(1200, 600, 600, 600, 2)).toEqual({ x: 600, y: 300 });
    expect(imagePanBounds(1200, 600, 1200, 300, 2)).toEqual({ x: 600, y: 300 });
  });

  it('does not allow panning before image load or while the frame has no size', () => {
    expect(imagePanBounds(0, 0, 600, 600, 4)).toEqual({ x: 0, y: 0 });
    expect(imagePanBounds(1200, 600, 0, 0, 4)).toEqual({ x: 0, y: 0 });
  });
});
