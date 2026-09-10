import '../../../src/styles.css';
import { VeriTaxaApp } from '../../../src/app';
import { SyntheticReviewRepository } from '../../../src/data/mockReviewRepository';

// Navigation-only fixture: generate one item on demand, not an in-browser queue
// of 1,000 records that would contaminate retained-state measurements.
const root = document.querySelector<HTMLElement>('#app');
if (!root) throw new Error('Missing test root');
const repository = new SyntheticReviewRepository();
// The benchmark supplies a disposable loopback HTTPS image server so real HTTP
// and decoded-image caches stay enabled (request interception disables caching).
const imagePort = new URLSearchParams(location.search).get('image-port');
if (
  imagePort !== null &&
  (!/^\d+$/.test(imagePort) || Number(imagePort) < 1 || Number(imagePort) > 65535)
)
  throw new Error('Invalid synthetic image port');
const imageOrigin = imagePort ? `https://127.0.0.1:${imagePort}` : 'https://images.example.invalid';
repository.listBatches = () =>
  Promise.resolve([
    {
      id: '30000000-0000-0000-0000-000000000001',
      name: 'Synthetic long session',
      code: 'SYNTH-LONG',
      reviewedCount: 0,
      totalCount: 1000,
      complete: false,
    },
  ]);
repository.getCursor = (_batchId, anchor, direction) => {
  const position =
    direction === 'resume'
      ? 1
      : (((anchor ?? 1) - 1 + (direction === 'next' ? 1 : -1) + 1000) % 1000) + 1;
  return Promise.resolve({
    id: `40000000-0000-0000-0000-${String(position).padStart(12, '0')}`,
    imageId: `synthetic-${String(position)}`,
    targetScientificName: null,
    displayUrl: `${imageOrigin}/display-${String(position)}.png`,
    fallbackImageUrl: `${imageOrigin}/original-${String(position)}.png`,
    position,
    currentLabel: null,
    currentComment: null,
    currentVersion: 0,
    reviewedCount: 0,
    totalCount: 1000,
    complete: false,
  });
};
repository.saveReview = () =>
  Promise.reject(new Error('This synthetic navigation fixture does not persist reviews.'));
void new VeriTaxaApp(root, repository).start();
