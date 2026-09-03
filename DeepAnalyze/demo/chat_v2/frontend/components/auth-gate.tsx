"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { API_URLS } from "@/lib/config";

export const UNAUTHORIZED_EVENT = "da:unauthorized";

export function getUsername(): string {
  if (typeof window === "undefined") return "";
  return localStorage.getItem("da_username") || "";
}

type Status = "loading" | "anonymous" | "authenticated";

export function AuthGate({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");

  const checkAuth = useCallback(async () => {
    try {
      const res = await fetch(API_URLS.AUTH_ME, { cache: "no-store" });
      if (res.ok) {
        const data = await res.json();
        try {
          localStorage.setItem("da_username", data.username || "");
        } catch {}
        setStatus("authenticated");
      } else {
        try {
          localStorage.removeItem("da_username");
        } catch {}
        setStatus("anonymous");
      }
    } catch {
      setStatus("anonymous");
    }
  }, []);

  useEffect(() => {
    void checkAuth();
    const onUnauthorized = () => {
      try {
        localStorage.removeItem("da_username");
      } catch {}
      setStatus("anonymous");
    };
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, [checkAuth]);

  if (status === "loading") {
    return (
      <div className="h-screen flex items-center justify-center bg-white dark:bg-black">
        <div className="text-sm text-gray-500 dark:text-gray-400">加载中...</div>
      </div>
    );
  }

  if (status === "authenticated") {
    return <>{children}</>;
  }

  return (
    <div className="h-screen flex items-center justify-center bg-gray-50 dark:bg-black px-4">
      <LoginCard onSuccess={checkAuth} />
    </div>
  );
}

function LoginCard({ onSuccess }: { onSuccess: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const submit = async (endpoint: string) => {
    if (!username.trim() || !password) {
      setError("请输入用户名和密码");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username.trim(), password }),
      });
      if (res.ok) {
        onSuccess();
        return;
      }
      const data = await res.json().catch(() => ({}));
      setError(data.detail || `请求失败 (${res.status})`);
    } catch {
      setError("无法连接服务器，请确认后端已启动");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Card className="w-full max-w-sm">
      <CardHeader className="text-center">
        <CardTitle className="text-xl">DA-Studio</CardTitle>
        <CardDescription>登录后开始你的数据分析</CardDescription>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="login">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="login">登录</TabsTrigger>
            <TabsTrigger value="register">注册</TabsTrigger>
          </TabsList>
          <TabsContent value="login" className="space-y-4 pt-4">
            <AuthForm
              username={username}
              password={password}
              error={error}
              submitting={submitting}
              onUsername={setUsername}
              onPassword={setPassword}
              buttonLabel="登录"
              onSubmit={() => submit(API_URLS.AUTH_LOGIN)}
            />
          </TabsContent>
          <TabsContent value="register" className="space-y-4 pt-4">
            <AuthForm
              username={username}
              password={password}
              error={error}
              submitting={submitting}
              onUsername={setUsername}
              onPassword={setPassword}
              buttonLabel="注册并登录"
              onSubmit={() => submit(API_URLS.AUTH_REGISTER)}
            />
            <p className="text-xs text-gray-500 dark:text-gray-400 text-center">
              用户名：小写字母/数字/下划线/连字符，3-32 位；密码至少 4 位
            </p>
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}

function AuthForm({
  username,
  password,
  error,
  submitting,
  onUsername,
  onPassword,
  buttonLabel,
  onSubmit,
}: {
  username: string;
  password: string;
  error: string;
  submitting: boolean;
  onUsername: (value: string) => void;
  onPassword: (value: string) => void;
  buttonLabel: string;
  onSubmit: () => void;
}) {
  return (
    <form
      className="space-y-4"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <div className="space-y-2">
        <Label htmlFor="auth-username">用户名</Label>
        <Input
          id="auth-username"
          autoComplete="username"
          value={username}
          onChange={(event) => onUsername(event.target.value)}
          placeholder="username"
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="auth-password">密码</Label>
        <Input
          id="auth-password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => onPassword(event.target.value)}
          placeholder="••••••"
        />
      </div>
      {error && (
        <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
      )}
      <Button type="submit" className="w-full" disabled={submitting}>
        {submitting ? "提交中..." : buttonLabel}
      </Button>
    </form>
  );
}
