import { spawn } from 'node:child_process';
import { EventEmitter } from 'node:events';
import { mkdtempSync } from 'node:fs';
import { rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { chromium, devices } from '@playwright/test';

export function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

// Only Runtime/Page/Performance/Tracing are enabled. Network recording retains
// response bodies in the renderer and would contaminate the memory under test.
export class CdpSession extends EventEmitter {
  constructor(
    readonly request: (
      method: string,
      params?: Record<string, unknown>,
    ) => Promise<Record<string, unknown>>,
  ) {
    super();
  }
  send(method: string, params?: Record<string, unknown>) {
    return this.request(method, params);
  }
  async evaluate<T, R>(fn: (argument: T) => R, argument: T): Promise<Awaited<R>> {
    const response = await this.send('Runtime.evaluate', {
      expression: `(${fn.toString()})(${JSON.stringify(argument)})`,
      awaitPromise: true,
      returnByValue: true,
      timeout: 30_000,
      userGesture: true,
    });
    if (response.exceptionDetails)
      throw new Error(
        'Synthetic browser evaluation failed: ' + JSON.stringify(response.exceptionDetails),
      );
    return record(response.result).value as Awaited<R>;
  }
}

async function connect(endpoint: string) {
  const socket = new WebSocket(endpoint);
  await new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => {
      socket.close();
      reject(new Error('Browser connection timed out'));
    }, 30_000);
    socket.addEventListener(
      'open',
      () => {
        clearTimeout(timer);
        resolve();
      },
      { once: true },
    );
    socket.addEventListener(
      'error',
      () => {
        clearTimeout(timer);
        reject(new Error('Browser connection failed'));
      },
      { once: true },
    );
  });
  let sequence = 0;
  const pending = new Map<
    number,
    {
      resolve: (value: Record<string, unknown>) => void;
      reject: (error: Error) => void;
      timer: ReturnType<typeof setTimeout>;
    }
  >();
  const sessions = new Map<string, CdpSession>();
  socket.addEventListener('message', (message) => {
    if (typeof message.data !== 'string') return;
    const decoded: unknown = JSON.parse(message.data);
    const response = record(decoded);
    if (typeof response.id === 'number') {
      const request = pending.get(response.id);
      if (!request) return;
      pending.delete(response.id);
      clearTimeout(request.timer);
      if (response.error) request.reject(new Error(JSON.stringify(response.error)));
      else request.resolve(record(response.result));
    } else if (typeof response.method === 'string') {
      sessions
        .get(typeof response.sessionId === 'string' ? response.sessionId : '')
        ?.emit(response.method, record(response.params));
    }
  });
  socket.addEventListener('close', () => {
    for (const request of pending.values()) {
      clearTimeout(request.timer);
      request.reject(new Error('Browser connection closed'));
    }
    pending.clear();
  });
  return {
    session: (sessionId = '') => {
      const session = new CdpSession(
        (method, params) =>
          new Promise((resolve, reject) => {
            const id = ++sequence;
            const timer = setTimeout(() => {
              pending.delete(id);
              reject(new Error(`${method} timed out`));
            }, 30_000);
            pending.set(id, { resolve, reject, timer });
            socket.send(
              JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }),
            );
          }),
      );
      sessions.set(sessionId, session);
      return session;
    },
    close: () => socket.close(),
  };
}

export async function startBrowser(mobile: boolean) {
  const directory = mkdtempSync(
    join(process.env.VERITAXA_BROWSER_TMP ?? tmpdir(), 'veritaxa-browser-profile-'),
  );
  const child = spawn(
    chromium.executablePath(),
    [
      '--headless',
      '--no-sandbox',
      '--disable-dev-shm-usage',
      '--disable-background-networking',
      '--no-first-run',
      '--no-default-browser-check',
      '--remote-debugging-port=0',
      '--remote-debugging-address=127.0.0.1',
      `--user-data-dir=${directory}`,
      ...(mobile ? ['--js-flags=--max-old-space-size=64'] : []),
      'about:blank',
    ],
    { stdio: ['ignore', 'ignore', 'pipe'] },
  );
  let connection: Awaited<ReturnType<typeof connect>> | undefined;
  let browserSession: CdpSession | undefined;
  const close = async () => {
    if (child.pid && child.exitCode === null && child.signalCode === null) {
      const exited = new Promise<void>((resolve) => {
        const terminate = setTimeout(() => child.kill('SIGTERM'), 5000);
        const kill = setTimeout(() => child.kill('SIGKILL'), 10_000);
        child.once('exit', () => {
          clearTimeout(terminate);
          clearTimeout(kill);
          resolve();
        });
      });
      // Let Chromium finish its profile/storage shutdown before removing files.
      // A closed transport during Browser.close is expected, not a probe failure.
      if (browserSession) await browserSession.send('Browser.close').catch(() => undefined);
      else child.kill('SIGTERM');
      await exited;
    }
    connection?.close();
    await rm(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
  };
  try {
    const endpoint = await new Promise<string>((resolve, reject) => {
      let recent = '';
      const timer = setTimeout(
        () => reject(new Error('Browser did not start within 30 seconds')),
        30_000,
      );
      const onData = (data: Buffer) => {
        recent = (recent + data.toString()).slice(-4096);
        const url =
          /DevTools listening on (ws:\/\/127\.0\.0\.1:\d+\/devtools\/browser\/[^\s]+)/.exec(
            recent,
          )?.[1];
        if (url) {
          clearTimeout(timer);
          child.stderr.off('data', onData);
          resolve(url);
        }
      };
      child.stderr.on('data', onData);
      child.once('error', () => {
        clearTimeout(timer);
        reject(new Error('Browser could not start'));
      });
      child.once('exit', () => {
        clearTimeout(timer);
        reject(new Error('Browser exited during startup'));
      });
    });
    connection = await connect(endpoint);
    const root = connection.session();
    browserSession = root;
    await root.send('Security.setIgnoreCertificateErrors', { ignore: true });
    const { targetId } = await root.send('Target.createTarget', { url: 'about:blank' });
    const { sessionId } = await root.send('Target.attachToTarget', { targetId, flatten: true });
    if (typeof sessionId !== 'string') throw new Error('Browser did not attach a page');
    const page = connection.session(sessionId);
    const device = devices['Pixel 7'];
    await page.send('Emulation.setDeviceMetricsOverride', {
      ...(mobile ? device.viewport : { width: 1280, height: 900 }),
      deviceScaleFactor: mobile ? device.deviceScaleFactor : 1,
      mobile,
    });
    if (mobile) {
      await page.send('Emulation.setUserAgentOverride', { userAgent: device.userAgent });
      await page.send('Emulation.setTouchEmulationEnabled', { enabled: true });
    }
    await page.send('Page.enable');
    await page.send('Runtime.enable');
    return { root, page, version: (await root.send('Browser.getVersion')).product, close };
  } catch (error) {
    await close();
    throw error;
  }
}
