/** Let every part of a zoomed picture reach the frame center without losing it. */
export function imagePanBounds(
  imageWidth: number,
  imageHeight: number,
  frameWidth: number,
  frameHeight: number,
  zoom: number,
): { x: number; y: number } {
  if (imageWidth <= 0 || imageHeight <= 0 || frameWidth <= 0 || frameHeight <= 0 || zoom <= 1)
    return { x: 0, y: 0 };
  const fit = Math.min(frameWidth / imageWidth, frameHeight / imageHeight);
  return {
    x: (imageWidth * fit * zoom) / 2,
    y: (imageHeight * fit * zoom) / 2,
  };
}
