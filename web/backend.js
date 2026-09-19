(function () {
  const runtime = window.SE_MECHANISM_CONFIG || {};
  let client = null;

  function enabled() {
    return Boolean(runtime.supabaseUrl && runtime.supabasePublishableKey && window.supabase?.createClient);
  }

  function getClient() {
    if (!enabled()) return null;
    if (!client) {
      client = window.supabase.createClient(runtime.supabaseUrl, runtime.supabasePublishableKey, {
        auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
      });
    }
    return client;
  }

  function assertOk(error) {
    if (error) throw new Error(error.message || String(error));
  }

  async function session() {
    const current = getClient();
    if (!current) return null;
    const { data, error } = await current.auth.getSession();
    assertOk(error);
    return data.session;
  }

  async function signIn(email, password) {
    const { data, error } = await getClient().auth.signInWithPassword({ email, password });
    assertOk(error);
    return data;
  }

  async function signUp(email, password) {
    const emailRedirectTo = `${window.location.origin}${window.location.pathname}`;
    const { data, error } = await getClient().auth.signUp({ email, password, options: { emailRedirectTo } });
    assertOk(error);
    return data;
  }

  async function signOut() {
    const { error } = await getClient().auth.signOut();
    assertOk(error);
  }

  async function loadWorkspace() {
    const current = getClient();
    const activeSession = await session();
    if (!activeSession) throw new Error("请先登录。");
    const userId = activeSession.user.id;
    const [settingsResult, papersResult, runResult] = await Promise.all([
      current.from("user_settings").select("config,updated_at").eq("user_id", userId).maybeSingle(),
      current.from("user_papers").select("payload").eq("user_id", userId).order("last_seen_at", { ascending: false }),
      current.from("collection_runs").select("status,started_at,completed_at,stats,error_message").eq("user_id", userId).order("started_at", { ascending: false }).limit(1).maybeSingle(),
    ]);
    assertOk(settingsResult.error);
    assertOk(papersResult.error);
    assertOk(runResult.error);
    const config = settingsResult.data?.config || null;
    const papers = (papersResult.data || []).map((row) => row.payload).filter(Boolean);
    const latestRun = runResult.data || null;
    return { user: activeSession.user, config, papers, latestRun, settingsUpdatedAt: settingsResult.data?.updated_at || "" };
  }

  async function saveSettings(config) {
    const activeSession = await session();
    if (!activeSession) throw new Error("登录已失效，请重新登录。");
    const { error } = await getClient().from("user_settings").upsert({
      user_id: activeSession.user.id,
      config,
      updated_at: new Date().toISOString(),
    }, { onConflict: "user_id" });
    assertOk(error);
  }

  async function credentialStatus() {
    const { data, error } = await getClient().functions.invoke("user-credentials", { body: { action: "status" } });
    assertOk(error);
    if (data?.error) throw new Error(data.error);
    return data?.credentials || [];
  }

  async function saveCredential(provider, apiKey) {
    const { data, error } = await getClient().functions.invoke("user-credentials", {
      body: { action: "save", provider, apiKey },
    });
    assertOk(error);
    if (data?.error) throw new Error(data.error);
    return data;
  }

  async function queueCollection(clearCache = false) {
    const activeSession = await session();
    if (!activeSession) throw new Error("登录已失效，请重新登录。");
    const { error } = await getClient().from("collection_requests").insert({
      user_id: activeSession.user.id,
      clear_cache: Boolean(clearCache),
    });
    assertOk(error);
  }

  function onAuthStateChange(callback) {
    const current = getClient();
    if (!current) return { unsubscribe() {} };
    return current.auth.onAuthStateChange((event, activeSession) => callback(event, activeSession)).data.subscription;
  }

  window.SeBackend = {
    enabled,
    requireAuth: Boolean(runtime.requireAuth),
    session,
    signIn,
    signUp,
    signOut,
    loadWorkspace,
    saveSettings,
    credentialStatus,
    saveCredential,
    queueCollection,
    onAuthStateChange,
  };
})();

