"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { get, post } from "@/lib/api";
import { Badge, ConfidenceBar, Shell, btn, btnPrimary, card, input } from "@/components/ui";

const PROFILE_LABELS: Record<string, string> = {
  helpdesk_direct: "Resposta ao usuário final",
  helpdesk_copilot_n1: "Copiloto N1",
  helpdesk_copilot_n2: "Copiloto N2",
  helpdesk_copilot_n3: "Copiloto N3",
};

const ACTION_LABELS: Record<string, string> = {
  ANSWER: "Pode responder",
  ANSWER_WITH_CAUTION: "Responder com ressalva",
  ASK_CLARIFYING: "Coletar mais contexto",
  ESCALATE: "Escalar atendimento",
};

const ANSWERABILITY_COLORS: Record<string, string> = {
  SUPPORTED: "#276749",
  PARTIAL: "#b7791f",
  CONFLICTED: "#c53030",
  INSUFFICIENT: "#c53030",
};

function knowledgeText(item: any): string {
  if (item.kind === "message") return item.body?.meaning ?? item.body?.text ?? item.description;
  if (item.kind === "procedure") return item.body?.goal ?? item.description;
  return item.statement ?? item.description ?? item.title;
}

export default function HelpDeskPage() {
  const [question, setQuestion] = useState("");
  const [profile, setProfile] = useState("helpdesk_copilot_n1");
  const [domain, setDomain] = useState("");
  const [capability, setCapability] = useState("");
  const [contextText, setContextText] = useState("{}");
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [outcome, setOutcome] = useState("RESOLVED");
  const [helpful, setHelpful] = useState<string[]>([]);
  const [misleading, setMisleading] = useState<string[]>([]);
  const [correction, setCorrection] = useState("");
  const [ticketReference, setTicketReference] = useState("");
  const [feedbackStatus, setFeedbackStatus] = useState("");
  const [metrics, setMetrics] = useState<any>(null);
  const [gaps, setGaps] = useState<any[]>([]);
  const [freshness, setFreshness] = useState<any>(null);

  useEffect(() => {
    Promise.all([get("/helpdesk/metrics"), get("/helpdesk/gaps?limit=5"), get("/helpdesk/freshness?limit=5")])
      .then(([metricsData, gapsData, freshnessData]) => {
        setMetrics(metricsData);
        setGaps(gapsData);
        setFreshness(freshnessData);
      })
      .catch(() => {});
  }, []);

  const context = useMemo(() => {
    try {
      return JSON.parse(contextText || "{}");
    } catch {
      return null;
    }
  }, [contextText]);

  async function consult() {
    if (question.trim().length < 2) return;
    if (context === null || Array.isArray(context) || typeof context !== "object") {
      setError("O contexto precisa ser um objeto JSON válido.");
      return;
    }
    setLoading(true);
    setError("");
    setFeedbackStatus("");
    setHelpful([]);
    setMisleading([]);
    try {
      const data = await post("/helpdesk/context", {
        question: question.trim(),
        consumer_profile: profile,
        domain: domain.trim() || null,
        capability: capability.trim() || null,
        context,
      });
      setResult(data);
    } catch (e: any) {
      setError(e.message ?? "Falha ao consultar o conhecimento.");
    } finally {
      setLoading(false);
    }
  }

  function toggle(id: string, target: "helpful" | "misleading") {
    if (target === "helpful") {
      setHelpful((ids) => (ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]));
      setMisleading((ids) => ids.filter((x) => x !== id));
    } else {
      setMisleading((ids) =>
        ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id],
      );
      setHelpful((ids) => ids.filter((x) => x !== id));
    }
  }

  async function sendFeedback() {
    if (!result?.interaction_id) return;
    setFeedbackStatus("Enviando…");
    try {
      const feedback = await post(`/helpdesk/interactions/${result.interaction_id}/feedback`, {
        idempotency_key: `ui-${result.interaction_id}-${outcome}`,
        outcome,
        helpful_atom_ids: helpful,
        misleading_atom_ids: misleading,
        missing_information: outcome === "UNKNOWN" ? correction.trim() || null : null,
        correction: outcome === "INCORRECT" ? correction.trim() || null : null,
        ticket_reference: ticketReference.trim() || null,
      });
      setFeedbackStatus(
        feedback.candidate_id
          ? `Feedback registrado; correção criada como candidato ${feedback.candidate_id}.`
          : "Feedback registrado.",
      );
    } catch (e: any) {
      setFeedbackStatus(e.message ?? "Não foi possível registrar o feedback.");
    }
  }

  async function copyGuidance() {
    const guidance = (result?.knowledge ?? [])
      .map((item: any) => {
        const steps = (item.body?.steps ?? []).map((step: any) => `${step.order}. ${step.action}`);
        return [`${item.title} [${item.label}]`, knowledgeText(item), ...steps].filter(Boolean).join("\n");
      })
      .join("\n\n");
    await navigator.clipboard.writeText(guidance);
    setFeedbackStatus("Orientação funcional copiada sem metadados internos.");
  }

  return (
    <Shell title="Assistência Semântica para Help Desk">
      {metrics && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10, marginBottom: 12 }}>
          {[
            ["Interações", metrics.interactions],
            ["Feedbacks", metrics.feedback],
            ["Lacunas recentes", gaps.length],
            ["Conhecimento stale", freshness?.by_freshness?.STALE ?? 0],
          ].map(([label, value]) => (
            <div key={String(label)} style={{ ...card, marginBottom: 0 }}>
              <div style={{ color: "#718096", fontSize: 12 }}>{label}</div>
              <strong style={{ fontSize: 22 }}>{value}</strong>
            </div>
          ))}
        </div>
      )}
      <div style={{ ...card, display: "grid", gap: 12 }}>
        <label>
          <div style={{ fontWeight: 600, marginBottom: 5 }}>Dúvida ou mensagem apresentada</div>
          <textarea
            style={{ ...input, width: "100%", minHeight: 82, resize: "vertical" }}
            placeholder="Ex.: O que significa o erro CAN-014 e como orientar o cliente?"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
          />
        </label>
        <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", gap: 10 }}>
          <label>
            <div style={{ fontSize: 13, marginBottom: 4 }}>Perfil consumidor</div>
            <select style={{ ...input, width: "100%" }} value={profile} onChange={(e) => setProfile(e.target.value)}>
              {Object.entries(PROFILE_LABELS).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </label>
          <label>
            <div style={{ fontSize: 13, marginBottom: 4 }}>Domain (opcional)</div>
            <input style={{ ...input, width: "100%" }} value={domain} onChange={(e) => setDomain(e.target.value)} placeholder="faturamento" />
          </label>
          <label>
            <div style={{ fontSize: 13, marginBottom: 4 }}>Capability (opcional)</div>
            <input style={{ ...input, width: "100%" }} value={capability} onChange={(e) => setCapability(e.target.value)} placeholder="cancelamento" />
          </label>
        </div>
        <details>
          <summary style={{ cursor: "pointer", fontWeight: 600 }}>Contexto estruturado</summary>
          <p style={{ color: "#718096", fontSize: 13 }}>
            Informe apenas dados não sensíveis que mudem a regra: versão, tenant, estado do documento,
            tela e códigos de erro.
          </p>
          <textarea
            style={{ ...input, width: "100%", minHeight: 95, fontFamily: "monospace" }}
            value={contextText}
            onChange={(e) => setContextText(e.target.value)}
          />
        </details>
        <div>
          <button style={btnPrimary} onClick={consult} disabled={loading || question.trim().length < 2}>
            {loading ? "Consultando…" : "Montar contexto confiável"}
          </button>
        </div>
        {error && <div style={{ color: "#c53030", fontWeight: 600 }}>{error}</div>}
      </div>

      {result && (
        <>
          <div style={{ ...card, borderLeft: `5px solid ${ANSWERABILITY_COLORS[result.answerability] ?? "#718096"}` }}>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <Badge text={result.answerability} color={ANSWERABILITY_COLORS[result.answerability]} />
              <Badge text={ACTION_LABELS[result.recommended_action] ?? result.recommended_action} color={ANSWERABILITY_COLORS[result.answerability]} />
              <span style={{ color: "#718096", fontSize: 12, marginLeft: "auto" }}>
                snapshot {result.knowledge_snapshot?.database_revision ?? "—"} · {result.budget?.estimated_tokens ?? 0}/{result.budget?.maximum_tokens ?? 0} tokens
              </span>
            </div>
            <p style={{ marginBottom: 0 }}>{result.reason}</p>
          </div>

          {result.clarifying_questions?.length > 0 && (
            <div style={{ ...card, background: "#fffaf0" }}>
              <h3 style={{ marginTop: 0 }}>Antes de responder, confirme</h3>
              <ul>{result.clarifying_questions.map((q: string) => <li key={q}>{q}</li>)}</ul>
            </div>
          )}

          <h2 style={{ fontSize: 18 }}>Conhecimento recuperado ({result.knowledge?.length ?? 0})</h2>
          <button style={{ ...btn, marginBottom: 12 }} onClick={copyGuidance}>
            Copiar orientação funcional
          </button>
          {result.knowledge?.map((item: any) => (
            <div key={item.id} style={card}>
              <div style={{ display: "flex", gap: 7, alignItems: "center", flexWrap: "wrap" }}>
                <Badge text={item.label} color={item.label === "CANONICAL" ? "#276749" : "#b7791f"} />
                <Badge text={item.kind} />
                <Badge text={`freshness ${item.freshness}`} color={item.freshness === "STALE" ? "#c53030" : "#718096"} />
                <span style={{ flex: 1 }} />
                <ConfidenceBar value={item.confidence} />
              </div>
              <h3 style={{ marginBottom: 5 }}>
                <Link href={`/atom/${encodeURIComponent(item.id)}`} style={{ color: "#2b6cb0", textDecoration: "none" }}>
                  {item.title}
                </Link>
              </h3>
              <p style={{ marginTop: 0 }}>{knowledgeText(item)}</p>
              {item.kind === "procedure" && item.body?.steps?.length > 0 && (
                <ol>
                  {item.body.steps.map((step: any) => (
                    <li key={step.order} style={{ marginBottom: 7 }}>
                      {step.action}{step.expected_result ? <span style={{ color: "#718096" }}> — {step.expected_result}</span> : null}
                    </li>
                  ))}
                </ol>
              )}
              {item.evidence_summaries?.length > 0 && (
                <div style={{ background: "#f7fafc", padding: 10, borderRadius: 8, fontSize: 13 }}>
                  <strong>Evidência:</strong> {item.evidence_summaries.join(" · ")}
                </div>
              )}
              <div style={{ display: "flex", gap: 7, marginTop: 10 }}>
                <button style={{ ...btn, background: helpful.includes(item.id) ? "#c6f6d5" : undefined }} onClick={() => toggle(item.id, "helpful")}>Útil</button>
                <button style={{ ...btn, background: misleading.includes(item.id) ? "#fed7d7" : undefined }} onClick={() => toggle(item.id, "misleading")}>Enganoso</button>
              </div>
            </div>
          ))}

          {result.open_questions?.length > 0 && (
            <div style={{ ...card, background: "#fffaf0" }}>
              <h3 style={{ marginTop: 0 }}>Lacunas conhecidas</h3>
              <ul>{result.open_questions.map((q: any) => <li key={q.id}>{q.title}</li>)}</ul>
            </div>
          )}

          <div style={card}>
            <h3 style={{ marginTop: 0 }}>Resultado do atendimento</h3>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
              <select style={input} value={outcome} onChange={(e) => setOutcome(e.target.value)}>
                <option value="RESOLVED">Resolvido</option>
                <option value="PARTIALLY_RESOLVED">Parcialmente resolvido</option>
                <option value="ESCALATED">Escalado</option>
                <option value="INCORRECT">Conhecimento incorreto</option>
                <option value="UNKNOWN">Conhecimento ausente</option>
              </select>
              <button style={btnPrimary} onClick={sendFeedback}>Registrar feedback</button>
            </div>
            <textarea
              style={{ ...input, width: "100%", minHeight: 70 }}
              value={correction}
              onChange={(e) => setCorrection(e.target.value)}
              placeholder="Correção ou informação ausente (nunca altera conhecimento canônico automaticamente)"
            />
            <input
              style={{ ...input, width: "100%", marginTop: 8 }}
              value={ticketReference}
              onChange={(e) => setTicketReference(e.target.value)}
              placeholder="Referência externa mascarada do ticket (opcional)"
            />
            {feedbackStatus && <p style={{ marginBottom: 0 }}>{feedbackStatus}</p>}
          </div>
        </>
      )}
    </Shell>
  );
}
