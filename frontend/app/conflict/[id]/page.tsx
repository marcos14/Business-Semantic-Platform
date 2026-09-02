"use client";

import { use, useCallback, useEffect, useState } from "react";
import { get, post } from "@/lib/api";
import {
  Badge,
  ConfidenceBar,
  Shell,
  StatusBadge,
  btn,
  btnPrimary,
  card,
  input,
} from "@/components/ui";

function Lado({ lado, escolher, scopeVal, setScope }: any) {
  const [tecnica, setTecnica] = useState<string | null>(null);
  const a = lado.atom;
  return (
    <div style={{ ...card, flex: 1, minWidth: 300, border: "1px solid #e2e8f0" }}>
      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
        <StatusBadge status={a.status} />
        {a.classification && <Badge text={a.classification} color="#6b46c1" />}
        <ConfidenceBar value={a.confidence} />
      </div>
      <h3 style={{ margin: "8px 0 4px" }}>{a.title}</h3>
      {a.statement && <p style={{ fontSize: 14 }}>{a.statement}</p>}
      {a.scope && (
        <div style={{ fontSize: 12, color: "#718096" }}>escopo: {JSON.stringify(a.scope)}</div>
      )}
      <h4 style={{ marginBottom: 4 }}>Evidências ({lado.evidence.length})</h4>
      {lado.evidence.map((e: any) => (
        <div
          key={e.id}
          style={{
            fontSize: 13,
            padding: 8,
            borderRadius: 6,
            marginBottom: 6,
            background: e.relation === "contradicts" ? "#fff5f5" : "#f7fafc",
            border: `1px solid ${e.relation === "contradicts" ? "#feb2b2" : "#e2e8f0"}`,
          }}
        >
          <Badge text={e.type} color={e.relation === "contradicts" ? "#c53030" : "#2b6cb0"} />{" "}
          {e.relation === "contradicts" && <Badge text="contradiz" color="#c53030" />}
          <div style={{ marginTop: 4 }}>{e.summary ?? "—"}</div>
          <a
            style={{ fontSize: 12, cursor: "pointer", color: "#2b6cb0" }}
            onClick={() => setTecnica(tecnica === e.id ? null : e.id)}
          >
            {tecnica === e.id ? "ocultar fonte" : "ver fonte técnica"}
          </a>
          {tecnica === e.id && (
            <pre
              style={{
                background: "#1a202c",
                color: "#e2e8f0",
                padding: 8,
                borderRadius: 6,
                overflowX: "auto",
                fontSize: 11,
              }}
            >
              {JSON.stringify(e.location)}
              {"\n"}
              {e.excerpt}
            </pre>
          )}
        </div>
      ))}
      {escolher && (
        <div style={{ marginTop: 8, display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button style={btnPrimary} onClick={() => escolher(a.id)}>
            Selecionar esta assertion
          </button>
          <input
            style={{ ...input, flex: 1, minWidth: 140 }}
            placeholder='escopo p/ split, ex.: {"pais":"BR"}'
            value={scopeVal ?? ""}
            onChange={(e) => setScope(a.id, e.target.value)}
          />
        </div>
      )}
    </div>
  );
}

export default function ConflictView({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const conflictId = decodeURIComponent(id);
  const [c, setC] = useState<any>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [scopes, setScopes] = useState<Record<string, string>>({});

  const reload = useCallback(() => {
    get(`/conflicts/${encodeURIComponent(conflictId)}`).then(setC).catch((e) => setErro(e.message));
  }, [conflictId]);
  useEffect(reload, [reload]);

  if (erro) return <Shell title="Conflito">Erro: {erro}</Shell>;
  if (!c) return <Shell title="Conflito">Carregando…</Shell>;

  async function resolver(action: string, extra: object = {}) {
    setErro(null);
    try {
      await post(`/conflicts/${encodeURIComponent(conflictId)}/resolve`, {
        action,
        reason: reason || "resolução do owner",
        expected_lock_version: c.lock_version,
        params: extra,
      });
      reload();
    } catch (e: any) {
      setErro(e.message);
      reload();
    }
  }

  const aberto = c.state === "open";
  return (
    <Shell title="Conflito">
      {erro && <div style={{ ...card, background: "#fffaf0", border: "1px solid #f6ad55" }}>{erro}</div>}
      <div style={card}>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <Badge
            text={c.state === "open" ? "aberto" : c.state === "resolved" ? "resolvido" : "não resolvido"}
            color={c.state === "open" ? "#c53030" : "#276749"}
          />
          {c.reevaluation && <Badge text="reavaliação de canonical (§74)" color="#6b46c1" />}
          <span style={{ fontSize: 12, color: "#a0aec0" }}>{c.id}</span>
        </div>
        <h2 style={{ margin: "8px 0" }}>{c.topic}</h2>
        {c.resolution && (
          <p style={{ fontSize: 14, color: "#718096" }}>
            Resolução: <strong>{c.resolution.action}</strong> por {c.resolution.by} — {c.resolution.reason}
          </p>
        )}
      </div>

      <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
        {c.sides.map((lado: any) => (
          <Lado
            key={lado.atom.id}
            lado={lado}
            scopeVal={scopes[lado.atom.id]}
            setScope={(id: string, v: string) => setScopes({ ...scopes, [id]: v })}
            escolher={
              aberto && !c.about
                ? (atomId: string) => resolver("SELECT_ASSERTION", { winner_atom_id: atomId })
                : null
            }
          />
        ))}
      </div>

      {aberto && (
        <div style={{ ...card, border: "2px solid #6b46c1", marginTop: 12 }}>
          <h3 style={{ marginTop: 0, color: "#6b46c1" }}>Resolução (Decision Owner)</h3>
          <input
            style={{ ...input, width: "100%", marginBottom: 8 }}
            placeholder="Justificativa"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {!c.about && (
              <button
                style={btn}
                onClick={() => {
                  const splits = c.sides
                    .filter((l: any) => scopes[l.atom.id])
                    .map((l: any) => ({ atom_id: l.atom.id, scope: JSON.parse(scopes[l.atom.id]) }));
                  resolver("SPLIT_BY_SCOPE", { splits });
                }}
              >
                Split por escopo (usa os campos acima)
              </button>
            )}
            <button style={btn} onClick={() => resolver("REQUEST_EVIDENCE")}>
              Pedir mais evidência
            </button>
            <button style={btn} onClick={() => resolver("MARK_UNRESOLVED")}>
              Marcar não resolvido
            </button>
          </div>
          {c.about && (
            <p style={{ fontSize: 13, color: "#718096", marginTop: 8 }}>
              Conflito sobre atom canonical: a regra não muda por aqui — use new-version/supersede
              na Decision Room após a reavaliação (§74).
            </p>
          )}
        </div>
      )}
    </Shell>
  );
}
