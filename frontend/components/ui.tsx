"use client";

import Link from "next/link";
import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { clearToken, get } from "@/lib/api";

export const STATUS_LABEL: Record<string, string> = {
  DISCOVERED: "Descoberto",
  CANDIDATE: "Candidato",
  CORROBORATING: "Aguardando evidência",
  READY_FOR_EVALUATION: "Pronto p/ avaliação",
  AUTO_APPROVED: "Auto-aprovado",
  NEEDS_HUMAN_REVIEW: "Aguardando revisão",
  IN_REVIEW: "Em discussão",
  DECISION_PENDING: "Aguardando decisão",
  CANONICAL: "Canônico",
  REJECTED: "Rejeitado",
  SUPERSEDED: "Substituído",
  CONFLICTED: "Em conflito",
  UNKNOWN: "Desconhecido",
  LEGACY_BUG: "Bug legado",
};

const STATUS_COLOR: Record<string, string> = {
  CANONICAL: "#276749",
  AUTO_APPROVED: "#276749",
  REJECTED: "#9b2c2c",
  LEGACY_BUG: "#9b2c2c",
  NEEDS_HUMAN_REVIEW: "#975a16",
  IN_REVIEW: "#2b6cb0",
  DECISION_PENDING: "#6b46c1",
  CORROBORATING: "#975a16",
  CONFLICTED: "#c53030",
};

const RISK_COLOR: Record<string, string> = {
  LOW: "#718096",
  MEDIUM: "#975a16",
  HIGH: "#c05621",
  CRITICAL: "#c53030",
};

export function Badge({ text, color }: { text: string; color?: string }) {
  return (
    <span
      style={{
        background: (color ?? "#718096") + "22",
        color: color ?? "#4a5568",
        border: `1px solid ${(color ?? "#718096")}55`,
        borderRadius: 6,
        padding: "1px 8px",
        fontSize: 12,
        fontWeight: 600,
        whiteSpace: "nowrap",
      }}
    >
      {text}
    </span>
  );
}

export const StatusBadge = ({ status }: { status: string }) => (
  <Badge text={STATUS_LABEL[status] ?? status} color={STATUS_COLOR[status]} />
);

export const RiskBadge = ({ risk }: { risk: string | null }) =>
  risk ? <Badge text={`risco ${risk}`} color={RISK_COLOR[risk]} /> : null;

export function ConfidenceBar({ value }: { value: number | null }) {
  if (value === null || value === undefined) return <span style={{ color: "#a0aec0" }}>—</span>;
  const pct = Math.round(value * 100);
  const color = pct >= 90 ? "#276749" : pct >= 70 ? "#975a16" : "#c53030";
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
      <span style={{ width: 70, height: 8, background: "#e2e8f0", borderRadius: 4 }}>
        <span
          style={{
            display: "block",
            width: `${pct}%`,
            height: 8,
            background: color,
            borderRadius: 4,
          }}
        />
      </span>
      <strong style={{ color, fontSize: 13 }}>{pct}%</strong>
    </span>
  );
}

export const card: CSSProperties = {
  background: "#fff",
  borderRadius: 10,
  padding: 16,
  boxShadow: "0 1px 3px rgba(0,0,0,.08)",
  marginBottom: 12,
};

export const btn: CSSProperties = {
  padding: "8px 14px",
  borderRadius: 8,
  border: "1px solid #cbd5e0",
  background: "#edf2f7",
  cursor: "pointer",
  fontSize: 14,
};

export const btnPrimary: CSSProperties = {
  ...btn,
  background: "#2b6cb0",
  color: "#fff",
  border: "none",
  fontWeight: 600,
};

export const input: CSSProperties = {
  padding: "8px 10px",
  border: "1px solid #cbd5e0",
  borderRadius: 8,
  fontSize: 14,
  boxSizing: "border-box",
};

function Nav() {
  const [unread, setUnread] = useState(0);
  useEffect(() => {
    get("/notifications?unread_only=true")
      .then((d) => setUnread(d.unread))
      .catch(() => {});
  }, []);
  const link: CSSProperties = {
    color: "#e2e8f0",
    textDecoration: "none",
    padding: "6px 12px",
    borderRadius: 6,
    fontSize: 14,
  };
  return (
    <nav
      style={{
        background: "#1a202c",
        display: "flex",
        alignItems: "center",
        gap: 4,
        padding: "10px 20px",
      }}
    >
      <strong style={{ color: "#fff", marginRight: 16 }}>BSP</strong>
      <Link href="/dashboard" style={link}>
        Dashboard
      </Link>
      <Link href="/inbox" style={link}>
        Inbox
      </Link>
      <Link href="/kanban" style={link}>
        Kanban
      </Link>
      <Link href="/explorer" style={link}>
        Explorer
      </Link>
      <Link href="/conflicts" style={link}>
        Conflitos
      </Link>
      <Link href="/questions" style={link}>
        Questions
      </Link>
      <Link href="/sources" style={link}>
        Sources
      </Link>
      <Link href="/notifications" style={link}>
        Notificações{unread > 0 ? ` (${unread})` : ""}
      </Link>
      <span style={{ flex: 1 }} />
      <a
        style={{ ...link, cursor: "pointer" }}
        onClick={() => {
          clearToken();
          window.location.href = "/";
        }}
      >
        Sair
      </a>
    </nav>
  );
}

export function Shell({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <Nav />
      <main style={{ maxWidth: 980, margin: "24px auto", padding: "0 16px" }}>
        <h1 style={{ fontSize: 22, marginTop: 0 }}>{title}</h1>
        {children}
      </main>
    </div>
  );
}
