import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const allowedOrigins = (Deno.env.get("ALLOWED_ORIGIN") || "")
  .split(",")
  .map((value) => value.trim().replace(/\/$/, ""))
  .filter(Boolean);

function json(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...headers, "Content-Type": "application/json" },
  });
}

function bytesToBase64(bytes: Uint8Array) {
  let binary = "";
  for (const value of bytes) binary += String.fromCharCode(value);
  return btoa(binary);
}

function base64ToBytes(value: string) {
  const binary = atob(value);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

async function encryptionKey() {
  const encoded = Deno.env.get("USER_SECRET_MASTER_KEY") || "";
  const raw = base64ToBytes(encoded);
  if (raw.byteLength !== 32) throw new Error("USER_SECRET_MASTER_KEY must be a base64-encoded 32-byte key");
  return crypto.subtle.importKey("raw", raw, { name: "AES-GCM" }, false, ["encrypt"]);
}

Deno.serve(async (request) => {
  const requestOrigin = (request.headers.get("Origin") || "").replace(/\/$/, "");
  if (!allowedOrigins.length) return json({ error: "ALLOWED_ORIGIN is not configured" }, 500);
  if (requestOrigin && !allowedOrigins.includes(requestOrigin)) return json({ error: "Origin not allowed" }, 403);
  const corsHeaders = {
    "Access-Control-Allow-Origin": requestOrigin || allowedOrigins[0],
    "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Vary": "Origin",
  };
  const respond = (body: unknown, status = 200) => json(body, status, corsHeaders);
  if (request.method === "OPTIONS") return new Response("ok", { headers: corsHeaders });
  if (request.method !== "POST") return respond({ error: "Method not allowed" }, 405);

  try {
    const authorization = request.headers.get("Authorization") || "";
    if (!authorization.startsWith("Bearer ")) return respond({ error: "Authentication required" }, 401);

    const url = Deno.env.get("SUPABASE_URL") || "";
    const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
    const admin = createClient(url, serviceKey, { auth: { persistSession: false } });
    const token = authorization.slice("Bearer ".length);
    const { data: userData, error: userError } = await admin.auth.getUser(token);
    if (userError || !userData.user) return respond({ error: "Invalid session" }, 401);

    const payload = await request.json().catch(() => ({}));
    const action = String(payload.action || "status");
    const provider = String(payload.provider || "").toLowerCase();
    const allowed = new Set(["zhipu", "gemini", "openai", "deepseek", "custom", "serpapi"]);

    if (action === "status") {
      const { data, error } = await admin
        .from("user_api_credentials")
        .select("provider,key_last4,updated_at")
        .eq("user_id", userData.user.id);
      if (error) throw error;
      return respond({ credentials: data || [] });
    }

    if (!allowed.has(provider)) return respond({ error: "Unsupported provider" }, 400);

    if (action === "delete") {
      const { error } = await admin
        .from("user_api_credentials")
        .delete()
        .eq("user_id", userData.user.id)
        .eq("provider", provider);
      if (error) throw error;
      return respond({ configured: false, provider });
    }

    if (action !== "save") return respond({ error: "Unsupported action" }, 400);
    const apiKey = String(payload.apiKey || "").trim();
    if (apiKey.length < 8 || apiKey.length > 4096) return respond({ error: "API Key 长度不正确" }, 400);

    const iv = crypto.getRandomValues(new Uint8Array(12));
    const key = await encryptionKey();
    const encrypted = await crypto.subtle.encrypt(
      { name: "AES-GCM", iv },
      key,
      new TextEncoder().encode(apiKey),
    );
    const now = new Date().toISOString();
    const { error } = await admin.from("user_api_credentials").upsert({
      user_id: userData.user.id,
      provider,
      ciphertext: bytesToBase64(new Uint8Array(encrypted)),
      iv: bytesToBase64(iv),
      key_last4: apiKey.slice(-4),
      updated_at: now,
    }, { onConflict: "user_id,provider" });
    if (error) throw error;
    return respond({ configured: true, provider, key_last4: apiKey.slice(-4), updated_at: now });
  } catch (error) {
    return respond({ error: error instanceof Error ? error.message : "Unexpected error" }, 500);
  }
});
