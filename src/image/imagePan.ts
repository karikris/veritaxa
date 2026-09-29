/** Maximum translation in CSS pixels for a centered, object-fit: contain image. */
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
    x: Math.max(0, (imageWidth * fit * zoom - frameWidth) / 2),
    y: Math.max(0, (imageHeight * fit * zoom - frameHeight) / 2),
  };
}
