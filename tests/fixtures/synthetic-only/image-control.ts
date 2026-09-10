// Negative control: no application, repository, drafts or task records. This
// distinguishes browser/tooling retention from the production application's.
const port = new URLSearchParams(location.search).get('image-port');
if (!port || !/^\d+$/.test(port) || Number(port) < 1 || Number(port) > 65535)
  throw new Error('Invalid synthetic image port');
const stage = document.querySelector('.image-stage');
const counter = document.querySelector('.image-position');
const next = document.querySelector<HTMLButtonElement>('[aria-label="Next image"]');
const source = document.querySelector<HTMLButtonElement>('.image-source-button');
if (!stage || !counter || !next || !source) throw new Error('Control fixture is incomplete');
let position = 1;
let original = false;
let image: HTMLImageElement | undefined;
const render = () => {
  image?.removeAttribute('src');
  image?.remove();
  image = document.createElement('img');
  image.className = 'review-image';
  image.decoding = 'async';
  image.style.width = '800px';
  image.src = `https://127.0.0.1:${port}/${original ? 'original' : 'display'}-${String(position)}.png`;
  stage.append(image);
  counter.textContent = `${String(position)} / 1000`;
  source.textContent = original ? 'Return to preview' : 'Inspect source image';
};
next.onclick = () => {
  position = (position % 1000) + 1;
  original = false;
  render();
};
source.onclick = () => {
  original = !original;
  render();
};
render();
