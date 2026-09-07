"use client";

import { useEffect, useRef, useState } from "react";
import { get, post } from "@/lib/api";
import { Badge, Shell, btn, btnPrimary, card, input } from "@/components/ui";

type Step = {
  tool: string;
  arguments: Record<string, unknown>;
  ok: boolean;
  result_preview: string;
};
type Msg = { role: "user" | "assistant"; content: string; steps?: Step[]; error?: boolean };
type Tool = { name: string; group: string; description: string; mutating: boolean };

const SUGESTOES = [
  "Como está o andamento geral? O que está travando o funil?",
  "O que falta fazer em cada source cadastrada?",
  "Resuma minha inbox por prioridade e diga por onde começar.",
  "Quais capabilities inventariadas ainda não têm campanha dirigida?",
  "Há jobs parados na fila sem worker vivo?",
  "Quais perguntas do help desk ficaram sem resposta (lacunas)?",
];

const GRUPO: Record<string, string> = {
  meta: "visão geral",
  admin: "cadastros",
  sources: "sources",
  discovery: "discovery",
  knowledge: "conhecimento",
  reviews: "revisão",
  conflicts: "conflitos",
  questions: "questions",
  consume: "consumo",
  metrics: "métricas",
  helpdesk: "help desk",
  notifications: "notificações",
};

function argsResumo(a: Record<string, unknown>): string {
  const partes = Object.entries(a)
    .filter(([, v]) => v !== null && v !== undefined)
    .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`);
  return partes.join(", ").slice(0, 160);
}

export default function AssistantPage() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const [readOnly, setReadOnly] = useState(false);
  const [loading, setLoading] = useState(false);
  const [tools, setTools] = useState<Tool[]>([]);
  const [showTools, setShowTools] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    get("/assistant/tools").then(setTools).catch(() => {});
  }, []);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function send(pergunta?: string) {
    const content = (pergunta ?? text).trim();
    if (!content || loading) return;
    const history: Msg[] = [...messages.filter((m) => !m.error), { role: "user", content }];
    setMessages(history);
    setText("");
    setLoading(true);
    try {
      const r = await post("/assistant/chat", {
        messages: history.map((m) => ({ role: m.role, content: m.content })),
        read_only: readOnly,
      });
      setMessages([
        ...history,
        {
          role: "assistant",
          content: r.reply || "(sem resposta)",
          steps: r.steps,
        },
      ]);
    } catch (e: any) {
      setMessages([
        ...history,
        { role: "assistant", content: e.message ?? "Falha ao consultar o assistente.", error: true },
      ]);
    } finally {
      setLoading(false);
    }
  }

  const porGrupo = tools.reduce<Record<string, Tool[]>>((acc, t) => {
    (acc[t.group] ??= []).push(t);
    return acc;
  }, {});

  return (
    <Shell title="Assistente · andamento, insights e operação por conversa">
      <div style={{ ...card, display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        <span style={{ fontSize: 14, color: "#4a5568", flex: 1, minWidth: 260 }}>
          O assistente opera a plataforma com as <strong>suas</strong> permissões: consulta fontes,
          campanhas, fila, inbox e métricas, e executa ações quando você pede (cadastros,
          votos, disparos de discovery…). Ações difíceis de desfazer pedem confirmação.
        </span>
        <label style={{ fontSize: 13, display: "flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={readOnly} onChange={(e) => setReadOnly(e.target.checked)} />
          somente leitura
        </label>
        <button style={btn} onClick={() => setShowTools((v) => !v)}>
          {showTools ? "Ocultar ferramentas" : `Ferramentas (${tools.length})`}
        </button>
        <button style={btn} onClick={() => setMessages([])} disabled={!messages.length}>
          Nova conversa
        </button>
      </div>

      {showTools && (
        <div style={card}>
          {Object.entries(porGrupo).map(([g, lista]) => (
            <div key={g} style={{ marginBottom: 8 }}>
              <strong style={{ fontSize: 13 }}>{GRUPO[g] ?? g}</strong>{" "}
              {lista.map((t) => (
                <span key={t.name} title={t.description} style={{ marginRight: 6 }}>
                  <Badge text={t.name} color={t.mutating ? "#975a16" : "#2b6cb0"} />
                </span>
              ))}
            </div>
          ))}
          <div style={{ fontSize: 12, color: "#718096" }}>
            Azul = consulta · laranja = escreve na plataforma. As mesmas ferramentas estão
            disponíveis a agentes externos pelo servidor MCP (ver README).
          </div>
        </div>
      )}

      {messages.length === 0 && (
        <div style={card}>
          <div style={{ fontSize: 13, color: "#718096", marginBottom: 8 }}>Sugestões</div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {SUGESTOES.map((s) => (
              <button key={s} style={{ ...btn, fontSize: 13 }} onClick={() => send(s)}>
                {s}
              </button>
            ))}
          </div>
        </div>
      )}

      {messages.map((m, i) => (
        <div
          key={i}
          style={{
            ...card,
            marginLeft: m.role === "user" ? 60 : 0,
            marginRight: m.role === "user" ? 0 : 60,
            background: m.error ? "#fff5f5" : m.role === "user" ? "#ebf8ff" : "#fff",
          }}
        >
          <div style={{ fontSize: 11, color: "#a0aec0", marginBottom: 4 }}>
            {m.role === "user" ? "Você" : "Assistente"}
          </div>
          <div style={{ whiteSpace: "pre-wrap", fontSize: 14, lineHeight: 1.5 }}>{m.content}</div>
          {m.steps && m.steps.length > 0 && (
            <details style={{ marginTop: 8, fontSize: 12 }}>
              <summary style={{ cursor: "pointer", color: "#4a5568" }}>
                Ferramentas consultadas ({m.steps.length})
              </summary>
              {m.steps.map((s, j) => (
                <div key={j} style={{ padding: "4px 0", borderTop: "1px solid #edf2f7" }}>
                  <span style={{ color: s.ok ? "#276749" : "#c53030", marginRight: 6 }}>
                    {s.ok ? "✓" : "✗"}
                  </span>
                  <code>{s.tool}</code>
                  <span style={{ color: "#718096" }}> {argsResumo(s.arguments)}</span>
                  {!s.ok && (
                    <div style={{ color: "#c53030", marginLeft: 18 }}>{s.result_preview.slice(0, 300)}</div>
                  )}
                </div>
              ))}
            </details>
          )}
        </div>
      ))}
      {loading && (
        <div style={{ ...card, marginRight: 60, color: "#718096", fontSize: 14 }}>
          Consultando a plataforma…
        </div>
      )}
      <div ref={endRef} />

      <form
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
        style={{ ...card, display: "flex", gap: 8 }}
      >
        <input
          style={{ ...input, flex: 1 }}
          placeholder="Pergunte sobre o andamento ou peça uma ação (ex.: cadastre a capability X no domain Y)"
          value={text}
          onChange={(e) => setText(e.target.value)}
          disabled={loading}
        />
        <button type="submit" style={btnPrimary} disabled={loading || !text.trim()}>
          Enviar
        </button>
      </form>
    </Shell>
  );
}
