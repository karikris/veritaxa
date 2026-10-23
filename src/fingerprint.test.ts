import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { start, get } = vi.hoisted(() => ({ start: vi.fn(), get: vi.fn() }));
vi.mock('@fingerprint/agent', () => ({ start }));

beforeEach(() => {
  vi.resetModules();
  vi.resetAllMocks();
  vi.stubEnv('VITE_FINGERPRINT_PUBLIC_API_KEY', 'synthetic-public-key');
  vi.stubEnv('VITE_FINGERPRINT_REGION', 'ap');
  get.mockResolvedValue({ visitor_id: 'synthetic', event_id: 'synthetic' });
  start.mockReturnValue({ get });
});
afterEach(() => vi.unstubAllEnvs());

describe('optional visitor identification', () => {
  it('skips the SDK when no public key is configured', async () => {
    vi.stubEnv('VITE_FINGERPRINT_PUBLIC_API_KEY', '');
    const { identifyVisitor } = await import('./fingerprint');
    await identifyVisitor();
    expect(start).not.toHaveBeenCalled();
  });

  it('identifies once in the configured region without review data', async () => {
    const { identifyVisitor } = await import('./fingerprint');
    await Promise.all([identifyVisitor(), identifyVisitor()]);
    expect(start).toHaveBeenCalledExactlyOnceWith({
      apiKey: 'synthetic-public-key',
      region: 'ap',
    });
    expect(get).toHaveBeenCalledExactlyOnceWith();
  });

  it.each(['start', 'get'])('contains %s failures', async (step) => {
    if (step === 'start')
      start.mockImplementation(() => {
        throw new Error('blocked');
      });
    else get.mockRejectedValue(new Error('offline'));
    const { identifyVisitor } = await import('./fingerprint');
    await expect(identifyVisitor()).resolves.toBeUndefined();
  });

  it('skips an invalid region rather than sending to a different region', async () => {
    vi.stubEnv('VITE_FINGERPRINT_REGION', 'invalid');
    const { identifyVisitor } = await import('./fingerprint');
    await identifyVisitor();
    expect(start).not.toHaveBeenCalled();
  });
});
