export type PublicConfig = {
  supabaseUrl: string;
  supabasePublishableKey: string;
};

export type ConfigResult = { ok: true; value: PublicConfig } | { ok: false; message: string };

export type PublicEnvironment = {
  readonly VITE_SUPABASE_URL?: string;
  readonly VITE_SUPABASE_PUBLISHABLE_KEY?: string;
};

const HTTPS_PROTOCOL = 'https:';

export function readPublicConfig(
  env: PublicEnvironment = import.meta.env as unknown as PublicEnvironment,
): ConfigResult {
  const supabaseUrl = env.VITE_SUPABASE_URL?.trim();
  const supabasePublishableKey = env.VITE_SUPABASE_PUBLISHABLE_KEY?.trim();

  if (!supabaseUrl || !supabasePublishableKey) {
    return {
      ok: false,
      message: 'VeriTaxa is not configured. Contact the application administrator.',
    };
  }

  try {
    const parsedUrl = new URL(supabaseUrl);
    if (
      parsedUrl.protocol !== HTTPS_PROTOCOL ||
      parsedUrl.username ||
      parsedUrl.password ||
      parsedUrl.pathname !== '/'
    ) {
      throw new Error('Invalid Supabase URL');
    }
  } catch {
    return {
      ok: false,
      message: 'VeriTaxa has invalid public configuration.',
    };
  }

  return {
    ok: true,
    value: { supabaseUrl, supabasePublishableKey },
  };
}
