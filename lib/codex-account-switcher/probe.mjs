import crypto from 'node:crypto';
import { spawn } from 'node:child_process';
import net from 'node:net';
import { setTimeout as delay } from 'node:timers/promises';

import { buildProbeLoginParams } from './auth.mjs';

const WS_MAGIC = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11';

async function allocatePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      server.close((closeError) => {
        if (closeError) {
          reject(closeError);
          return;
        }

        resolve(address.port);
      });
    });
  });
}

async function waitForHealth(port, timeoutMs = 8_000) {
  const deadline = Date.now() + timeoutMs;
  let lastError = null;

  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/healthz`);
      if (response.ok) {
        return;
      }

      lastError = new Error(`HTTP ${response.status}`);
    } catch (error) {
      lastError = error;
    }

    await delay(150);
  }

  throw new Error(`Codex app-server did not become healthy: ${lastError?.message ?? 'unknown error'}`);
}

function encodeMaskedFrame(opcode, payloadBuffer) {
  const payload = Buffer.from(payloadBuffer);
  let header;

  if (payload.length < 126) {
    header = Buffer.from([0x80 | opcode, 0x80 | payload.length]);
  } else if (payload.length < 65_536) {
    header = Buffer.alloc(4);
    header[0] = 0x80 | opcode;
    header[1] = 0x80 | 126;
    header.writeUInt16BE(payload.length, 2);
  } else {
    throw new Error('WebSocket payload is too large');
  }

  const mask = crypto.randomBytes(4);
  const masked = Buffer.alloc(payload.length);
  for (let index = 0; index < payload.length; index += 1) {
    masked[index] = payload[index] ^ mask[index % 4];
  }

  return Buffer.concat([header, mask, masked]);
}

class JsonRpcWebSocketClient {
  constructor({ host, port }) {
    this.host = host;
    this.port = port;
    this.socket = null;
    this.buffer = Buffer.alloc(0);
    this.phase = 'handshake';
    this.pending = new Map();
    this.nextId = 1;
    this.handshakeResolve = null;
    this.handshakeReject = null;
    this.closed = false;
  }

  async connect() {
    const socket = net.createConnection({ host: this.host, port: this.port });
    this.socket = socket;

    socket.on('data', (chunk) => this.#onData(chunk));
    socket.on('error', (error) => {
      if (this.phase === 'handshake' && this.handshakeReject) {
        this.handshakeReject(error);
        this.handshakeReject = null;
        this.handshakeResolve = null;
      }
      this.#rejectAll(error);
    });
    socket.on('close', () => {
      this.closed = true;
      this.#rejectAll(new Error('WebSocket connection closed'));
    });

    await new Promise((resolve, reject) => {
      socket.once('connect', resolve);
      socket.once('error', reject);
    });

    const key = crypto.randomBytes(16).toString('base64');
    const accept = crypto.createHash('sha1').update(`${key}${WS_MAGIC}`).digest('base64');

    const handshakePromise = new Promise((resolve, reject) => {
      this.handshakeResolve = resolve;
      this.handshakeReject = reject;
    });

    socket.write(
      `GET / HTTP/1.1\r\n` +
        `Host: ${this.host}:${this.port}\r\n` +
        `Upgrade: websocket\r\n` +
        `Connection: Upgrade\r\n` +
        `Sec-WebSocket-Version: 13\r\n` +
        `Sec-WebSocket-Key: ${key}\r\n` +
        `\r\n`,
    );

    await handshakePromise;

    if (this.acceptKey !== accept) {
      throw new Error('Unexpected WebSocket accept key from app-server');
    }
  }

  async request(method, params, timeoutMs = 8_000) {
    if (!this.socket || this.closed) {
      throw new Error('WebSocket client is not connected');
    }

    const id = String(this.nextId++);
    const payload = JSON.stringify({
      jsonrpc: '2.0',
      id,
      method,
      params,
    });

    const responsePromise = new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`${method} timed out after ${timeoutMs}ms`));
      }, timeoutMs);

      this.pending.set(id, {
        resolve(result) {
          clearTimeout(timer);
          resolve(result);
        },
        reject(error) {
          clearTimeout(timer);
          reject(error);
        },
      });
    });

    this.socket.write(encodeMaskedFrame(0x1, payload));
    return responsePromise;
  }

  async close() {
    if (!this.socket || this.closed) {
      return;
    }

    this.socket.end(encodeMaskedFrame(0x8, Buffer.alloc(0)));
    await delay(50);
  }

  #rejectAll(error) {
    for (const pending of this.pending.values()) {
      pending.reject(error);
    }
    this.pending.clear();
  }

  #onData(chunk) {
    this.buffer = Buffer.concat([this.buffer, chunk]);

    if (this.phase === 'handshake') {
      const boundary = this.buffer.indexOf('\r\n\r\n');
      if (boundary === -1) {
        return;
      }

      const headerText = this.buffer.subarray(0, boundary).toString('utf8');
      this.buffer = this.buffer.subarray(boundary + 4);

      const [statusLine, ...headers] = headerText.split('\r\n');
      if (!statusLine.includes('101')) {
        this.handshakeReject?.(new Error(`WebSocket upgrade failed: ${statusLine}`));
        this.handshakeReject = null;
        this.handshakeResolve = null;
        return;
      }

      this.acceptKey = null;
      for (const header of headers) {
        const separator = header.indexOf(':');
        if (separator === -1) {
          continue;
        }

        const name = header.slice(0, separator).trim().toLowerCase();
        const value = header.slice(separator + 1).trim();
        if (name === 'sec-websocket-accept') {
          this.acceptKey = value;
        }
      }

      this.phase = 'frames';
      this.handshakeResolve?.();
      this.handshakeReject = null;
      this.handshakeResolve = null;
    }

    if (this.phase === 'frames') {
      this.#readFrames();
    }
  }

  #readFrames() {
    while (this.buffer.length >= 2) {
      const firstByte = this.buffer[0];
      const secondByte = this.buffer[1];
      let payloadLength = secondByte & 0x7f;
      let headerLength = 2;

      if (payloadLength === 126) {
        if (this.buffer.length < 4) {
          return;
        }
        payloadLength = this.buffer.readUInt16BE(2);
        headerLength = 4;
      } else if (payloadLength === 127) {
        throw new Error('64-bit WebSocket payloads are not supported');
      }

      if (this.buffer.length < headerLength + payloadLength) {
        return;
      }

      const opcode = firstByte & 0x0f;
      const payload = this.buffer.subarray(headerLength, headerLength + payloadLength);
      this.buffer = this.buffer.subarray(headerLength + payloadLength);

      if (opcode === 0x8) {
        this.socket?.end();
        return;
      }

      if (opcode === 0x9) {
        this.socket?.write(encodeMaskedFrame(0xA, payload));
        continue;
      }

      if (opcode !== 0x1) {
        continue;
      }

      const message = JSON.parse(payload.toString('utf8'));
      if (Object.prototype.hasOwnProperty.call(message, 'id')) {
        const pending = this.pending.get(String(message.id));
        if (!pending) {
          continue;
        }

        this.pending.delete(String(message.id));
        if (message.error) {
          pending.reject(new Error(message.error.message ?? JSON.stringify(message.error)));
        } else {
          pending.resolve(message.result);
        }
      }
    }
  }
}

async function stopChild(child) {
  if (!child || child.exitCode !== null) {
    return;
  }

  child.kill('SIGTERM');
  await Promise.race([
    new Promise((resolve) => child.once('exit', resolve)),
    delay(1_000),
  ]);

  if (child.exitCode === null) {
    child.kill('SIGKILL');
  }
}

function selectCodexRateLimits(result) {
  return result?.rateLimitsByLimitId?.codex ?? result?.rateLimits ?? null;
}

export async function probeAuthRateLimits(auth, { codexBin = 'codex', cwd, timeoutMs = 8_000 } = {}) {
  const port = await allocatePort();
  const child = spawn(codexBin, ['app-server', '--listen', `ws://127.0.0.1:${port}`], {
    cwd,
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  let stderr = '';
  child.stderr.on('data', (chunk) => {
    stderr += chunk.toString('utf8');
  });

  const client = new JsonRpcWebSocketClient({ host: '127.0.0.1', port });

  try {
    await waitForHealth(port, timeoutMs);
    await client.connect();
    await client.request('initialize', {
      clientInfo: {
        name: 'codex-account-switcher',
        version: '0.1.0',
      },
      capabilities: {
        experimentalApi: true,
      },
    });

    await client.request('account/login/start', buildProbeLoginParams(auth), timeoutMs);
    const account = await client.request('account/read', { refreshToken: false }, timeoutMs);
    const rateLimitResult = await client.request('account/rateLimits/read', null, timeoutMs);

    return {
      success: true,
      probedAt: new Date().toISOString(),
      account: account.account ?? null,
      rateLimits: selectCodexRateLimits(rateLimitResult),
      rateLimitsByLimitId: rateLimitResult.rateLimitsByLimitId ?? null,
    };
  } catch (error) {
    return {
      success: false,
      probedAt: new Date().toISOString(),
      error: `${error.message}${stderr ? ` | ${stderr.trim()}` : ''}`,
    };
  } finally {
    await client.close().catch(() => {});
    await stopChild(child);
  }
}
