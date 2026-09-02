"use client";

import { useCallback, useEffect, useState } from "react";
import { get, post } from "@/lib/api";
import { Badge, Shell, btn, btnPrimary, card, input } from "@/components/ui";

function QuestionCard({ q, reload, onErro }: any) {
  const [resposta, setResposta] = useState("");
  const [converter, setConverter] = useState(false);
  const [titulo, setTitulo] = useState("");
  const [statement, setStatement] = useState("");

  async function agir(fn: () => Promise<any>) {
    try {
      await fn();
      reload();
    } catch (e: any) {
      onErro(e.message);
    }
  }

  return (
    <div style={card}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <Badge text={q.answer ? "respondida" : "aberta"} color={q.answer ? "#276749" : "#975a16"} />
        {q.assigned_to && <Badge text={`atribuída: ${q.assigned_to}`} />}
        {q.converted_to && <Badge text={`virou ${q.converted_to}`} color="#2b6cb0" />}
        <span style={{ fontSize: 12, color: "#a0aec0" }}>
          {q.domain}
          {q.capability ? ` / ${q.capability}` : ""} · {q.created_by}
        </span>
      </div>
      <div style={{ fontWeight: 600, margin: "8px 0 4px" }}>{q.question}</div>
      {q.description && <div style={{ fontSize: 13, color: "#718096" }}>{q.description}</div>}
      {q.answer && (
        <div style={{ marginTop: 8, padding: 10, background: "#f0fff4", borderRadius: 8, fontSize: 14 }}>
          <strong>Resposta:</strong> {q.answer}
        </div>
      )}
      {!q.answer && (
        <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
          <input
            style={{ ...input, flex: 1 }}
            placeholder="Responder (Domain Expert)"
            value={resposta}
            onChange={(e) => setResposta(e.target.value)}
          />
          <button
            style={btnPrimary}
            onClick={() =>
              resposta && agir(() => post(`/questions/${encodeURIComponent(q.id)}/answer`, { answer: resposta }))
            }
          >
            Responder
          </button>
        </div>
      )}
      {q.answer && !q.converted_to && (
        <div style={{ marginTop: 10 }}>
          {!converter ? (
            <button style={btn} onClick={() => setConverter(true)}>
              Converter em rule (§51)
            </button>
          ) : (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <input
                style={{ ...input, flex: 1, minWidth: 160 }}
                placeholder="Título da rule"
                value={titulo}
                onChange={(e) => setTitulo(e.target.value)}
              />
              <input
                style={{ ...input, flex: 2, minWidth: 200 }}
                placeholder="Statement normativo"
                value={statement}
                onChange={(e) => setStatement(e.target.value)}
              />
              <button
                style={btnPrimary}
                onClick={() =>
                  titulo &&
                  statement &&
                  agir(() =>
                    post(`/questions/${encodeURIComponent(q.id)}/convert-to-rule`, {
                      title: titulo,
                      statement,
                    })
                  )
                }
              >
                Criar rule
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function QuestionsPage() {
  const [filtro, setFiltro] = useState<"todas" | "abertas" | "respondidas">("abertas");
  const [items, setItems] = useState<any[] | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  const reload = useCallback(() => {
    const p = filtro === "todas" ? "" : `?answered=${filtro === "respondidas"}`;
    get(`/questions${p}`).then(setItems).catch((e) => setErro(e.message));
  }, [filtro]);
  useEffect(reload, [reload]);

  return (
    <Shell title="Questions">
      {erro && (
        <div style={{ ...card, background: "#fffaf0", border: "1px solid #f6ad55" }}>
          {erro} <a style={{ cursor: "pointer", color: "#2b6cb0" }} onClick={() => setErro(null)}>fechar</a>
        </div>
      )}
      <div style={{ marginBottom: 14, display: "flex", gap: 8 }}>
        {(["abertas", "respondidas", "todas"] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFiltro(f)}
            style={{
              padding: "6px 14px",
              borderRadius: 8,
              border: "1px solid #cbd5e0",
              background: filtro === f ? "#2b6cb0" : "#edf2f7",
              color: filtro === f ? "#fff" : "#4a5568",
              cursor: "pointer",
            }}
          >
            {f}
          </button>
        ))}
      </div>
      {items === null && <p>Carregando…</p>}
      {items?.length === 0 && <p style={{ color: "#718096" }}>Nenhuma question.</p>}
      {items?.map((q) => (
        <QuestionCard key={q.id} q={q} reload={reload} onErro={setErro} />
      ))}
    </Shell>
  );
}
