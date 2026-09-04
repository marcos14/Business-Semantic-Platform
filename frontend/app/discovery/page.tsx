"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { get, post } from "@/lib/api";
import { Badge, Shell, btn, btnPrimary, card, input } from "@/components/ui";

const REFRESH_MS = 5000;

const JOB_STATUS: Record<string, { label: string; color: string }> = {
  todo: { label: "pendente", color: "#975a16" },
  doing: { label: "executando", color: "#2b6cb0" },
  succeeded: { label: "concluído", color: "#276749" },
  failed: { label: "falhou", color: "#c53030" },
  cancelled: { label: "cancelado", color: "#718096" },
  aborting: { label: "abortando", color: "#c05621" },
  aborted: { label: "abortado", color: "#9b2c2c" },
};

const RUN_STATUS: Record<string, { label: string; color: string }> = {
  running: { label: "executando", color: "#2b6cb0" },
  succeeded: { label: "sucesso", color: "#276749" },
  failed: { label: "falhou", color: "#c53030" },
  limit: { label: "limite de franquia", color: "#975a16" },
  auth_failed: { label: "falha de autenticação", color: "#c53030" },
};

const WORKER_CMD = "uv run procrastinate --app=app.jobs.job_app worker --queues discovery";

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function fmtDuration(startIso: string, endIso: string | null, now: number): string {
  const ms = (endIso ? new Date(endIso).getTime() : now) - new Date(startIso).getTime();
  if (ms < 0) return "—";
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}min ${s % 60}s`;
  return `${Math.floor(m / 60)}h ${m % 60}min`;
}

function fmtAge(iso: string | null, now: number): string {
  if (!iso) return "";
  const s = Math.floor((now - new Date(iso).getTime()) / 1000);
  if (s < 60) return `há ${s}s`;
  if (s < 3600) return `há ${Math.floor(s / 60)}min`;
  return `há ${Math.floor(s / 3600)}h`;
}

function agentLabel(r: any): string {
  if (r.agent === "inventory") return "inventário";
  if (r.target_file) return "dirigido";
  return r.agent;
}

function Kpi({ label, value, color }: { label: string; value: string | number; color?: string }) {
  return (
    <div style={{ ...card, marginBottom: 0, padding: "12px 16px", minWidth: 130, flex: 1 }}>
      <div style={{ fontSize: 12, color: "#718096" }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: color ?? "#1a202c" }}>{value}</div>
    </div>
  );
}

function Progresso({ done, total, running }: { done: number; total: number; running: number }) {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  const pctRun = total > 0 ? Math.round((running / total) * 100) : 0;
  return (
    <div title={`${done}/${total} concluído(s)`} style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div style={{ flex: 1, height: 10, background: "#e2e8f0", borderRadius: 5, overflow: "hidden", display: "flex" }}>
        <div style={{ width: `${pct}%`, background: "#276749" }} />
        <div style={{ width: `${pctRun}%`, background: "#2b6cb0" }} />
      </div>
      <span style={{ fontSize: 12, color: "#4a5568", whiteSpace: "nowrap" }}>
        {done}/{total} · {pct}%
      </span>
    </div>
  );
}

export default function DiscoveryPage() {
  const [queue, setQueue] = useState<any | null>(null);
  const [runs, setRuns] = useState<any[]>([]);
  const [batches, setBatches] = useState<any[]>([]);
  const [sources, setSources] = useState<Record<string, any>>({});
  const [admin, setAdmin] = useState(false);
  const [auto, setAuto] = useState(true);
  const [now, setNow] = useState(() => Date.now());
  const [ultimo, setUltimo] = useState<number | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [filtroStatus, setFiltroStatus] = useState("");
  const [filtroSource, setFiltroSource] = useState("");
  const [filtroBatch, setFiltroBatch] = useState("");
  const [mostrarConcluidos, setMostrarConcluidos] = useState(false);
  const [ocultarBloqueados, setOcultarBloqueados] = useState(true);
  const [mostrarCampanhasAntigas, setMostrarCampanhasAntigas] = useState(false);
  const [aberto, setAberto] = useState<string | null>(null);

  useEffect(() => {
    try {
      const p = new URLSearchParams(window.location.search);
      if (p.get("source")) setFiltroSource(p.get("source") as string);
      if (p.get("batch")) setFiltroBatch(p.get("batch") as string);
    } catch {
      /* ignore */
    }
  }, []);

  const reload = useCallback(async () => {
    try {
      const [q, r, b] = await Promise.all([
        get("/discovery/queue"),
        get(`/discovery/runs?limit=200${ocultarBloqueados ? "&exclude=limit,auth_failed" : ""}`),
        get("/discovery/batches"),
      ]);
      setQueue(q);
      setRuns(r);
      setBatches(b);
      setErro(null);
      setUltimo(Date.now());
    } catch (e: any) {
      setErro(e.message);
    }
  }, [ocultarBloqueados]);

  useEffect(() => {
    get("/sources")
      .then((list: any[]) => setSources(Object.fromEntries(list.map((s) => [s.id, s]))))
      .catch(() => {});
    get("/admin/domains").then(() => setAdmin(true)).catch(() => setAdmin(false));
  }, []);

  useEffect(() => {
    reload();
    if (!auto) return;
    const t = setInterval(reload, REFRESH_MS);
    return () => clearInterval(t);
  }, [auto, reload]);

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const jobs: any[] = queue?.jobs ?? [];
  const jobsVisiveis = jobs.filter((j) => mostrarConcluidos || j.status === "todo" || j.status === "doing");
  const pendentes = queue?.pending ?? 0;
  const executando = queue?.running ?? 0;
  const workersVivos = queue?.workers_alive ?? 0;
  const semWorker = pendentes > 0 && workersVivos === 0;

  const campanhasVisiveis = batches.filter((b) => mostrarCampanhasAntigas || b.active || filtroBatch === b.batch_id);

  const runsVisiveis = useMemo(
    () =>
      runs.filter(
        (r) =>
          (!filtroStatus || r.status === filtroStatus) &&
          (!filtroSource || r.source_id === filtroSource) &&
          (!filtroBatch || r.batch_id === filtroBatch),
      ),
    [runs, filtroStatus, filtroSource, filtroBatch],
  );
  const custoTotal = runs.reduce((acc, r) => acc + (r.cost_usd || 0), 0);
  const emExecucao = runs.filter((r) => r.status === "running").length;

  const cancelar = async (id: number) => {
    try {
      await post(`/discovery/queue/${id}/cancel`);
      setMsg(`Job ${id} cancelado.`);
      reload();
    } catch (e: any) {
      setErro(e.message);
    }
  };

  const cancelarCampanha = async (b: any) => {
    const alvos = jobs.filter((j) => j.status === "todo" && j.args?.batch_id === b.batch_id);
    if (alvos.length === 0) return setErro("A fila carregada não mostra jobs pendentes desta campanha (a lista é limitada aos 50 mais recentes).");
    let n = 0;
    for (const j of alvos) {
      try {
        await post(`/discovery/queue/${j.id}/cancel`);
        n++;
      } catch {
        /* segue */
      }
    }
    setMsg(`${n} job(s) pendente(s) da campanha cancelado(s). Os já em execução terminam normalmente.`);
    reload();
  };

  return (
    <Shell title="Discovery · campanhas, fila e runs">
      {/* barra de controle */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12, flexWrap: "wrap" }}>
        <label style={{ fontSize: 13, display: "flex", alignItems: "center", gap: 6 }}>
          <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
          atualizar a cada {REFRESH_MS / 1000}s
        </label>
        <button style={btn} onClick={reload}>Atualizar agora</button>
        <span style={{ fontSize: 12, color: "#718096" }}>
          {ultimo ? `atualizado ${fmtAge(new Date(ultimo).toISOString(), now)}` : "carregando…"}
        </span>
        <span style={{ flex: 1 }} />
        <a href="/sources" style={{ fontSize: 13, color: "#2b6cb0" }}>inventariar / iniciar campanha em Sources →</a>
      </div>

      {erro && (
        <div style={{ ...card, background: "#fff5f5", border: "1px solid #fc8181" }}>
          {erro}{" "}
          <a style={{ cursor: "pointer", color: "#2b6cb0" }} onClick={() => setErro(null)}>fechar</a>
        </div>
      )}
      {msg && (
        <div style={{ ...card, background: "#f0fff4", border: "1px solid #68d391" }}>
          {msg}{" "}
          <a style={{ cursor: "pointer", color: "#2b6cb0" }} onClick={() => setMsg(null)}>fechar</a>
        </div>
      )}

      {/* KPIs */}
      <div style={{ display: "flex", gap: 10, marginBottom: 12, flexWrap: "wrap" }}>
        <Kpi label="jobs pendentes" value={pendentes} color={pendentes > 0 ? "#975a16" : undefined} />
        <Kpi label="jobs executando" value={executando} color={executando > 0 ? "#2b6cb0" : undefined} />
        <Kpi label="workers ativos" value={workersVivos} color={workersVivos === 0 ? "#c53030" : "#276749"} />
        <Kpi label="runs em execução" value={emExecucao} />
        <Kpi label="custo acumulado" value={`US$ ${custoTotal.toFixed(2)}`} />
      </div>

      {queue?.schema_missing && (
        <div style={{ ...card, background: "#fffaf0", border: "1px solid #f6ad55" }}>
          O schema do Procrastinate ainda não existe no banco: nenhum worker subiu até agora.
          Suba o serviço <code>worker</code> do compose ou rode o worker no host.
        </div>
      )}
      {semWorker && (
        <div style={{ ...card, background: "#fffaf0", border: "1px solid #f6ad55" }}>
          <strong>Há job pendente e nenhum worker ativo.</strong> A fila <code>discovery</code> só é
          consumida por um worker no host, onde o CLI <code>claude</code> está logado:
          <pre style={{ margin: "8px 0 0", padding: 8, background: "#1a202c", color: "#e2e8f0", borderRadius: 6, fontSize: 12, overflowX: "auto" }}>
            cd backend{"\n"}{WORKER_CMD}
          </pre>
        </div>
      )}
      {queue?.scheduled_future > 0 && (
        <div style={{ ...card, background: "#fffaf0", border: "1px solid #f6ad55" }}>
          <strong>{queue.scheduled_future} job(s) aguardando</strong> até{" "}
          {fmtDate(queue.next_scheduled_at)}, o horário de reset da franquia informado pelo harness.
          Trocou de conta do Claude? Libere-os para rodar agora.
          {admin && (
            <button
              style={{ ...btnPrimary, marginLeft: 10, padding: "6px 12px", fontSize: 13 }}
              onClick={async () => {
                try {
                  const r = await post("/discovery/queue/release", {});
                  setMsg(`${r.released} job(s) liberado(s) para execução imediata.`);
                  reload();
                } catch (e: any) {
                  setErro(e.message);
                }
              }}
            >
              Liberar agora
            </button>
          )}
        </div>
      )}
      {!semWorker && pendentes > 0 && workersVivos > 0 && (
        <div style={{ ...card, background: "#ebf8ff", border: "1px solid #90cdf4", fontSize: 13 }}>
          Há {workersVivos} worker(s) com heartbeat, mas o heartbeat não informa a fila. Se o job
          continuar pendente, confirme que o worker do host foi iniciado com <code>--queues discovery</code>.
        </div>
      )}

      {/* Campanhas */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "18px 0 8px" }}>
        <h2 style={{ fontSize: 18, margin: 0, flex: 1 }}>
          Campanhas{" "}
          <span style={{ fontSize: 13, color: "#718096", fontWeight: 400 }}>
            inventário em lotes · discovery dirigido arquivo a arquivo
          </span>
        </h2>
        <label style={{ fontSize: 13, display: "flex", alignItems: "center", gap: 6 }}>
          <input type="checkbox" checked={mostrarCampanhasAntigas} onChange={(e) => setMostrarCampanhasAntigas(e.target.checked)} />
          mostrar concluídas
        </label>
      </div>
      {campanhasVisiveis.length === 0 && (
        <div style={card}>
          <p style={{ color: "#718096", margin: 0, fontSize: 13 }}>
            {batches.length === 0 ? "Nenhuma campanha ainda." : "Nenhuma campanha ativa."}
          </p>
        </div>
      )}
      {campanhasVisiveis.map((b) => {
        const src = sources[b.source_id];
        const selecionada = filtroBatch === b.batch_id;
        return (
          <div key={b.batch_id} style={{ ...card, border: selecionada ? "2px solid #2b6cb0" : undefined }}>
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <Badge text={b.agent === "inventory" ? "inventário" : "dirigido"} color={b.agent === "inventory" ? "#6b46c1" : "#2b6cb0"} />
              <strong>{src?.name ?? (b.source_id ? String(b.source_id).slice(0, 8) : "—")}</strong>
              <span style={{ color: "#718096", fontSize: 13 }}>
                {b.domain}{b.capability ? `/${b.capability}` : ""}
              </span>
              {b.active ? <Badge text="ativa" color="#2b6cb0" /> : <Badge text="concluída" color="#276749" />}
              <span style={{ flex: 1 }} />
              <span style={{ fontSize: 12, color: "#718096" }} title={b.batch_id}>
                início {fmtDate(b.started_at)}
              </span>
              <button style={btn} onClick={() => setFiltroBatch(selecionada ? "" : b.batch_id)}>
                {selecionada ? "Todos os runs" : "Ver runs"}
              </button>
              {admin && b.pending_jobs > 0 && (
                <button style={btn} onClick={() => cancelarCampanha(b)} title="cancela os jobs ainda pendentes desta campanha">
                  Cancelar pendentes
                </button>
              )}
            </div>
            <div style={{ marginTop: 8 }}>
              <Progresso done={b.done} total={b.total} running={b.running + b.doing_jobs} />
            </div>
            <div style={{ fontSize: 13, color: "#4a5568", marginTop: 6, display: "flex", gap: 14, flexWrap: "wrap" }}>
              <span>{b.pending_jobs} na fila</span>
              <span>{b.running} executando</span>
              <span style={{ color: "#276749" }}>{b.succeeded} ok</span>
              {b.failed > 0 && <span style={{ color: "#c53030" }}>{b.failed} falhou</span>}
              {b.blocked > 0 && (
                <span style={{ color: "#975a16" }} title="tentativas que bateram na franquia ou em falha de login; o job voltou para a fila e será refeito no reset">
                  {b.blocked} tentativa(s) bloqueada(s) por franquia
                </span>
              )}
              <span>
                {b.agent === "inventory"
                  ? `${b.candidates} arquivo(s) inventariado(s) · ${b.questions} sugestão(ões)`
                  : `${b.candidates} candidates · ${b.questions} questions · ${b.evidence_rejected} evidência(s) inválida(s)`}
              </span>
              <strong>US$ {b.cost_usd.toFixed(2)}</strong>
            </div>
          </div>
        );
      })}

      {/* Fila */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "18px 0 8px" }}>
        <h2 style={{ fontSize: 18, margin: 0, flex: 1 }}>
          Fila <code style={{ fontSize: 13, color: "#718096" }}>discovery</code>
        </h2>
        <label style={{ fontSize: 13, display: "flex", alignItems: "center", gap: 6 }}>
          <input type="checkbox" checked={mostrarConcluidos} onChange={(e) => setMostrarConcluidos(e.target.checked)} />
          mostrar concluídos
        </label>
      </div>
      <div style={card}>
        {jobsVisiveis.length === 0 ? (
          <p style={{ color: "#718096", margin: 0, fontSize: 13 }}>
            {jobs.length === 0 ? "Nenhum job na fila." : "Nenhum job pendente ou em execução."}
          </p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", fontSize: 13, borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ color: "#718096", textAlign: "left" }}>
                  <th style={th}>#</th>
                  <th style={th}>status</th>
                  <th style={th}>tipo</th>
                  <th style={th}>source</th>
                  <th style={th}>domain / capability</th>
                  <th style={th}>alvo</th>
                  <th style={th}>budget</th>
                  <th style={th}>criado</th>
                  <th style={th}>agendado p/</th>
                  <th style={th}>tent.</th>
                  {admin && <th style={th}></th>}
                </tr>
              </thead>
              <tbody>
                {jobsVisiveis.map((j) => {
                  const a = j.args ?? {};
                  const st = JOB_STATUS[j.status] ?? { label: j.status, color: "#718096" };
                  const src = sources[a.source_id];
                  const tipo = j.task === "jobs.run_inventory" ? "inventário" : j.task === "jobs.run_directed" ? (a.is_followup ? "dirigido (follow-up)" : "dirigido") : a.agent ?? j.task;
                  const alvo = j.task === "jobs.run_inventory"
                    ? `${(a.files ?? []).length} arquivo(s)`
                    : j.task === "jobs.run_directed"
                      ? `${a.file}${a.start_line && a.end_line ? ` [${a.start_line}-${a.end_line}]` : ""}`
                      : a.scope_hint ?? "—";
                  return (
                    <tr key={j.id} style={{ borderTop: "1px solid #edf2f7" }}>
                      <td style={td}>{j.id}</td>
                      <td style={td}><Badge text={st.label} color={st.color} /></td>
                      <td style={td}>{tipo}</td>
                      <td style={td} title={a.source_id}>{src?.name ?? (a.source_id ? a.source_id.slice(0, 8) : "—")}</td>
                      <td style={td}>{a.domain}{a.capability ? ` / ${a.capability}` : ""}</td>
                      <td style={{ ...td, fontFamily: "monospace", fontSize: 12, maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={alvo}>{alvo}</td>
                      <td style={td}>{a.budget_usd != null ? `US$ ${Number(a.budget_usd).toFixed(2)}` : "—"}</td>
                      <td style={td} title={j.created_at ?? ""}>{fmtDate(j.created_at)} <span style={{ color: "#a0aec0" }}>{fmtAge(j.created_at, now)}</span></td>
                      <td style={td}>{j.scheduled_at ? fmtDate(j.scheduled_at) : "—"}</td>
                      <td style={td}>{j.attempts}</td>
                      {admin && (
                        <td style={td}>
                          {j.status === "todo" && (
                            <button style={{ ...btn, padding: "4px 10px", fontSize: 12 }} onClick={() => cancelar(j.id)}>
                              Cancelar
                            </button>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {queue?.workers?.length > 0 && (
          <div style={{ fontSize: 12, color: "#718096", marginTop: 10 }}>
            workers:{" "}
            {queue.workers.map((w: any) => (
              <span key={w.id} style={{ marginRight: 10 }}>
                #{w.id}{" "}
                <span style={{ color: w.alive ? "#276749" : "#c53030" }}>
                  {w.alive ? "ativo" : "sem heartbeat"}
                </span>{" "}
                ({fmtAge(w.last_heartbeat, now)})
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Runs */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "18px 0 8px", flexWrap: "wrap" }}>
        <h2 style={{ fontSize: 18, margin: 0, flex: 1 }}>
          Runs{" "}
          <span style={{ fontSize: 13, color: "#718096", fontWeight: 400 }}>
            {runsVisiveis.length} de {runs.length}
            {filtroBatch && (
              <>
                {" "}· campanha {filtroBatch.slice(0, 8)}{" "}
                <a style={{ cursor: "pointer", color: "#2b6cb0" }} onClick={() => setFiltroBatch("")}>limpar</a>
              </>
            )}
          </span>
        </h2>
        <select style={input} value={filtroSource} onChange={(e) => setFiltroSource(e.target.value)}>
          <option value="">todas as sources</option>
          {Object.values(sources).map((s: any) => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
        </select>
        <select style={input} value={filtroStatus} onChange={(e) => setFiltroStatus(e.target.value)}>
          <option value="">todos os status</option>
          {Object.entries(RUN_STATUS).map(([k, v]) => (
            <option key={k} value={k}>{v.label}</option>
          ))}
        </select>
        <label style={{ fontSize: 13, display: "flex", alignItems: "center", gap: 6 }} title="runs que bateram na franquia/login não concluem nada: o job é reenfileirado">
          <input type="checkbox" checked={ocultarBloqueados} onChange={(e) => setOcultarBloqueados(e.target.checked)} />
          ocultar bloqueados por franquia
        </label>
      </div>

      {runsVisiveis.length === 0 && (
        <p style={{ color: "#718096", fontSize: 13 }}>
          Nenhum run registrado. O registro nasce quando o worker pega o job da fila.
        </p>
      )}
      {runsVisiveis.map((r) => {
        const st = RUN_STATUS[r.status] ?? { label: r.status, color: "#718096" };
        const src = sources[r.source_id];
        const isOpen = aberto === r.id;
        return (
          <div key={r.id} style={{ ...card, borderLeft: `4px solid ${st.color}` }}>
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <Badge text={st.label} color={st.color} />
              <Badge text={agentLabel(r)} color={r.agent === "inventory" ? "#6b46c1" : undefined} />
              {r.line_range?.startsWith("f:") && <Badge text="follow-up" color="#975a16" />}
              <strong>{src?.name ?? r.source_id.slice(0, 8)}</strong>
              <span style={{ color: "#718096", fontSize: 13 }}>
                {r.domain}{r.capability ? `/${r.capability}` : ""}
              </span>
              {r.target_file && (
                <span style={{ fontFamily: "monospace", fontSize: 12, color: "#4a5568" }} title={r.target_file}>
                  {r.target_file}{r.line_range ? ` [${r.line_range.replace(/^f:/, "")}]` : ""}
                </span>
              )}
              <span style={{ flex: 1 }} />
              <span style={{ fontSize: 13, color: "#718096" }}>
                {fmtDate(r.started_at)} · {fmtDuration(r.started_at, r.finished_at, now)}
                {r.status === "running" && <span style={{ color: "#2b6cb0" }}> ⏳</span>}
              </span>
              <strong style={{ fontSize: 13 }}>US$ {(r.cost_usd || 0).toFixed(2)}</strong>
              <button style={btn} onClick={() => setAberto(isOpen ? null : r.id)}>
                {isOpen ? "Fechar" : "Detalhes"}
              </button>
            </div>
            <div style={{ fontSize: 13, color: "#4a5568", marginTop: 6 }}>
              {r.agent === "inventory" ? (
                <>
                  {r.candidates_created} arquivo(s) inventariado(s) · {r.candidates_rejected} não classificado(s) ·{" "}
                  {r.questions_created} capability(ies) sugerida(s) · {r.num_turns} turno(s)
                </>
              ) : (
                <>
                  {r.candidates_created} candidates · {r.questions_created} questions ·{" "}
                  {r.reinforcements > 0 && <span style={{ color: "#276749" }} title="evidências adicionadas a candidates já existentes (fonte independente)">{r.reinforcements} reforço(s) · </span>}
                  {r.candidates_rejected} rejeitados · {r.duplicates_skipped} duplicados ·{" "}
                  {r.potential_duplicates > 0 && <>{r.potential_duplicates} potencial(is) duplicata(s) · </>}
                  {r.systemic_created > 0 && <span title="comportamentos objetivos (validação de entrada, interface, infraestrutura): gravados e aprovados sem revisão humana">{r.systemic_created} sistêmico(s) · </span>}
                  {r.evidence_rejected} evidência(s) inválida(s) · {r.num_turns} turno(s)
                </>
              )}
              {r.workspace_clean === "no" && <> · <Badge text="workspace sujo!" color="#c53030" /></>}
            </div>
            {r.error && (
              <div style={{ color: "#c53030", fontSize: 13, marginTop: 6, whiteSpace: "pre-wrap" }}>
                {String(r.error).slice(0, isOpen ? 4000 : 300)}
              </div>
            )}
            {isOpen && (
              <table style={{ fontSize: 12, marginTop: 10, borderCollapse: "collapse" }}>
                <tbody>
                  {[
                    ["run id", r.id],
                    ["campanha", r.batch_id],
                    ["arquivo alvo", r.target_file],
                    ["faixa", r.line_range],
                    ["commit analisado", r.commit],
                    ["modelo / effort", `${r.model} / ${r.effort}`],
                    ["cli", r.cli_version],
                    ["prompt hash", r.prompt_hash],
                    ["session", r.session_id],
                    ["log (.jsonl no host do worker)", r.log_path],
                    ["disparado por", r.created_by],
                    ["início", fmtDate(r.started_at)],
                    ["fim", fmtDate(r.finished_at)],
                    ["potenciais duplicatas", r.potential_duplicates],
                  ].map(([k, v]) => (
                    <tr key={String(k)}>
                      <td style={{ ...td, color: "#718096", paddingRight: 14 }}>{k}</td>
                      <td style={{ ...td, fontFamily: "monospace", wordBreak: "break-all" }}>{v ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        );
      })}
    </Shell>
  );
}

const th = { padding: "4px 6px", fontWeight: 600, whiteSpace: "nowrap" as const };
const td = { padding: "6px", verticalAlign: "top" as const };
