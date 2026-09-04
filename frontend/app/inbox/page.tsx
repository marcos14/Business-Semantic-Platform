"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { get, post } from "@/lib/api";
import { Badge, ConfidenceBar, RiskBadge, Shell, StatusBadge, btnPrimary, card } from "@/components/ui";

type Item = {
  id: string;
  kind: string;
  title: string;
  domain: string;
  capability: string | null;
  status: string;
  confidence: number | null;
  risk: string | null;
  supporting_evidence: number;
  conflicting_evidence: number;
  votes: number;
  priority: { score: number; breakdown: Record<string, number> };
  needs_your_decision: boolean;
};

export default function InboxPage() {
  const [data, setData] = useState<{ summary: any; items: Item[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [admin, setAdmin] = useState(false);
  const [triagem, setTriagem] = useState<{ rodando: boolean; msg: string | null }>({ rodando: false, msg: null });

  const load = () => get("/reviews/inbox").then(setData).catch((e) => setError(e.message));
  useEffect(() => {
    load();
    get("/admin/domains").then(() => setAdmin(true)).catch(() => setAdmin(false));
  }, []);

  const aplicarRegua = async () => {
    setTriagem({ rodando: true, msg: null });
    try {
      const r = await post("/discovery/triage", {});
      const por = Object.entries(r.by_significance as Record<string, number>)
        .filter(([, n]) => n > 0)
        .map(([k, n]) => `${n} ${k.toLowerCase()}`)
        .join(", ");
      setTriagem({
        rodando: false,
        msg: `${r.considered} pendente(s) analisados · ${r.classified} classificados (${por || "nenhum"}) · ${r.auto_approved} aprovados automaticamente · ${r.awaiting_evidence} aguardando evidência · ${r.still_human} seguem para revisão · ${r.unclassified} sem resposta do modelo.`,
      });
      load();
    } catch (e: any) {
      setTriagem({ rodando: false, msg: `Erro: ${e.message}` });
    }
  };

  if (error) return <Shell title="Inbox">Erro: {error}</Shell>;
  if (!data) return <Shell title="Inbox">Carregando…</Shell>;

  const s = data.summary;
  const resumo = [
    [s.awaiting_review, "aguardando sua revisão"],
    [s.needs_decision, "decisões aguardando você"],
    [s.with_conflicts, "itens com evidência contraditória"],
    [s.canonical_challenged, "regras canônicas desafiadas"],
  ] as const;

  return (
    <Shell title="Sua Inbox de Revisão">
      <div style={{ display: "flex", gap: 12, marginBottom: 20, flexWrap: "wrap" }}>
        {resumo.map(([n, label]) => (
          <div key={label} style={{ ...card, flex: 1, minWidth: 180, marginBottom: 0 }}>
            <div style={{ fontSize: 28, fontWeight: 700 }}>{n}</div>
            <div style={{ color: "#718096", fontSize: 13 }}>{label}</div>
          </div>
        ))}
      </div>

      {admin && (
        <div style={{ ...card, display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", background: "#f7fafc" }}>
          <div style={{ flex: 1, fontSize: 13, color: "#4a5568" }}>
            <strong>Régua de relevância.</strong> Itens criados antes da régua chegaram aqui sem
            classificação. A triagem usa o modelo de análise para marcar cada pendente sem voto como
            sistêmico, baixo, médio ou alto: sistêmico é aprovado direto, baixo aprova com régua
            reduzida ou aguarda evidência, médio e alto continuam na Inbox.
            {triagem.msg && <div style={{ marginTop: 6, color: triagem.msg.startsWith("Erro") ? "#c53030" : "#276749" }}>{triagem.msg}</div>}
          </div>
          <button style={btnPrimary} disabled={triagem.rodando} onClick={aplicarRegua}>
            {triagem.rodando ? "Classificando…" : "Aplicar régua aos pendentes"}
          </button>
        </div>
      )}
      {data.items.length === 0 && (
        <p style={{ color: "#718096" }}>Nada aguardando sua atenção. 🎉</p>
      )}
      {data.items.map((i) => (
        <Link key={i.id} href={`/atom/${encodeURIComponent(i.id)}`} style={{ textDecoration: "none", color: "inherit" }}>
          <div style={{ ...card, display: "flex", gap: 14, alignItems: "center" }}>
            <div
              title={Object.entries(i.priority.breakdown)
                .map(([k, v]) => `${k}: ${v}`)
                .join("\n")}
              style={{
                minWidth: 52,
                textAlign: "center",
                background: "#f7fafc",
                border: "1px solid #e2e8f0",
                borderRadius: 8,
                padding: "6px 4px",
              }}
            >
              <div style={{ fontSize: 16, fontWeight: 700 }}>{i.priority.score}</div>
              <div style={{ fontSize: 10, color: "#a0aec0" }}>prioridade</div>
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 600 }}>{i.title}</div>
              <div style={{ fontSize: 13, color: "#718096", marginTop: 2 }}>
                {i.domain}
                {i.capability ? ` / ${i.capability}` : ""} · {i.kind} ·{" "}
                {i.supporting_evidence} evidência(s) a favor
                {i.conflicting_evidence > 0 ? `, ${i.conflicting_evidence} contra` : ""} ·{" "}
                {i.votes} voto(s)
              </div>
              <div style={{ display: "flex", gap: 6, marginTop: 6, alignItems: "center" }}>
                <StatusBadge status={i.status} />
                <RiskBadge risk={i.risk} />
                {i.needs_your_decision && <Badge text="decisão sua" color="#6b46c1" />}
              </div>
            </div>
            <ConfidenceBar value={i.confidence} />
          </div>
        </Link>
      ))}
    </Shell>
  );
}
