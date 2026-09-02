"use client";

import { use, useCallback, useEffect, useState } from "react";
import { get, post } from "@/lib/api";
import {
  Badge,
  ConfidenceBar,
  RiskBadge,
  Shell,
  StatusBadge,
  btn,
  btnPrimary,
  card,
  input,
} from "@/components/ui";

const ACOES_VOTO = [
  "CONFIRM",
  "CONFIRM_WITH_EXCEPTION",
  "REJECT",
  "OBSERVED_ONLY",
  "LEGACY_BUG",
  "NEEDS_MORE_EVIDENCE",
  "NEEDS_SPECIALIST",
  "NOT_MY_DOMAIN",
];

function Gherkin({ atomId }: { atomId: string }) {
  const [texto, setTexto] = useState<string | null>(null);
  useEffect(() => {
    import("@/lib/api").then(({ API, getToken }) =>
      fetch(`${API}/projections/bdd/${encodeURIComponent(atomId)}`, {
        headers: { Authorization: `Bearer ${getToken()}` },
      })
        .then((r) => r.text())
        .then(setTexto)
    );
  }, [atomId]);
  if (!texto) return null;
  return (
    <div style={card}>
      <h3 style={{ marginTop: 0 }}>Projeção BDD (§65)</h3>
      <pre style={{ background: "#f0fff4", padding: 12, borderRadius: 8, fontSize: 13 }}>
        {texto}
      </pre>
    </div>
  );
}

function TabelaDecisao({ atomId }: { atomId: string }) {
  const [t, setT] = useState<any>(null);
  useEffect(() => {
    get(`/projections/decision-table/${encodeURIComponent(atomId)}`).then(setT).catch(() => {});
  }, [atomId]);
  if (!t || !t.rows?.length) return null;
  const cols = [...t.inputs, "output"];
  return (
    <div style={card}>
      <h3 style={{ marginTop: 0 }}>Tabela de decisão (§66)</h3>
      <div style={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "collapse", fontSize: 14 }}>
          <thead>
            <tr>
              {cols.map((c) => (
                <th key={c} style={{ border: "1px solid #e2e8f0", padding: "6px 12px", background: "#f7fafc" }}>
                  {c === "output" ? t.output : c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {t.rows.map((row: any, i: number) => (
              <tr key={i}>
                {cols.map((c) => (
                  <td key={c} style={{ border: "1px solid #e2e8f0", padding: "6px 12px" }}>
                    {String(row[c] ?? "—")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const CLASSIFICACOES = [
  "OBSERVED_BEHAVIOR",
  "INTENDED_BEHAVIOR",
  "MANDATED_BEHAVIOR",
  "LEGACY_QUIRK",
  "KNOWN_BUG",
  "DEPRECATED_BEHAVIOR",
  "UNKNOWN",
];

function Evidencia({ e }: { e: any }) {
  const [tecnica, setTecnica] = useState(false);
  const contra = e.relation === "contradicts";
  return (
    <div
      style={{
        border: `1px solid ${contra ? "#feb2b2" : "#e2e8f0"}`,
        background: contra ? "#fff5f5" : "#f7fafc",
        borderRadius: 8,
        padding: 10,
        marginBottom: 8,
      }}
    >
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <Badge text={e.type} color={contra ? "#c53030" : "#2b6cb0"} />
        {contra && <Badge text="contradiz" color="#c53030" />}
        <span style={{ fontSize: 12, color: "#a0aec0" }}>{e.created_by}</span>
      </div>
      <div style={{ marginTop: 6, fontSize: 14 }}>
        {e.summary ?? "Sem tradução de negócio registrada."}
      </div>
      <button style={{ ...btn, marginTop: 8, fontSize: 12 }} onClick={() => setTecnica(!tecnica)}>
        {tecnica ? "Ocultar fonte técnica" : "Ver fonte técnica"}
      </button>
      {tecnica && (
        <div
          style={{
            marginTop: 8,
            fontFamily: "monospace",
            fontSize: 12,
            background: "#1a202c",
            color: "#e2e8f0",
            borderRadius: 6,
            padding: 10,
            overflowX: "auto",
          }}
        >
          {e.location && <div>{JSON.stringify(e.location)}</div>}
          {e.excerpt && <pre style={{ margin: "6px 0 0" }}>{e.excerpt}</pre>}
          {!e.location && !e.excerpt && <div>Sem detalhe técnico registrado.</div>}
        </div>
      )}
    </div>
  );
}

export default function DecisionRoom({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const atomId = decodeURIComponent(id);
  const [room, setRoom] = useState<any>(null);
  const [impact, setImpact] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [showConf, setShowConf] = useState(false);
  const [voto, setVoto] = useState("CONFIRM");
  const [votoComment, setVotoComment] = useState("");
  const [comentario, setComentario] = useState("");
  const [decReason, setDecReason] = useState("");
  const [decClass, setDecClass] = useState("OBSERVED_BEHAVIOR");
  const [excTitle, setExcTitle] = useState("");
  const [excCond, setExcCond] = useState("");

  const reload = useCallback(() => {
    get(`/reviews/${encodeURIComponent(atomId)}`)
      .then(setRoom)
      .catch((e) => setError(e.message));
  }, [atomId]);
  useEffect(reload, [reload]);

  async function acao(fn: () => Promise<any>) {
    setMsg(null);
    try {
      await fn();
      reload();
    } catch (e: any) {
      setMsg(e.message);
      reload(); // 409 → recarrega o estado atual (§105)
    }
  }

  if (error) return <Shell title="Decision Room">Erro: {error}</Shell>;
  if (!room) return <Shell title="Decision Room">Carregando…</Shell>;

  const a = room.atom;
  const decidir = (action: string, extra: object = {}) =>
    acao(() =>
      post(`/reviews/${encodeURIComponent(atomId)}/decision`, {
        action,
        reason: decReason || "decisão do owner",
        expected_lock_version: a.lock_version,
        ...extra,
      })
    );

  return (
    <Shell title="Decision Room">
      {msg && (
        <div style={{ ...card, background: "#fffaf0", border: "1px solid #f6ad55" }}>{msg}</div>
      )}

      <div style={card}>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <StatusBadge status={a.status} />
          <RiskBadge risk={a.risk} />
          <Badge text={a.kind} />
          {a.classification && <Badge text={a.classification} color="#6b46c1" />}
          <span style={{ fontSize: 12, color: "#a0aec0" }}>
            {a.domain}
            {a.capability ? ` / ${a.capability}` : ""} · {a.id} · v{a.version}
          </span>
        </div>
        <h2 style={{ margin: "10px 0 4px" }}>{a.title}</h2>
        {a.statement && <p style={{ fontSize: 15, margin: "4px 0" }}>{a.statement}</p>}
        {a.description && <p style={{ color: "#718096", margin: "4px 0" }}>{a.description}</p>}
        <div style={{ marginTop: 10, display: "flex", gap: 12, alignItems: "center" }}>
          <span style={{ fontSize: 13, color: "#718096" }}>Confiança:</span>
          <ConfidenceBar value={a.confidence} />
          {room.confidence && (
            <button style={{ ...btn, fontSize: 12 }} onClick={() => setShowConf(!showConf)}>
              {showConf ? "Ocultar explicação" : "Por que este número?"}
            </button>
          )}
        </div>
        {showConf && room.confidence && (
          <ul style={{ marginTop: 8, fontSize: 13 }}>
            {room.confidence.signals
              .filter((s: any) => s.contribution !== 0)
              .map((s: any) => (
                <li key={s.name} style={{ color: s.contribution > 0 ? "#276749" : "#c53030" }}>
                  {s.contribution > 0 ? "+" : ""}
                  {s.contribution.toFixed(2)} — {s.explanation}
                </li>
              ))}
          </ul>
        )}
      </div>

      <div style={card}>
        <h3 style={{ marginTop: 0 }}>Evidências ({room.evidence.length})</h3>
        {room.evidence.map((e: any) => (
          <Evidencia key={e.id} e={e} />
        ))}
        {room.contradicting_evidence.length > 0 && (
          <>
            <h3 style={{ color: "#c53030" }}>
              Evidências contraditórias ({room.contradicting_evidence.length})
            </h3>
            {room.contradicting_evidence.map((e: any) => (
              <Evidencia key={e.id} e={e} />
            ))}
          </>
        )}
      </div>

      {(room.relations.length > 0 || true) && (
        <div style={card}>
          <h3 style={{ marginTop: 0 }}>Relações e impacto</h3>
          <ul style={{ fontSize: 14 }}>
            {room.relations.map((r: any, i: number) => (
              <li key={i}>
                {r.direction === "out" ? `${r.type} → ` : `← ${r.type} `}
                <a href={`/atom/${encodeURIComponent(r.atom)}`}>{r.title}</a>
              </li>
            ))}
          </ul>
          <button
            style={btn}
            onClick={async () => {
              const imp = await get(`/knowledge/${encodeURIComponent(atomId)}/impact`);
              setImpact(imp);
            }}
          >
            O que é afetado se isto mudar? (§55)
          </button>
          {impact && (
            <div style={{ marginTop: 10, fontSize: 14 }}>
              <div style={{ color: "#718096", marginBottom: 6 }}>
                {impact.total} atom(s) afetado(s) —{" "}
                {Object.entries(impact.by_kind)
                  .map(([k, n]) => `${k}: ${n}`)
                  .join(" · ")}
              </div>
              {impact.direct.length > 0 && <strong>Impacto direto:</strong>}
              <ul>
                {impact.direct.map((i: any) => (
                  <li key={i.id}>
                    <a href={`/atom/${encodeURIComponent(i.id)}`}>{i.title}</a>{" "}
                    <Badge text={i.kind} />
                  </li>
                ))}
              </ul>
              {impact.transitive.length > 0 && <strong>Impacto transitivo:</strong>}
              <ul>
                {impact.transitive.map((i: any) => (
                  <li key={i.id}>
                    <a href={`/atom/${encodeURIComponent(i.id)}`}>{i.title}</a>{" "}
                    <Badge text={i.kind} /> <span style={{ color: "#a0aec0" }}>d{i.distance}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {a.kind === "scenario" && <Gherkin atomId={atomId} />}
      {a.kind === "decision" && <TabelaDecisao atomId={atomId} />}

      <div style={card}>
        <h3 style={{ marginTop: 0 }}>
          Votos ({room.summary.total_votes}) — recomendação do sistema:{" "}
          <Badge text={room.summary.recommendation} color="#2b6cb0" />
        </h3>
        {room.votes.map((v: any, i: number) => (
          <div key={i} style={{ fontSize: 14, marginBottom: 6 }}>
            <strong>{v.reviewer}</strong> <Badge text={v.role} />{" "}
            {v.domain_expert && <Badge text="expert" color="#6b46c1" />}{" "}
            <Badge
              text={v.action}
              color={v.action.startsWith("CONFIRM") ? "#276749" : v.action === "REJECT" ? "#c53030" : "#975a16"}
            />
            {v.comment && <span style={{ color: "#718096" }}> — {v.comment}</span>}
          </div>
        ))}
        {room.permissions.can_vote && (
          <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
            <select style={input} value={voto} onChange={(e) => setVoto(e.target.value)}>
              {ACOES_VOTO.map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
            <input
              style={{ ...input, flex: 1, minWidth: 160 }}
              placeholder="comentário (opcional)"
              value={votoComment}
              onChange={(e) => setVotoComment(e.target.value)}
            />
            <button
              style={btnPrimary}
              onClick={() =>
                acao(() =>
                  post(`/reviews/${encodeURIComponent(atomId)}/vote`, {
                    action: voto,
                    comment: votoComment || null,
                  })
                )
              }
            >
              {room.my_vote ? `Mudar voto (${room.my_vote})` : "Votar"}
            </button>
            <button
              style={btn}
              onClick={() =>
                acao(() => post(`/reviews/${encodeURIComponent(atomId)}/ready-for-decision`))
              }
            >
              Pronto p/ decisão
            </button>
            <button
              style={btn}
              onClick={() =>
                acao(() =>
                  post(`/reviews/${encodeURIComponent(atomId)}/request-evidence`, {
                    note: "mais evidência necessária",
                  })
                )
              }
            >
              Pedir evidência
            </button>
          </div>
        )}
      </div>

      <div style={card}>
        <h3 style={{ marginTop: 0 }}>Comentários ({room.comments.length})</h3>
        {room.comments.map((c: any, i: number) => (
          <div key={i} style={{ fontSize: 14, marginBottom: 6 }}>
            <strong>{c.author}</strong>{" "}
            <span style={{ color: "#a0aec0", fontSize: 12 }}>{c.at.slice(0, 16)}</span>
            <div>{c.text}</div>
          </div>
        ))}
        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <input
            style={{ ...input, flex: 1 }}
            placeholder="Comente (mencione por e-mail para notificar)"
            value={comentario}
            onChange={(e) => setComentario(e.target.value)}
          />
          <button
            style={btnPrimary}
            onClick={() =>
              comentario &&
              acao(async () => {
                await post(`/reviews/${encodeURIComponent(atomId)}/comment`, { text: comentario });
                setComentario("");
              })
            }
          >
            Enviar
          </button>
        </div>
      </div>

      {room.permissions.can_decide && (
        <div style={{ ...card, border: "2px solid #6b46c1" }}>
          <h3 style={{ marginTop: 0, color: "#6b46c1" }}>Decisão (Decision Owner)</h3>
          <input
            style={{ ...input, width: "100%", marginBottom: 8 }}
            placeholder="Justificativa da decisão"
            value={decReason}
            onChange={(e) => setDecReason(e.target.value)}
          />
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button style={{ ...btnPrimary, background: "#276749" }} onClick={() => decidir("APPROVE")}>
              Aprovar como canônico
            </button>
            <button style={{ ...btnPrimary, background: "#9b2c2c" }} onClick={() => decidir("REJECT")}>
              Rejeitar
            </button>
            <button style={btn} onClick={() => decidir("MARK_KNOWN_BUG")}>
              Marcar bug legado
            </button>
            <button style={btn} onClick={() => decidir("REQUEST_EVIDENCE")}>
              Pedir mais evidência
            </button>
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 10, alignItems: "center", flexWrap: "wrap" }}>
            <select style={input} value={decClass} onChange={(e) => setDecClass(e.target.value)}>
              {CLASSIFICACOES.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
            <button style={btn} onClick={() => decidir("RECLASSIFY", { classification: decClass })}>
              Reclassificar
            </button>
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
            <input
              style={{ ...input, flex: 1, minWidth: 180 }}
              placeholder="Título da exceção"
              value={excTitle}
              onChange={(e) => setExcTitle(e.target.value)}
            />
            <input
              style={{ ...input, flex: 1, minWidth: 180 }}
              placeholder="Condição (ex.: customer.type == GOVERNMENT)"
              value={excCond}
              onChange={(e) => setExcCond(e.target.value)}
            />
            <button
              style={btn}
              onClick={() =>
                excTitle &&
                excCond &&
                decidir("ADD_EXCEPTION", { exception: { title: excTitle, condition: excCond } })
              }
            >
              Adicionar exceção
            </button>
          </div>
        </div>
      )}
    </Shell>
  );
}
