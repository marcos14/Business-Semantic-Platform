"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { get } from "@/lib/api";
import { ConfidenceBar, RiskBadge, Shell } from "@/components/ui";

const COLUNAS: Record<string, string> = {
  needs_review: "Aguardando revisão",
  in_discussion: "Em discussão",
  needs_evidence: "Precisa de evidência",
  needs_decision: "Aguardando decisão",
  approved: "Aprovados",
  rejected: "Rejeitados",
};

export default function KanbanPage() {
  const [cols, setCols] = useState<Record<string, any[]> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    get("/reviews/kanban").then((d) => setCols(d.columns)).catch((e) => setError(e.message));
  }, []);

  if (error) return <Shell title="Kanban">Erro: {error}</Shell>;
  if (!cols) return <Shell title="Kanban">Carregando…</Shell>;

  return (
    <div>
      <Shell title="Kanban de Governança">
        <div style={{ display: "flex", gap: 12, overflowX: "auto", paddingBottom: 12 }}>
          {Object.entries(COLUNAS).map(([key, label]) => (
            <div
              key={key}
              style={{
                minWidth: 230,
                flex: 1,
                background: "#edf2f7",
                borderRadius: 10,
                padding: 10,
              }}
            >
              <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 8, color: "#4a5568" }}>
                {label} ({cols[key]?.length ?? 0})
              </div>
              {(cols[key] ?? []).map((c) => (
                <Link
                  key={c.id}
                  href={`/atom/${encodeURIComponent(c.id)}`}
                  style={{ textDecoration: "none", color: "inherit" }}
                >
                  <div
                    style={{
                      background: "#fff",
                      borderRadius: 8,
                      padding: 10,
                      marginBottom: 8,
                      boxShadow: "0 1px 2px rgba(0,0,0,.08)",
                    }}
                  >
                    <div style={{ fontSize: 13, fontWeight: 600 }}>{c.title}</div>
                    <div style={{ fontSize: 11, color: "#718096", margin: "4px 0" }}>
                      {c.domain}
                      {c.capability ? ` / ${c.capability}` : ""}
                    </div>
                    <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                      <ConfidenceBar value={c.confidence} />
                      <RiskBadge risk={c.risk} />
                    </div>
                    <div style={{ fontSize: 11, color: "#a0aec0", marginTop: 4 }}>
                      {c.supporting_evidence} a favor
                      {c.conflicting_evidence > 0 ? ` · ${c.conflicting_evidence} contra` : ""} ·{" "}
                      {c.votes} voto(s)
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          ))}
        </div>
      </Shell>
    </div>
  );
}
