/**
 * Passkey ceremonies in the browser. The server sends WebAuthn options as JSON (binary fields in
 * base64url); these helpers turn them into what navigator.credentials expects and turn the
 * resulting credential back into JSON for the server.
 */

type Json = Record<string, unknown>;

export function passkeysSupported(): boolean {
  return typeof window !== 'undefined' && !!window.PublicKeyCredential && !!navigator.credentials?.create;
}

function fromB64url(value: string): ArrayBuffer {
  const b64 = value.replace(/-/g, '+').replace(/_/g, '/') + '==='.slice((value.length + 3) % 4);
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out.buffer;
}

function toB64url(buffer: ArrayBuffer | null | undefined): string | null {
  if (!buffer) return null;
  const bytes = new Uint8Array(buffer);
  let bin = '';
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function descriptors(list: unknown): PublicKeyCredentialDescriptor[] | undefined {
  if (!Array.isArray(list)) return undefined;
  return list.map((c: Json) => ({ ...(c as object), id: fromB64url(c.id as string) }) as PublicKeyCredentialDescriptor);
}

/** A browser cancelling or timing out the prompt reads as a plain sentence, not a DOMException. */
function explain(err: unknown): Error {
  const name = (err as DOMException)?.name;
  if (name === 'NotAllowedError') return new Error('The passkey prompt was closed or timed out.');
  if (name === 'InvalidStateError') return new Error('This device already has a passkey for this account.');
  if (name === 'SecurityError') return new Error('Passkeys need a secure address (https, or localhost).');
  return err instanceof Error ? err : new Error('The passkey could not be used.');
}

export async function createPasskey(options: Json): Promise<Json> {
  const user = options.user as Json;
  const publicKey: PublicKeyCredentialCreationOptions = {
    ...(options as object),
    challenge: fromB64url(options.challenge as string),
    user: { ...(user as object), id: fromB64url(user.id as string) } as PublicKeyCredentialUserEntity,
    excludeCredentials: descriptors(options.excludeCredentials),
  } as PublicKeyCredentialCreationOptions;
  let credential: PublicKeyCredential;
  try {
    credential = (await navigator.credentials.create({ publicKey })) as PublicKeyCredential;
  } catch (err) {
    throw explain(err);
  }
  const response = credential.response as AuthenticatorAttestationResponse;
  return {
    id: credential.id,
    rawId: toB64url(credential.rawId),
    type: credential.type,
    clientExtensionResults: credential.getClientExtensionResults?.() ?? {},
    authenticatorAttachment: credential.authenticatorAttachment ?? undefined,
    response: {
      clientDataJSON: toB64url(response.clientDataJSON),
      attestationObject: toB64url(response.attestationObject),
      transports: response.getTransports?.() ?? [],
    },
  };
}

export async function signWithPasskey(options: Json): Promise<Json> {
  const publicKey: PublicKeyCredentialRequestOptions = {
    ...(options as object),
    challenge: fromB64url(options.challenge as string),
    allowCredentials: descriptors(options.allowCredentials),
  } as PublicKeyCredentialRequestOptions;
  let credential: PublicKeyCredential;
  try {
    credential = (await navigator.credentials.get({ publicKey })) as PublicKeyCredential;
  } catch (err) {
    throw explain(err);
  }
  const response = credential.response as AuthenticatorAssertionResponse;
  return {
    id: credential.id,
    rawId: toB64url(credential.rawId),
    type: credential.type,
    clientExtensionResults: credential.getClientExtensionResults?.() ?? {},
    authenticatorAttachment: credential.authenticatorAttachment ?? undefined,
    response: {
      clientDataJSON: toB64url(response.clientDataJSON),
      authenticatorData: toB64url(response.authenticatorData),
      signature: toB64url(response.signature),
      userHandle: toB64url(response.userHandle),
    },
  };
}
