/**
 * The proof-of-work check that guards sign-up, the demo and recovery codes (see core/abuse.py):
 * find the number n, at most maxnumber, for which SHA-256(salt + n) is the server's challenge.
 * About a second of work in a browser; nothing is sent to any third party.
 */
export interface PowChallenge {
  algorithm: string;
  salt: string;
  challenge: string;
  maxnumber: number;
  signature: string;
}

export type PowSolution = PowChallenge & { number: number };

const encoder = new TextEncoder();

function hex(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let out = '';
  for (let i = 0; i < bytes.length; i++) out += bytes[i].toString(16).padStart(2, '0');
  return out;
}

export async function solvePow(c: PowChallenge): Promise<PowSolution> {
  const BATCH = 256;
  for (let start = 0; start <= c.maxnumber; start += BATCH) {
    const tries = [];
    for (let n = start; n < Math.min(start + BATCH, c.maxnumber + 1); n++) {
      tries.push(crypto.subtle.digest('SHA-256', encoder.encode(c.salt + n)).then((d) => (hex(d) === c.challenge ? n : -1)));
    }
    const found = (await Promise.all(tries)).find((n) => n >= 0);
    if (found !== undefined) return { ...c, number: found };
  }
  throw new Error('The browser check failed. Reload the page and try again.');
}
