/**
 * Doppelganger Protocol — Browser Crypto
 *
 * All cryptographic operations happen here using the Web Crypto API.
 * The private key is marked non-extractable — it cannot leave this tab.
 *
 * Protocol:
 *   1. Both Alice and Bob generate ECDH P-256 keypairs locally
 *   2. Public keys are exchanged through the server (server sees only public keys)
 *   3. Both sides derive the same AES-GCM 256-bit shared secret via ECDH
 *   4. All subsequent messages are encrypted with AES-GCM before leaving the browser
 */

const Crypto = (() => {

    async function generateKeyPair() {
        return crypto.subtle.generateKey(
            { name: "ECDH", namedCurve: "P-256" },
            false,              // private key: non-extractable — never leaves this tab
            ["deriveKey"]
        );
    }

    async function exportPublicKey(publicKey) {
        return crypto.subtle.exportKey("jwk", publicKey);
    }

    async function importPublicKey(jwk) {
        return crypto.subtle.importKey(
            "jwk",
            jwk,
            { name: "ECDH", namedCurve: "P-256" },
            false,
            []
        );
    }

    async function deriveSharedKey(myPrivateKey, theirPublicKey) {
        return crypto.subtle.deriveKey(
            { name: "ECDH", public: theirPublicKey },
            myPrivateKey,
            { name: "AES-GCM", length: 256 },
            false,
            ["encrypt", "decrypt"]
        );
    }

    async function encrypt(sharedKey, plaintext) {
        const iv = crypto.getRandomValues(new Uint8Array(12));
        const encrypted = await crypto.subtle.encrypt(
            { name: "AES-GCM", iv },
            sharedKey,
            new TextEncoder().encode(plaintext)
        );
        return {
            iv: _toBase64(iv),
            ciphertext: _toBase64(new Uint8Array(encrypted))
        };
    }

    async function decrypt(sharedKey, iv_b64, ciphertext_b64) {
        const iv = _fromBase64(iv_b64);
        const ciphertext = _fromBase64(ciphertext_b64);
        const decrypted = await crypto.subtle.decrypt(
            { name: "AES-GCM", iv },
            sharedKey,
            ciphertext
        );
        return new TextDecoder().decode(decrypted);
    }

    function _toBase64(uint8Array) {
        return btoa(String.fromCharCode(...uint8Array));
    }

    function _fromBase64(b64) {
        return Uint8Array.from(atob(b64), c => c.charCodeAt(0));
    }

    return { generateKeyPair, exportPublicKey, importPublicKey, deriveSharedKey, encrypt, decrypt };
})();