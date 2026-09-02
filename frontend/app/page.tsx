"use client";

import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function Home() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    try {
      const token = localStorage.getItem("bsp_token");
      if (!token) return;
      fetch(`${API}/auth/me`, { headers: { Authorization: `Bearer ${token}` } }).then((r) => {
        if (r.ok) window.location.href = "/inbox";
      });
    } catch {
      /* storage indisponível */
    }
  }, []);

  async function login(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const r = await fetch(`${API}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!r.ok) {
        setError(r.status === 401 ? "Credenciais inválidas" : `Erro ${r.status}`);
        return;
      }
      const { access_token } = await r.json();
      try {
        localStorage.setItem("bsp_token", access_token);
      } catch {
        /* segue sem persistir */
      }
      window.location.href = "/inbox";
    } catch {
      setError("API indisponível — o backend está rodando?");
    } finally {
      setLoading(false);
    }
  }

  const input: React.CSSProperties = {
    width: "100%",
    padding: "10px 12px",
    marginBottom: 12,
    border: "1px solid #cbd5e0",
    borderRadius: 8,
    fontSize: 15,
    boxSizing: "border-box",
  };

  return (
    <main
      style={{
        maxWidth: 420,
        margin: "10vh auto",
        background: "#fff",
        borderRadius: 12,
        padding: 32,
        boxShadow: "0 1px 4px rgba(0,0,0,.08)",
      }}
    >
      <h1 style={{ fontSize: 22, marginTop: 0 }}>Business Semantic Platform</h1>
      <p style={{ color: "#718096" }}>Entre com sua conta.</p>
      <form onSubmit={login}>
        <input
          style={input}
          type="email"
          placeholder="E-mail"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        <input
          style={input}
          type="password"
          placeholder="Senha"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        <button
          type="submit"
          disabled={loading}
          style={{
            ...input,
            cursor: "pointer",
            background: "#2b6cb0",
            color: "#fff",
            border: "none",
            fontWeight: 600,
          }}
        >
          {loading ? "Entrando…" : "Entrar"}
        </button>
      </form>
      {error && <p style={{ color: "#c53030" }}>{error}</p>}
    </main>
  );
}
