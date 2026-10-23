import * as Fingerprint from '@fingerprint/agent';

let identification: Promise<void> | undefined;

/** Identify once per page load without delaying or interrupting review work. */
export function identifyVisitor(): Promise<void> {
  return (identification ??= identify());
}

async function identify(): Promise<void> {
  const apiKey = import.meta.env.VITE_FINGERPRINT_PUBLIC_API_KEY as string | undefined;
  const region = (import.meta.env.VITE_FINGERPRINT_REGION as string | undefined) ?? 'us';
  if (!apiKey || (region !== 'us' && region !== 'eu' && region !== 'ap')) return;

  try {
    const agent = Fingerprint.start({ apiKey, region });
    // Do not attach review identifiers, image URLs, or source metadata.
    await agent.get();
  } catch {
    // Offline browsers, blocked scripts, and SDK initialization errors must not
    // prevent a reviewer from signing in or saving their work.
  }
}
