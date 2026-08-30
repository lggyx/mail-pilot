/** 登录页：单用户账号密码。 */

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { Button, Input } from "../components/ui";
import { toastError } from "../lib/toast";
import { useTitle } from "../lib/hooks";

export default function LoginPage() {
  useTitle("登录");
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      await api("/api/auth/login", { method: "POST", json: { username, password } });
      navigate("/", { replace: true });
      window.location.reload(); // 让全局 me 查询重新生效
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
      toastError(err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <form onSubmit={submit} className="fade-in w-full max-w-sm rounded-2xl border border-line bg-card p-8 shadow-2xl">
        <div className="mb-6 text-center">
          <div className="text-3xl">✈️</div>
          <h1 className="mt-2 text-xl font-semibold text-white">mail-pilot</h1>
          <p className="mt-1 text-xs text-fog">AI 邮件工作台 · 名单 / 代写 / 批量发送 / 送达追踪</p>
        </div>
        <div className="space-y-3">
          <Input placeholder="用户名" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
          <Input placeholder="密码" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
          {error && <p className="text-xs text-bad">{error}</p>}
          <Button type="submit" variant="primary" className="w-full" disabled={loading || !username || !password}>
            {loading ? "登录中…" : "登 录"}
          </Button>
        </div>
        <p className="mt-4 text-center text-[11px] text-fog/60">
          账号在服务器 .env 中配置（APP_USERNAME / APP_PASSWORD）
        </p>
      </form>
    </div>
  );
}
