import '../../../src/styles.css';
import { VeriTaxaApp } from '../../../src/app';
import { SyntheticReviewRepository } from '../../../src/data/mockReviewRepository';

// Browser-only synthetic race fixture. This entry is not part of the production build.
const root = document.querySelector<HTMLElement>('#app');
if (!root) throw new Error('Missing test root');
const repository = new SyntheticReviewRepository();
const save = repository.saveReview.bind(repository);
let changedElsewhere = false;
repository.saveReview = async (submission) => {
  if (!changedElsewhere) {
    changedElsewhere = true;
    await save({
      ...submission,
      label: 'bird',
      comment: 'Saved elsewhere',
      submissionId: crypto.randomUUID(),
    });
  }
  return save(submission);
};
void new VeriTaxaApp(root, repository).start();
