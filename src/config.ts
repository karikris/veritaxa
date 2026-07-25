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

  if (
    supabasePublishableKey.length > 4096 ||
    isServerSecretKey(supabasePublishableKey) ||
    jwtRole(supabasePublishableKey) === 'service_role'
  ) {
    return {
      ok: false,
      message: 'VeriTaxa has invalid public configuration.',
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

function isServerSecretKey(value: string): boolean {
  const segments = value.split('_', 3);
  return segments[0] === 'sb' && segments[1] === 'secret' && segments[2] !== undefined;
}

function jwtRole(value: string): string | null {
  const payload = value.split('.')[1];
  if (!payload) return null;
  try {
    const base64 = payload.replaceAll('-', '+').replaceAll('_', '/');
    const decoded = JSON.parse(atob(base64)) as unknown;
    if (typeof decoded !== 'object' || decoded === null || !('role' in decoded)) return null;
    return typeof decoded.role === 'string' ? decoded.role : null;
  } catch {
    return null;
  }
}
