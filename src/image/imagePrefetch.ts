type NetworkInformationLike = {
  readonly saveData?: boolean;
};

type PrefetchImage = {
  src: string;
};

export function shouldPrefetch(connection: NetworkInformationLike | undefined): boolean {
  return connection?.saveData !== true;
}

export class ImagePrefetch {
  readonly #imageFactory: () => PrefetchImage;
  #active: PrefetchImage | null = null;

  constructor(imageFactory: () => PrefetchImage = () => new Image()) {
    this.#imageFactory = imageFactory;
  }

  start(url: string, connection: NetworkInformationLike | undefined): void {
    this.invalidate();
    if (!shouldPrefetch(connection)) return;
    const safeUrl = validatePrefetchUrl(url);
    if (!safeUrl) return;
    this.#active = this.#imageFactory();
    this.#active.src = safeUrl;
  }

  invalidate(): void {
    if (this.#active) this.#active.src = '';
    this.#active = null;
  }
}

function validatePrefetchUrl(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && !url.username && !url.password ? url.href : null;
  } catch {
    return null;
  }
}
