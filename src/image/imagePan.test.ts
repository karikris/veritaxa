import { describe, expect, it } from 'vitest';
import { imagePanBounds } from './imagePan';

describe('contained image pan limits', () => {
  it('keeps every image centered at 100%', () => {
    expect(imagePanBounds(1200, 600, 600, 600, 1)).toEqual({ x: 0, y: 0 });
    expect(imagePanBounds(600, 1200, 600, 600, 1)).toEqual({ x: 0, y: 0 });
  });

  it('accounts for letterboxing instead of moving the whole image element to its edges', () => {
    expect(imagePanBounds(1200, 600, 600, 600, 1.5)).toEqual({ x: 150, y: 0 });
    expect(imagePanBounds(600, 1200, 600, 600, 1.5)).toEqual({ x: 0, y: 150 });
    expect(imagePanBounds(600, 600, 600, 600, 1.5)).toEqual({ x: 150, y: 150 });
  });

  it('makes both axes available once the actual picture exceeds the frame', () => {
    expect(imagePanBounds(1200, 600, 600, 600, 4)).toEqual({ x: 900, y: 300 });
    expect(imagePanBounds(600, 1200, 600, 600, 4)).toEqual({ x: 300, y: 900 });
  });

  it('recalculates the fit for a resized frame', () => {
    expect(imagePanBounds(1200, 600, 600, 600, 2)).toEqual({ x: 300, y: 0 });
    expect(imagePanBounds(1200, 600, 1200, 300, 2)).toEqual({ x: 0, y: 150 });
  });

  it('does not allow panning before image load or while the frame has no size', () => {
    expect(imagePanBounds(0, 0, 600, 600, 4)).toEqual({ x: 0, y: 0 });
    expect(imagePanBounds(1200, 600, 0, 0, 4)).toEqual({ x: 0, y: 0 });
  });
});
