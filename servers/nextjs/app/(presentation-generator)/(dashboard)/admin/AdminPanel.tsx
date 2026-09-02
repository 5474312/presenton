"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  Cable,
  Copy,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  LockKeyhole,
  RefreshCw,
  Trash2,
  UserPlus,
  Users,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { notify } from "@/components/ui/sonner";
import { sanitizeAnalyticsError } from "@/utils/analytics";
import { formatFastApiDetail } from "@/utils/authErrors";
import { MixpanelEvent, trackEvent } from "@/utils/mixpanel";

type AdminUser = {
  id: string;
  username: string;
  role: "admin" | "user";
  created_at?: string | null;
};

type ApiKey = {
  token: string;
  user_id: string;
  created_at: string;
};

type McpCredential = {
  id: string;
  user_id: string;
  created_by_id: string;
  label: string;
  created_at: string;
  expires_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
};

type McpCredentialCreated = McpCredential & { token: string };

type AdminDialog =
  | { kind: "reset-password"; user: AdminUser }
  | { kind: "delete-user"; user: AdminUser }
  | { kind: "revoke-key"; key: ApiKey }
  | { kind: "revoke-mcp"; credential: McpCredential }
  | null;

type AdminPanelProps = {
  embedded?: boolean;
};

async function errorDetail(response: Response): Promise<string> {
  const payload = await response.json().catch(() => null);
  return payload?.detail === undefined
    ? `Request failed (${response.status})`
    : formatFastApiDetail(payload.detail);
}

function maskedKey(token: string) {
  return `••••••••••••••••${token.slice(-4)}`;
}

const primaryButtonClass =
  "inline-flex h-11 items-center justify-center gap-2 rounded-full bg-[#7C51F8] px-5 text-xs font-semibold text-white transition hover:bg-[#6D46E6] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#7A5AF8] focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60";

const inputClass =
  "h-11 w-full rounded-lg border border-[#E1E1E5] bg-white px-4 text-sm text-[#101323] outline-none transition placeholder:text-[#98A2B3] focus:border-[#7A5AF8] focus:ring-2 focus:ring-[#7A5AF8]/15";

export default function AdminPanel({ embedded = false }: AdminPanelProps) {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [mcpCredentials, setMcpCredentials] = useState<McpCredential[]>([]);
  const [mcpTokens, setMcpTokens] = useState<Record<string, string>>({});
  const [visibleMcpKeys, setVisibleMcpKeys] = useState<Set<string>>(() => new Set());
  const [mcpUserId, setMcpUserId] = useState("");
  const [mcpLabel, setMcpLabel] = useState("MCP client");
  const [mcpExpiryDays, setMcpExpiryDays] = useState(90);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [resetPasswordValue, setResetPasswordValue] = useState("");
  const [visibleKeys, setVisibleKeys] = useState<Set<string>>(() => new Set());
  const [busy, setBusy] = useState<string | null>(null);
  const [dialog, setDialog] = useState<AdminDialog>(null);

  const loadUsers = useCallback(async (
    trigger: "initial" | "manual" | "user_created" | "user_deleted" = "initial"
  ) => {
    setBusy("users");
    try {
      const response = await fetch("/api/v1/admin/users", {
        cache: "no-store",
        credentials: "include",
      });
      if (response.ok) {
        const loadedUsers = (await response.json()) as AdminUser[];
        setUsers(loadedUsers);
        setMcpUserId((current) =>
          current && loadedUsers.some((user) => user.id === current)
            ? current
            : loadedUsers.find((user) => user.role === "admin")?.id ?? loadedUsers[0]?.id ?? ""
        );
        trackEvent(MixpanelEvent.Auth_Admin_User_List_Loaded, {
          trigger,
          user_count: loadedUsers.length,
        });
      } else {
        const detail = await errorDetail(response);
        trackEvent(MixpanelEvent.Auth_Admin_User_List_Failed, {
          trigger,
          status_code: response.status,
          error_message: sanitizeAnalyticsError(detail),
        });
        notify.error("Could not load users", detail);
      }
    } catch (loadError) {
      trackEvent(MixpanelEvent.Auth_Admin_User_List_Failed, {
        trigger,
        status_code: null,
        error_message: sanitizeAnalyticsError(
          loadError,
          "Could not load users"
        ),
      });
      notify.error("Could not load users", "Please try again.");
    } finally {
      setBusy(null);
    }
  }, []);

  const loadKeys = useCallback(async () => {
    setBusy("keys");
    try {
      const response = await fetch("/api/v1/auth/token/list", {
        cache: "no-store",
        credentials: "include",
      });
      if (response.ok) {
        const loadedKeys = (await response.json()) as ApiKey[];
        setKeys(loadedKeys);
        trackEvent(MixpanelEvent.Auth_Admin_API_Key_List_Loaded, {
          api_key_count: loadedKeys.length,
        });
      } else {
        const detail = await errorDetail(response);
        trackEvent(MixpanelEvent.Auth_Admin_API_Key_List_Failed, {
          status_code: response.status,
          error_message: sanitizeAnalyticsError(detail),
        });
        notify.error("Could not load API keys", detail);
      }
    } catch (loadError) {
      trackEvent(MixpanelEvent.Auth_Admin_API_Key_List_Failed, {
        status_code: null,
        error_message: sanitizeAnalyticsError(
          loadError,
          "Could not load API keys"
        ),
      });
      notify.error("Could not load API keys", "Please try again.");
    } finally {
      setBusy(null);
    }
  }, []);

  const loadMcpCredentials = useCallback(async () => {
    setBusy("mcp-keys");
    try {
      const response = await fetch("/api/v1/admin/mcp-credentials", {
        cache: "no-store",
        credentials: "include",
      });
      if (response.ok) {
        const loaded = (await response.json()) as McpCredential[];
        setMcpCredentials(loaded.filter((credential) => !credential.revoked_at));
      } else {
        notify.error("Could not load MCP keys", await errorDetail(response));
      }
    } catch {
      notify.error("Could not load MCP keys", "Please try again.");
    } finally {
      setBusy(null);
    }
  }, []);

  useEffect(() => {
    trackEvent(MixpanelEvent.Auth_Admin_Viewed, {
      embedded,
    });
    void Promise.all([loadUsers(), loadKeys(), loadMcpCredentials()]);
  }, [embedded, loadKeys, loadMcpCredentials, loadUsers]);

  const addUser = async (event: FormEvent) => {
    event.preventDefault();
    const cleanedUsername = username.trim();
    setBusy("add");
    trackEvent(MixpanelEvent.Auth_Admin_User_Create_Started, {
      username_length: cleanedUsername.length,
      user_count_before: users.length,
    });
    try {
      const response = await fetch("/api/v1/admin/users", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: cleanedUsername, password }),
      });
      if (response.ok) {
        trackEvent(MixpanelEvent.Auth_Admin_User_Create_Completed, {
          username_length: cleanedUsername.length,
          user_count_after: users.length + 1,
        });
        notify.success("User created", `${cleanedUsername} can now sign in.`);
        setUsername("");
        setPassword("");
        await loadUsers("user_created");
      } else {
        const detail = await errorDetail(response);
        trackEvent(MixpanelEvent.Auth_Admin_User_Create_Failed, {
          status_code: response.status,
          error_message: sanitizeAnalyticsError(detail),
        });
        notify.error("Could not create user", detail);
      }
    } catch (createError) {
      trackEvent(MixpanelEvent.Auth_Admin_User_Create_Failed, {
        status_code: null,
        error_message: sanitizeAnalyticsError(
          createError,
          "Could not create user"
        ),
      });
      notify.error("Could not create user", "Please try again.");
    } finally {
      setBusy(null);
    }
  };

  const openResetPassword = (user: AdminUser) => {
    setResetPasswordValue("");
    setDialog({ kind: "reset-password", user });
  };

  const resetPassword = async (event: FormEvent) => {
    event.preventDefault();
    if (dialog?.kind !== "reset-password") return;

    const { user } = dialog;
    setBusy(`reset:${user.id}`);
    trackEvent(MixpanelEvent.Auth_Admin_User_Password_Reset_Started, {
      target_role: user.role,
    });
    try {
      const response = await fetch(`/api/v1/admin/users/${user.id}/password`, {
        method: "PUT",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: resetPasswordValue }),
      });
      if (response.ok) {
        trackEvent(MixpanelEvent.Auth_Admin_User_Password_Reset_Completed, {
          target_role: user.role,
          sessions_invalidated: true,
        });
        notify.success("Password reset", "Existing sessions were signed out.");
        setDialog(null);
        setResetPasswordValue("");
      } else {
        const detail = await errorDetail(response);
        trackEvent(MixpanelEvent.Auth_Admin_User_Password_Reset_Failed, {
          target_role: user.role,
          status_code: response.status,
          error_message: sanitizeAnalyticsError(detail),
        });
        notify.error("Could not reset password", detail);
      }
    } catch (resetError) {
      trackEvent(MixpanelEvent.Auth_Admin_User_Password_Reset_Failed, {
        target_role: user.role,
        status_code: null,
        error_message: sanitizeAnalyticsError(
          resetError,
          "Could not reset password"
        ),
      });
      notify.error("Could not reset password", "Please try again.");
    } finally {
      setBusy(null);
    }
  };

  const deleteUser = async () => {
    if (dialog?.kind !== "delete-user") return;

    const { user } = dialog;
    setBusy(`delete:${user.id}`);
    trackEvent(MixpanelEvent.Auth_Admin_User_Delete_Started, {
      target_role: user.role,
      user_count_before: users.length,
    });
    try {
      const response = await fetch(`/api/v1/admin/users/${user.id}`, {
        method: "DELETE",
        credentials: "include",
      });
      if (response.ok) {
        trackEvent(MixpanelEvent.Auth_Admin_User_Delete_Completed, {
          target_role: user.role,
          user_count_after: Math.max(0, users.length - 1),
        });
        notify.success("User deleted", `${user.username}'s workspace was removed.`);
        setDialog(null);
        await loadUsers("user_deleted");
      } else {
        const detail = await errorDetail(response);
        trackEvent(MixpanelEvent.Auth_Admin_User_Delete_Failed, {
          target_role: user.role,
          status_code: response.status,
          error_message: sanitizeAnalyticsError(detail),
        });
        notify.error("Could not delete user", detail);
      }
    } catch (deleteError) {
      trackEvent(MixpanelEvent.Auth_Admin_User_Delete_Failed, {
        target_role: user.role,
        status_code: null,
        error_message: sanitizeAnalyticsError(
          deleteError,
          "Could not delete user"
        ),
      });
      notify.error("Could not delete user", "Please try again.");
    } finally {
      setBusy(null);
    }
  };

  const createKey = async () => {
    setBusy("create-key");
    trackEvent(MixpanelEvent.Auth_Admin_API_Key_Create_Started, {
      api_key_count_before: keys.length,
    });
    try {
      const response = await fetch("/api/v1/auth/token/create", {
        method: "POST",
        credentials: "include",
      });
      if (response.ok) {
        const key = (await response.json()) as ApiKey;
        setKeys((current) => [key, ...current]);
        trackEvent(MixpanelEvent.Auth_Admin_API_Key_Create_Completed, {
          api_key_count_after: keys.length + 1,
        });
        try {
          await navigator.clipboard.writeText(key.token);
          notify.success("API key created", "The new key was copied to your clipboard.");
        } catch {
          notify.success("API key created", "Use the copy button to copy the new key.");
        }
      } else {
        const detail = await errorDetail(response);
        trackEvent(MixpanelEvent.Auth_Admin_API_Key_Create_Failed, {
          status_code: response.status,
          error_message: sanitizeAnalyticsError(detail),
        });
        notify.error("Could not create API key", detail);
      }
    } catch (createError) {
      trackEvent(MixpanelEvent.Auth_Admin_API_Key_Create_Failed, {
        status_code: null,
        error_message: sanitizeAnalyticsError(
          createError,
          "Could not create API key"
        ),
      });
      notify.error("Could not create API key", "Please try again.");
    } finally {
      setBusy(null);
    }
  };

  const revokeKey = async () => {
    if (dialog?.kind !== "revoke-key") return;

    const { key } = dialog;
    setBusy(`revoke:${key.token}`);
    trackEvent(MixpanelEvent.Auth_Admin_API_Key_Revoke_Started, {
      api_key_count_before: keys.length,
    });
    try {
      const response = await fetch("/api/v1/auth/token/revoke", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: key.token }),
      });
      if (response.ok) {
        setKeys((current) => current.filter((item) => item.token !== key.token));
        setVisibleKeys((current) => {
          const next = new Set(current);
          next.delete(key.token);
          return next;
        });
        trackEvent(MixpanelEvent.Auth_Admin_API_Key_Revoke_Completed, {
          api_key_count_after: Math.max(0, keys.length - 1),
        });
        setDialog(null);
        notify.success("API key revoked");
      } else {
        const detail = await errorDetail(response);
        trackEvent(MixpanelEvent.Auth_Admin_API_Key_Revoke_Failed, {
          status_code: response.status,
          error_message: sanitizeAnalyticsError(detail),
        });
        notify.error("Could not revoke API key", detail);
      }
    } catch (revokeError) {
      trackEvent(MixpanelEvent.Auth_Admin_API_Key_Revoke_Failed, {
        status_code: null,
        error_message: sanitizeAnalyticsError(
          revokeError,
          "Could not revoke API key"
        ),
      });
      notify.error("Could not revoke API key", "Please try again.");
    } finally {
      setBusy(null);
    }
  };

  const createMcpCredential = async (event: FormEvent) => {
    event.preventDefault();
    setBusy("create-mcp-key");
    try {
      const response = await fetch("/api/v1/admin/mcp-credentials", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: mcpUserId,
          label: mcpLabel.trim(),
          expiry_days: mcpExpiryDays,
        }),
      });
      if (!response.ok) {
        notify.error("Could not create MCP key", await errorDetail(response));
        return;
      }
      const created = (await response.json()) as McpCredentialCreated;
      const { token, ...credential } = created;
      setMcpCredentials((current) => [credential, ...current]);
      setMcpTokens((current) => ({ ...current, [credential.id]: token }));
      setVisibleMcpKeys((current) => new Set(current).add(credential.id));
      try {
        await navigator.clipboard.writeText(token);
        notify.success("MCP key created", "The key is visible and was copied to your clipboard.");
      } catch {
        notify.success("MCP key created", "The key is visible below.");
      }
    } catch {
      notify.error("Could not create MCP key", "Please try again.");
    } finally {
      setBusy(null);
    }
  };

  const getMcpToken = async (credentialId: string) => {
    const cached = mcpTokens[credentialId];
    if (cached) return cached;
    const response = await fetch(
      `/api/v1/admin/mcp-credentials/${credentialId}/token`,
      { cache: "no-store", credentials: "include" }
    );
    if (!response.ok) throw new Error(await errorDetail(response));
    const payload = (await response.json()) as { token: string };
    setMcpTokens((current) => ({ ...current, [credentialId]: payload.token }));
    return payload.token;
  };

  const toggleMcpKeyVisibility = async (credentialId: string) => {
    if (visibleMcpKeys.has(credentialId)) {
      setVisibleMcpKeys((current) => {
        const next = new Set(current);
        next.delete(credentialId);
        return next;
      });
      return;
    }
    setBusy(`reveal-mcp:${credentialId}`);
    try {
      await getMcpToken(credentialId);
      setVisibleMcpKeys((current) => new Set(current).add(credentialId));
    } catch (revealError) {
      notify.error(
        "Could not reveal MCP key",
        revealError instanceof Error ? revealError.message : "Please try again."
      );
    } finally {
      setBusy(null);
    }
  };

  const copyMcpKey = async (credentialId: string) => {
    setBusy(`reveal-mcp:${credentialId}`);
    try {
      await navigator.clipboard.writeText(await getMcpToken(credentialId));
      notify.success("MCP key copied");
    } catch (copyError) {
      notify.error(
        "Could not copy MCP key",
        copyError instanceof Error ? copyError.message : "Please try again."
      );
    } finally {
      setBusy(null);
    }
  };

  const revokeMcpCredential = async () => {
    if (dialog?.kind !== "revoke-mcp") return;
    const { credential } = dialog;
    setBusy(`revoke-mcp:${credential.id}`);
    try {
      const response = await fetch(
        `/api/v1/admin/mcp-credentials/${credential.id}/revoke`,
        { method: "POST", credentials: "include" }
      );
      if (!response.ok) {
        notify.error("Could not revoke MCP key", await errorDetail(response));
        return;
      }
      const revoked = (await response.json()) as McpCredential;
      setMcpCredentials((current) =>
        current.filter((item) => item.id !== revoked.id)
      );
      setMcpTokens((current) => {
        const next = { ...current };
        delete next[credential.id];
        return next;
      });
      setVisibleMcpKeys((current) => {
        const next = new Set(current);
        next.delete(credential.id);
        return next;
      });
      setDialog(null);
      notify.success("MCP key revoked");
    } catch {
      notify.error("Could not revoke MCP key", "Please try again.");
    } finally {
      setBusy(null);
    }
  };

  const toggleKeyVisibility = (token: string) => {
    setVisibleKeys((current) => {
      const next = new Set(current);
      if (next.has(token)) next.delete(token);
      else next.add(token);
      return next;
    });
  };

  const copyKey = async (token: string) => {
    try {
      await navigator.clipboard.writeText(token);
      notify.success("API key copied");
    } catch {
      notify.error("Could not copy API key", "Please try again.");
    }
  };

  const dialogBusy =
    (dialog?.kind === "reset-password" && busy === `reset:${dialog.user.id}`) ||
    (dialog?.kind === "delete-user" && busy === `delete:${dialog.user.id}`) ||
    (dialog?.kind === "revoke-key" && busy === `revoke:${dialog.key.token}`) ||
    (dialog?.kind === "revoke-mcp" && busy === `revoke-mcp:${dialog.credential.id}`);
  const RootElement = embedded ? "section" : "main";

  return (
    <RootElement
      className={
        embedded
          ? "h-[calc(100vh-104px)] overflow-y-auto pb-28 pr-6 font-syne"
          : "min-h-screen bg-white px-8 py-10 font-syne"
      }
    >
      <div className={embedded ? "max-w-5xl" : "mx-auto max-w-5xl"}>
        {!embedded ? (
          <h1 className="font-syne font-medium text-[28px] tracking-[-0.84px] text-black">
            Admin
          </h1>
        ) : null}

        <div
          className={`rounded-[12px] bg-[#F9F8F8] p-7 ${
            embedded ? "" : "mt-7"
          }`}
        >
          <h2 className="text-sm font-semibold text-[#191919]">
            Manage access
          </h2>
          <p className="mt-1 max-w-2xl text-xs leading-relaxed text-[#6B7280]">
            Create login accounts and manage API keys and user-scoped MCP keys.
            User workspaces remain private.
          </p>

          <Tabs defaultValue="users" className="mt-6">
          <TabsList className="h-11 rounded-full border border-[#EDEEEF] bg-[#F9FAFB] p-1">
            <TabsTrigger
              value="users"
              className="h-9 rounded-full px-5 text-xs text-[#667085] shadow-none data-[state=active]:bg-white data-[state=active]:text-[#5146E5] data-[state=active]:shadow-sm"
            >
              Users
            </TabsTrigger>
            <TabsTrigger
              value="keys"
              className="h-9 rounded-full px-5 text-xs text-[#667085] shadow-none data-[state=active]:bg-white data-[state=active]:text-[#5146E5] data-[state=active]:shadow-sm"
            >
              API keys
            </TabsTrigger>
            <TabsTrigger
              value="mcp-keys"
              className="h-9 rounded-full px-5 text-xs text-[#667085] shadow-none data-[state=active]:bg-white data-[state=active]:text-[#5146E5] data-[state=active]:shadow-sm"
            >
              MCP keys
            </TabsTrigger>
          </TabsList>

          <TabsContent value="users" className="mt-6 space-y-5">
            <section className="rounded-[12px] border border-[#EDEEEF] bg-white p-6">
              <div className="mb-5 flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[#F4F3FF]">
                  <UserPlus className="h-4 w-4 text-[#5146E5]" />
                </div>
                <div>
                  <h2 className="text-sm font-semibold text-[#101323]">Add user</h2>
                  <p className="mt-0.5 text-xs text-[#667085]">
                    Create a private workspace and sign-in credentials.
                  </p>
                </div>
              </div>
              <form onSubmit={addUser} className="grid gap-3 sm:grid-cols-[1fr_1fr_auto]">
                <input
                  aria-label="Username"
                  className={inputClass}
                  placeholder="Username"
                  minLength={3}
                  maxLength={128}
                  pattern="\S+"
                  title="Username cannot contain spaces"
                  value={username}
                  onChange={(event) =>
                    setUsername(event.target.value.replace(/\s/g, ""))
                  }
                  required
                  spellCheck={false}
                />
                <input
                  aria-label="Password"
                  className={inputClass}
                  type="password"
                  placeholder="Password (8+ characters)"
                  minLength={8}
                  maxLength={128}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  required
                />
                <button type="submit" className={primaryButtonClass} disabled={busy === "add"}>
                  {busy === "add" && <Loader2 className="h-4 w-4 animate-spin" />}
                  Create user
                </button>
              </form>
            </section>

            <section className="overflow-hidden rounded-[12px] border border-[#EDEEEF] bg-white">
              <div className="flex items-center justify-between border-b border-[#EDEEEF] px-6 py-5">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[#F4F3FF]">
                    <Users className="h-4 w-4 text-[#5146E5]" />
                  </div>
                  <div>
                    <h2 className="text-sm font-semibold text-[#101323]">Accounts</h2>
                    <p className="mt-0.5 text-xs text-[#667085]">
                      {users.length} account{users.length === 1 ? "" : "s"}
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  aria-label="Refresh accounts"
                  className="flex h-9 w-9 items-center justify-center rounded-full border border-[#EDEEEF] text-[#667085] transition hover:bg-[#F9FAFB] hover:text-[#5146E5]"
                  onClick={() => void loadUsers("manual")}
                >
                  <RefreshCw className={`h-4 w-4 ${busy === "users" ? "animate-spin" : ""}`} />
                </button>
              </div>
              <div className="divide-y divide-[#EDEEEF]">
                {users.map((user) => (
                  <div
                    key={user.id}
                    className="flex flex-wrap items-center justify-between gap-4 px-6 py-4"
                  >
                    <div>
                      <p className="text-sm font-semibold text-[#101323]">{user.username}</p>
                      <p className="mt-1 text-xs text-[#667085]">
                        {user.role === "admin" ? "Administrator" : "User"}
                        {user.created_at
                          ? ` · ${new Date(user.created_at).toLocaleDateString()}`
                          : ""}
                      </p>
                    </div>
                    {user.role === "user" && (
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          className="h-9 rounded-full border border-[#EDEEEF] bg-white px-4 text-xs font-semibold text-[#344054] transition hover:bg-[#F9FAFB]"
                          onClick={() => openResetPassword(user)}
                          disabled={busy !== null}
                        >
                          Reset password
                        </button>
                        <button
                          type="button"
                          aria-label={`Delete ${user.username}`}
                          className="flex h-9 w-9 items-center justify-center rounded-full border border-[#FEE4E2] bg-white text-[#D92D20] transition hover:bg-[#FEF3F2]"
                          onClick={() => setDialog({ kind: "delete-user", user })}
                          disabled={busy !== null}
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </section>
          </TabsContent>

          <TabsContent value="keys" className="mt-6">
            <section className="overflow-hidden rounded-[12px] border border-[#EDEEEF] bg-white">
              <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[#EDEEEF] px-6 py-5">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[#F4F3FF]">
                    <KeyRound className="h-4 w-4 text-[#5146E5]" />
                  </div>
                  <div>
                    <h2 className="text-sm font-semibold text-[#101323]">API keys</h2>
                    <p className="mt-0.5 text-xs text-[#667085]">
                      Administrator-owned keys for direct REST API access.
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  className={primaryButtonClass}
                  onClick={() => void createKey()}
                  disabled={busy === "create-key"}
                >
                  {busy === "create-key" && <Loader2 className="h-4 w-4 animate-spin" />}
                  Generate key
                </button>
              </div>
              <div className="divide-y divide-[#EDEEEF]">
                {keys.length === 0 && (
                  <div className="px-6 py-12 text-center">
                    <KeyRound className="mx-auto h-6 w-6 text-[#B8B4C7]" />
                    <p className="mt-3 text-sm text-[#667085]">
                      No API keys have been generated.
                    </p>
                  </div>
                )}
                {keys.map((key) => {
                  const isVisible = visibleKeys.has(key.token);
                  return (
                    <div
                      key={key.token}
                      className="flex flex-wrap items-center gap-3 px-6 py-4"
                    >
                      <div className="min-w-[220px] flex-1">
                        <code className="block truncate text-xs text-[#344054]">
                          {isVisible ? key.token : maskedKey(key.token)}
                        </code>
                        <p className="mt-1 text-[11px] text-[#98A2B3]">
                          Created {new Date(key.created_at).toLocaleDateString()}
                        </p>
                      </div>
                      <button
                        type="button"
                        aria-label={isVisible ? "Hide API key" : "Show API key"}
                        title={isVisible ? "Hide API key" : "Show API key"}
                        className="flex h-9 w-9 items-center justify-center rounded-full border border-[#EDEEEF] text-[#667085] transition hover:bg-[#F4F3FF] hover:text-[#5146E5]"
                        onClick={() => toggleKeyVisibility(key.token)}
                      >
                        {isVisible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                      </button>
                      <button
                        type="button"
                        aria-label="Copy API key"
                        title="Copy API key"
                        className="flex h-9 w-9 items-center justify-center rounded-full border border-[#EDEEEF] text-[#667085] transition hover:bg-[#F4F3FF] hover:text-[#5146E5]"
                        onClick={() => void copyKey(key.token)}
                      >
                        <Copy className="h-4 w-4" />
                      </button>
                      <button
                        type="button"
                        aria-label="Revoke API key"
                        title="Revoke API key"
                        className="flex h-9 w-9 items-center justify-center rounded-full border border-[#FEE4E2] text-[#D92D20] transition hover:bg-[#FEF3F2]"
                        onClick={() => setDialog({ kind: "revoke-key", key })}
                        disabled={busy !== null}
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  );
                })}
              </div>
            </section>
          </TabsContent>

          <TabsContent value="mcp-keys" className="mt-6 space-y-5">
            <section className="rounded-[12px] border border-[#EDEEEF] bg-white p-6">
              <div className="mb-5 flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[#F4F3FF]">
                  <Cable className="h-4 w-4 text-[#5146E5]" />
                </div>
                <div>
                  <h2 className="text-sm font-semibold text-[#101323]">Generate MCP key</h2>
                  <p className="mt-0.5 text-xs text-[#667085]">
                    Scope a key to one user. Administrator keys can also create templates.
                  </p>
                </div>
              </div>
              <form
                onSubmit={createMcpCredential}
                className="grid gap-3 lg:grid-cols-[1fr_1fr_150px_auto]"
              >
                <select
                  aria-label="MCP key user"
                  className={inputClass}
                  value={mcpUserId}
                  onChange={(event) => setMcpUserId(event.target.value)}
                  required
                >
                  <option value="" disabled>Select user</option>
                  {users.map((user) => (
                    <option key={user.id} value={user.id}>
                      {user.username} ({user.role})
                    </option>
                  ))}
                </select>
                <input
                  aria-label="MCP key label"
                  className={inputClass}
                  value={mcpLabel}
                  onChange={(event) => setMcpLabel(event.target.value)}
                  minLength={1}
                  maxLength={120}
                  placeholder="Client name"
                  required
                />
                <select
                  aria-label="MCP key expiry days"
                  className={inputClass}
                  value={mcpExpiryDays}
                  onChange={(event) => setMcpExpiryDays(Number(event.target.value))}
                  required
                >
                  <option value={30}>30 days</option>
                  <option value={90}>90 days</option>
                  <option value={180}>180 days</option>
                  <option value={365}>365 days</option>
                </select>
                <button
                  type="submit"
                  className={primaryButtonClass}
                  disabled={busy === "create-mcp-key" || !mcpUserId}
                >
                  {busy === "create-mcp-key" && <Loader2 className="h-4 w-4 animate-spin" />}
                  Generate key
                </button>
              </form>
            </section>

            <section className="overflow-hidden rounded-[12px] border border-[#EDEEEF] bg-white">
              <div className="flex items-center justify-between border-b border-[#EDEEEF] px-6 py-5">
                <div>
                  <h2 className="text-sm font-semibold text-[#101323]">MCP keys</h2>
                  <p className="mt-0.5 text-xs text-[#667085]">
                    Reveal or copy a key whenever you need to configure an MCP client.
                  </p>
                </div>
                <button
                  type="button"
                  aria-label="Refresh MCP keys"
                  className="flex h-9 w-9 items-center justify-center rounded-full border border-[#EDEEEF] text-[#667085] transition hover:bg-[#F9FAFB] hover:text-[#5146E5]"
                  onClick={() => void loadMcpCredentials()}
                >
                  <RefreshCw className={`h-4 w-4 ${busy === "mcp-keys" ? "animate-spin" : ""}`} />
                </button>
              </div>
              <div className="divide-y divide-[#EDEEEF]">
                {mcpCredentials.length === 0 && (
                  <div className="px-6 py-12 text-center">
                    <Cable className="mx-auto h-6 w-6 text-[#B8B4C7]" />
                    <p className="mt-3 text-sm text-[#667085]">No MCP keys have been generated.</p>
                  </div>
                )}
                {mcpCredentials.map((credential) => {
                  const isVisible = visibleMcpKeys.has(credential.id);
                  const token = mcpTokens[credential.id];
                  const user = users.find((item) => item.id === credential.user_id);
                  const isRevoked = Boolean(credential.revoked_at);
                  return (
                    <div key={credential.id} className="flex flex-wrap items-center gap-3 px-6 py-4">
                      <div className="min-w-[260px] flex-1">
                        <div className="flex items-center gap-2">
                          <p className="text-sm font-semibold text-[#101323]">{credential.label}</p>
                          {isRevoked && (
                            <span className="rounded-full bg-[#FEF3F2] px-2 py-0.5 text-[10px] font-semibold text-[#D92D20]">
                              Revoked
                            </span>
                          )}
                        </div>
                        <code className="mt-1 block truncate text-xs text-[#344054]">
                          {isVisible && token ? token : `sk-presenton-mcp-••••••••${credential.id.slice(-4)}`}
                        </code>
                        <p className="mt-1 text-[11px] text-[#98A2B3]">
                          {user?.username ?? credential.user_id} · Expires {new Date(credential.expires_at).toLocaleDateString()}
                          {credential.last_used_at
                            ? ` · Last used ${new Date(credential.last_used_at).toLocaleDateString()}`
                            : " · Never used"}
                        </p>
                      </div>
                      <button
                        type="button"
                        aria-label={isVisible ? "Hide MCP key" : "Show MCP key"}
                        title={isVisible ? "Hide MCP key" : "Show MCP key"}
                        className="flex h-9 w-9 items-center justify-center rounded-full border border-[#EDEEEF] text-[#667085] transition hover:bg-[#F4F3FF] hover:text-[#5146E5] disabled:opacity-50"
                        onClick={() => void toggleMcpKeyVisibility(credential.id)}
                        disabled={busy === `reveal-mcp:${credential.id}`}
                      >
                        {busy === `reveal-mcp:${credential.id}` ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : isVisible ? (
                          <EyeOff className="h-4 w-4" />
                        ) : (
                          <Eye className="h-4 w-4" />
                        )}
                      </button>
                      <button
                        type="button"
                        aria-label="Copy MCP key"
                        title="Copy MCP key"
                        className="flex h-9 w-9 items-center justify-center rounded-full border border-[#EDEEEF] text-[#667085] transition hover:bg-[#F4F3FF] hover:text-[#5146E5] disabled:opacity-50"
                        onClick={() => void copyMcpKey(credential.id)}
                        disabled={busy === `reveal-mcp:${credential.id}`}
                      >
                        <Copy className="h-4 w-4" />
                      </button>
                      {!isRevoked && (
                        <button
                          type="button"
                          aria-label="Revoke MCP key"
                          title="Revoke MCP key"
                          className="flex h-9 w-9 items-center justify-center rounded-full border border-[#FEE4E2] text-[#D92D20] transition hover:bg-[#FEF3F2]"
                          onClick={() => setDialog({ kind: "revoke-mcp", credential })}
                          disabled={busy !== null}
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            </section>
          </TabsContent>
          </Tabs>
        </div>
      </div>

      <Dialog
        open={dialog !== null}
        onOpenChange={(open) => {
          if (!open && !dialogBusy) {
            setDialog(null);
            setResetPasswordValue("");
          }
        }}
      >
        <DialogContent className="w-[calc(100vw-32px)] max-w-[440px] gap-0 rounded-[24px] border-0 bg-white p-0 font-syne shadow-[0_24px_80px_rgba(15,23,42,0.18)] [&>button]:hidden">
          {dialog?.kind === "reset-password" && (
            <form onSubmit={resetPassword}>
              <DialogHeader className="px-7 pb-5 pt-7 text-left">
                <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-[#F4F3FF]">
                  <LockKeyhole className="h-5 w-5 text-[#5146E5]" />
                </div>
                <DialogTitle className="text-xl font-semibold leading-7 text-[#101323]">
                  Reset password
                </DialogTitle>
                <DialogDescription className="pt-1 text-sm leading-6 text-[#667085]">
                  Set a new password for{" "}
                  <span className="font-semibold text-[#344054]">{dialog.user.username}</span>.
                  Existing sessions will be signed out.
                </DialogDescription>
                <label className="pt-4 text-xs font-semibold text-[#344054]" htmlFor="reset-password">
                  New password
                </label>
                <input
                  id="reset-password"
                  autoFocus
                  className={inputClass}
                  type="password"
                  placeholder="Minimum 8 characters"
                  minLength={8}
                  maxLength={128}
                  value={resetPasswordValue}
                  onChange={(event) => setResetPasswordValue(event.target.value)}
                  required
                />
              </DialogHeader>
              <DialogFooter className="flex-row border-t border-[#EAECF0] p-4 sm:justify-end sm:space-x-0">
                <button
                  type="button"
                  className="h-10 rounded-full border border-[#E1E1E5] px-5 text-xs font-semibold text-[#344054] transition hover:bg-[#F9FAFB]"
                  onClick={() => setDialog(null)}
                  disabled={dialogBusy}
                >
                  Cancel
                </button>
                <button type="submit" className={primaryButtonClass} disabled={dialogBusy}>
                  {dialogBusy && <Loader2 className="h-4 w-4 animate-spin" />}
                  Reset password
                </button>
              </DialogFooter>
            </form>
          )}

          {dialog?.kind === "delete-user" && (
            <>
              <DialogHeader className="px-7 pb-6 pt-7 text-left">
                <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-[#FEF3F2]">
                  <AlertTriangle className="h-5 w-5 text-[#D92D20]" />
                </div>
                <DialogTitle className="text-xl font-semibold leading-7 text-[#101323]">
                  Delete {dialog.user.username}?
                </DialogTitle>
                <DialogDescription className="pt-1 text-sm leading-6 text-[#667085]">
                  This permanently removes the user and all of their presentations,
                  templates, chats, tasks, and files. This action cannot be undone.
                </DialogDescription>
              </DialogHeader>
              <DialogFooter className="flex-row border-t border-[#EAECF0] p-4 sm:justify-end sm:space-x-0">
                <button
                  type="button"
                  className="h-10 rounded-full border border-[#E1E1E5] px-5 text-xs font-semibold text-[#344054] transition hover:bg-[#F9FAFB]"
                  onClick={() => setDialog(null)}
                  disabled={dialogBusy}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="inline-flex h-10 items-center justify-center gap-2 rounded-full bg-[#D92D20] px-5 text-xs font-semibold text-white transition hover:bg-[#B42318] disabled:opacity-60"
                  onClick={() => void deleteUser()}
                  disabled={dialogBusy}
                >
                  {dialogBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                  Delete user
                </button>
              </DialogFooter>
            </>
          )}

          {dialog?.kind === "revoke-key" && (
            <>
              <DialogHeader className="px-7 pb-6 pt-7 text-left">
                <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-[#FEF3F2]">
                  <AlertTriangle className="h-5 w-5 text-[#D92D20]" />
                </div>
                <DialogTitle className="text-xl font-semibold leading-7 text-[#101323]">
                  Revoke API key?
                </DialogTitle>
                <DialogDescription className="pt-1 text-sm leading-6 text-[#667085]">
                  Any application using this key will lose API access
                  immediately. This action cannot be undone.
                </DialogDescription>
              </DialogHeader>
              <DialogFooter className="flex-row border-t border-[#EAECF0] p-4 sm:justify-end sm:space-x-0">
                <button
                  type="button"
                  className="h-10 rounded-full border border-[#E1E1E5] px-5 text-xs font-semibold text-[#344054] transition hover:bg-[#F9FAFB]"
                  onClick={() => setDialog(null)}
                  disabled={dialogBusy}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="inline-flex h-10 items-center justify-center gap-2 rounded-full bg-[#D92D20] px-5 text-xs font-semibold text-white transition hover:bg-[#B42318] disabled:opacity-60"
                  onClick={() => void revokeKey()}
                  disabled={dialogBusy}
                >
                  {dialogBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                  Revoke key
                </button>
              </DialogFooter>
            </>
          )}

          {dialog?.kind === "revoke-mcp" && (
            <>
              <DialogHeader className="px-7 pb-6 pt-7 text-left">
                <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-[#FEF3F2]">
                  <AlertTriangle className="h-5 w-5 text-[#D92D20]" />
                </div>
                <DialogTitle className="text-xl font-semibold leading-7 text-[#101323]">
                  Revoke MCP key?
                </DialogTitle>
                <DialogDescription className="pt-1 text-sm leading-6 text-[#667085]">
                  Clients using “{dialog.credential.label}” will lose MCP access
                  immediately. Only revoke it if the key is no longer needed or may be compromised.
                </DialogDescription>
              </DialogHeader>
              <DialogFooter className="flex-row border-t border-[#EAECF0] p-4 sm:justify-end sm:space-x-0">
                <button
                  type="button"
                  className="h-10 rounded-full border border-[#E1E1E5] px-5 text-xs font-semibold text-[#344054] transition hover:bg-[#F9FAFB]"
                  onClick={() => setDialog(null)}
                  disabled={dialogBusy}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="inline-flex h-10 items-center justify-center gap-2 rounded-full bg-[#D92D20] px-5 text-xs font-semibold text-white transition hover:bg-[#B42318] disabled:opacity-60"
                  onClick={() => void revokeMcpCredential()}
                  disabled={dialogBusy}
                >
                  {dialogBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                  Revoke key
                </button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </RootElement>
  );
}
