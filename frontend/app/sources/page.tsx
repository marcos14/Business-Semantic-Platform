"use client";

import { useCallback, useEffect, useState } from "react";
import { get, post } from "@/lib/api";
import { Badge, Shell, btn, btnPrimary, card, input } from "@/components/ui";

const TIPOS = [
  "source_code",
  "automated_test",
  "documentation",
  "database_schema",
  "api",
  "configuration",
  "runtime_trace",
  "manual",
  "ticket",
  "human_input",
];

const RUN_STATUS: Record<string, string> = {
  running: "#2b6cb0",
  succeeded: "#276749",
  failed: "#c53030",
  limit: "#975a16",
  auth_failed: "#c53030",
};

function slugify(s: string): string {
  return s
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 100);
}

function NovaSource({ domains, onCriada, onErro }: any) {
  const [aberto, setAberto] = useState(false);
  const [f, setF] = useState<any>({ type: "source_code", name: "", repository: "", branch: "", commit: "", location: "", domain_slug: "" });
  const set = (k: string, v: string) => setF({ ...f, [k]: v });

  if (!aberto)
    return (
      <button style={btnPrimary} onClick={() => setAberto(true)}>
        + Registrar source (§10)
      </button>
    );
  return (
    <div style={{ ...card, border: "2px solid #2b6cb0" }}>
      <h3 style={{ marginTop: 0 }}>Nova source</h3>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <select style={input} value={f.type} onChange={(e) => set("type", e.target.value)}>
          {TIPOS.map((t) => (
            <option key={t}>{t}</option>
          ))}
        </select>
        <input style={{ ...input, flex: 1, minWidth: 160 }} placeholder="Nome *" value={f.name} onChange={(e) => set("name", e.target.value)} />
        <select style={input} value={f.domain_slug} onChange={(e) => set("domain_slug", e.target.value)}>
          <option value="">domain (opcional)</option>
          {domains.map((d: any) => (
            <option key={d.slug} value={d.slug}>{d.slug}</option>
          ))}
        </select>
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
        <input style={{ ...input, flex: 2, minWidth: 220 }} placeholder="Repositório (caminho local; pode ser um subdiretório do repo git)" value={f.repository} onChange={(e) => set("repository", e.target.value)} />
        <input style={{ ...input, width: 120 }} placeholder="branch" value={f.branch} onChange={(e) => set("branch", e.target.value)} />
        <input style={{ ...input, width: 130 }} placeholder="commit (opcional)" value={f.commit} onChange={(e) => set("commit", e.target.value)} />
      </div>
      <input style={{ ...input, width: "100%", marginTop: 8 }} placeholder="Location (para fontes não-git: caminho de docs, URL de API…)" value={f.location} onChange={(e) => set("location", e.target.value)} />
      <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
        <button
          style={btnPrimary}
          onClick={async () => {
            try {
              const body: any = { type: f.type, name: f.name };
              for (const k of ["repository", "branch", "commit", "location", "domain_slug"])
                if (f[k]) body[k] = f[k];
              await post("/sources", body);
              setAberto(false);
              setF({ ...f, name: "", repository: "", branch: "", commit: "", location: "" });
              onCriada();
            } catch (e: any) {
              onErro(e.message);
            }
          }}
        >
          Salvar
        </button>
        <button style={btn} onClick={() => setAberto(false)}>Cancelar</button>
      </div>
    </div>
  );
}

const painel = { marginTop: 10, padding: 12, background: "#f7fafc", borderRadius: 8 };
const dica = { fontSize: 12, color: "#718096" };

/** Passo 1: inventário — liga cada arquivo-fonte às capabilities do domain. */
function Inventariar({ source, domains, capabilities, onOk, onErro }: any) {
  const [f, setF] = useState<any>({ domain: source.domain_slug ?? "", prefix: "", max_files: "", only_missing: true, budget_usd: 3 });
  const caps = capabilities.filter((c: any) => c.domain_slug === f.domain);
  return (
    <div style={painel}>
      <p style={{ ...dica, marginTop: 0 }}>
        Enumera os arquivos-fonte da source (por extensão, sem binários), monta lotes que cabem no prompt
        e pede ao harness, por lote, um resumo de negócio de cada arquivo e a ligação com as capabilities
        do domain. Capabilities que ele encontrar sem cadastro viram sugestões abaixo.
      </p>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <select style={input} value={f.domain} onChange={(e) => setF({ ...f, domain: e.target.value })}>
          <option value="">domain *</option>
          {domains.map((d: any) => (
            <option key={d.slug} value={d.slug}>{d.slug}</option>
          ))}
        </select>
        <input style={{ ...input, width: 180 }} placeholder="prefixo (ex.: ADM001/)" value={f.prefix} onChange={(e) => setF({ ...f, prefix: e.target.value })} title="só arquivos sob este caminho" />
        <input style={{ ...input, width: 110 }} type="number" min={1} placeholder="máx. arquivos" value={f.max_files} onChange={(e) => setF({ ...f, max_files: e.target.value })} />
        <input style={{ ...input, width: 90 }} type="number" min={0.5} max={20} step={0.5} value={f.budget_usd} onChange={(e) => setF({ ...f, budget_usd: Number(e.target.value) })} title="budget US$ por lote" />
        <label style={{ fontSize: 13, display: "flex", alignItems: "center", gap: 6 }}>
          <input type="checkbox" checked={f.only_missing} onChange={(e) => setF({ ...f, only_missing: e.target.checked })} />
          só arquivos ainda não inventariados
        </label>
      </div>
      {f.domain && caps.length === 0 && (
        <p style={{ color: "#c53030", fontSize: 13, margin: "8px 0 0" }}>
          O domain {f.domain} não tem capabilities cadastradas. Cadastre em Admin antes de inventariar.
        </p>
      )}
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8 }}>
        <button
          style={btnPrimary}
          disabled={!f.domain || caps.length === 0}
          onClick={async () => {
            try {
              const r = await post("/discovery/inventory", {
                source_id: source.id,
                domain: f.domain,
                prefix: f.prefix || null,
                max_files: f.max_files ? Number(f.max_files) : null,
                only_missing: f.only_missing,
                budget_usd: f.budget_usd,
              });
              onOk(`Inventário enfileirado (campanha ${String(r.batch_id).slice(0, 8)}). O worker do host enumera os fontes e cria um job por lote. Acompanhe em Discovery.`);
            } catch (e: any) {
              onErro(e.message);
            }
          }}
        >
          Enfileirar inventário
        </button>
        <span style={dica}>Muitos lotes = muitos jobs na fila `discovery` (worker no host).</span>
      </div>
    </div>
  );
}

/** Passo 2: discovery dirigido — um turno por arquivo (ou faixa) por capability. */
function Campanha({ source, domains, capabilities, summary, onOk, onErro }: any) {
  const [f, setF] = useState<any>({ domain: source.domain_slug ?? "", capability: "", min_relevance: 2, max_files: "", budget_usd: 3, max_candidates: 12 });
  const caps = capabilities.filter((c: any) => c.domain_slug === f.domain);
  const contagem: Record<string, any> = Object.fromEntries((summary?.capabilities ?? []).map((c: any) => [c.slug, c]));
  const sel = contagem[f.capability];
  const elegiveis = sel ? [3, 2, 1].filter((r) => r >= f.min_relevance).reduce((a, r) => a + (sel.by_relevance?.[r] ?? 0), 0) : 0;
  return (
    <div style={painel}>
      <p style={{ ...dica, marginTop: 0 }}>
        Para a capability escolhida, cada arquivo inventariado (com relevância mínima) vira um turno do
        harness com o conteúdo numerado embutido no prompt. Arquivos grandes são fatiados em faixas.
        O agente pode pedir follow-ups em arquivos relacionados, que entram na mesma campanha.
      </p>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <select style={input} value={f.domain} onChange={(e) => setF({ ...f, domain: e.target.value, capability: "" })}>
          <option value="">domain *</option>
          {domains.map((d: any) => (
            <option key={d.slug} value={d.slug}>{d.slug}</option>
          ))}
        </select>
        <select style={{ ...input, minWidth: 220 }} value={f.capability} onChange={(e) => setF({ ...f, capability: e.target.value })}>
          <option value="">capability *</option>
          {caps.map((c: any) => (
            <option key={c.slug} value={c.slug}>
              {c.slug} ({contagem[c.slug]?.files ?? 0} arquivo(s))
            </option>
          ))}
        </select>
        <select style={input} value={f.min_relevance} onChange={(e) => setF({ ...f, min_relevance: Number(e.target.value) })} title="relevância mínima">
          <option value={3}>só centrais (3)</option>
          <option value={2}>centrais + relevantes (≥2)</option>
          <option value={1}>todos, inclusive tangenciais (≥1)</option>
        </select>
        <input style={{ ...input, width: 110 }} type="number" min={1} placeholder="máx. arquivos" value={f.max_files} onChange={(e) => setF({ ...f, max_files: e.target.value })} />
        <input style={{ ...input, width: 90 }} type="number" min={0.5} max={20} step={0.5} value={f.budget_usd} onChange={(e) => setF({ ...f, budget_usd: Number(e.target.value) })} title="budget US$ por arquivo/faixa" />
        <input style={{ ...input, width: 90 }} type="number" min={1} max={40} value={f.max_candidates} onChange={(e) => setF({ ...f, max_candidates: Number(e.target.value) })} title="máx. candidates por turno" />
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8 }}>
        <button
          style={btnPrimary}
          disabled={!f.domain || !f.capability}
          onClick={async () => {
            try {
              const r = await post("/discovery/campaigns", {
                source_id: source.id,
                domain: f.domain,
                capability: f.capability,
                min_relevance: f.min_relevance,
                max_files: f.max_files ? Number(f.max_files) : null,
                budget_usd: f.budget_usd,
                max_candidates: f.max_candidates,
              });
              onOk(`Campanha enfileirada: ${r.files} arquivo(s), ${r.jobs} turno(s). Acompanhe em Discovery.`);
            } catch (e: any) {
              onErro(e.message);
            }
          }}
        >
          Enfileirar campanha
        </button>
        <span style={dica}>
          {f.capability
            ? `${elegiveis} arquivo(s) elegível(is) · custo máximo ≈ US$ ${(elegiveis * f.budget_usd).toFixed(0)} (sem contar faixas e follow-ups)`
            : summary && summary.files === 0
              ? "Esta source ainda não foi inventariada."
              : ""}
        </span>
      </div>
    </div>
  );
}

/** Varredura livre (modo original): o agente explora sozinho com um texto de escopo. */
function RodarDiscovery({ source, domains, capabilities, onOk, onErro }: any) {
  const [f, setF] = useState<any>({
    agent: "code",
    domain: source.domain_slug ?? "",
    capability: "",
    scope_hint: "todo o repositório",
    budget_usd: 5,
  });
  const caps = capabilities.filter((c: any) => c.domain_slug === f.domain);
  return (
    <div style={painel}>
      <p style={{ ...dica, marginTop: 0 }}>
        O agente recebe domain, capability e um texto de escopo, e explora o repositório por conta própria
        dentro do budget. Útil para repositórios pequenos ou para a corroboração (§88).
      </p>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <select style={input} value={f.agent} onChange={(e) => setF({ ...f, agent: e.target.value })}>
          <option value="code">code discovery</option>
          <option value="test">test discovery</option>
          <option value="corroboration">corroboration (§88)</option>
        </select>
        <select style={input} value={f.domain} onChange={(e) => setF({ ...f, domain: e.target.value, capability: "" })}>
          <option value="">domain *</option>
          {domains.map((d: any) => (
            <option key={d.slug} value={d.slug}>{d.slug}</option>
          ))}
        </select>
        <select style={input} value={f.capability} onChange={(e) => setF({ ...f, capability: e.target.value })}>
          <option value="">capability (opcional)</option>
          {caps.map((c: any) => (
            <option key={c.slug} value={c.slug}>{c.slug}</option>
          ))}
        </select>
        <input style={{ ...input, width: 90 }} type="number" min={1} max={50} value={f.budget_usd} onChange={(e) => setF({ ...f, budget_usd: Number(e.target.value) })} title="budget US$" />
      </div>
      <input style={{ ...input, width: "100%", marginTop: 8 }} placeholder="Escopo prioritário da varredura (módulos, pastas…)" value={f.scope_hint} onChange={(e) => setF({ ...f, scope_hint: e.target.value })} />
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8 }}>
        <button
          style={btnPrimary}
          onClick={async () => {
            if (!f.domain) return onErro("Selecione o domain");
            try {
              await post("/discovery/runs", {
                source_id: source.id,
                agent: f.agent,
                domain: f.domain,
                capability: f.capability || null,
                scope_hint: f.scope_hint,
                budget_usd: f.budget_usd,
              });
              onOk("Run enfileirado na fila `discovery`.");
            } catch (e: any) {
              onErro(e.message);
            }
          }}
        >
          Enfileirar run
        </button>
      </div>
    </div>
  );
}

function ResumoInventario({ source, summary, domains, admin, onCriada, onErro }: any) {
  if (!summary) return <p style={{ ...dica }}>Carregando inventário…</p>;
  if (summary.files === 0)
    return (
      <p style={{ ...dica, margin: "6px 0" }}>
        Nenhum arquivo inventariado ainda. Rode o <strong>inventário</strong> para ligar os fontes às capabilities.
      </p>
    );
  return (
    <div style={{ fontSize: 13, margin: "6px 0" }}>
      <div>
        <strong>{summary.files}</strong> arquivo(s) inventariado(s) · {summary.files_with_capability} com capability ·{" "}
        {summary.files_without_capability} sem (infra/genéricos)
        {summary.last_inventoried_at && (
          <span style={dica}> · último em {summary.last_inventoried_at.slice(0, 16).replace("T", " ")}</span>
        )}
      </div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 6 }}>
        {summary.capabilities.map((c: any) => (
          <span key={c.slug} title={`central ${c.by_relevance[3] ?? 0} · relevante ${c.by_relevance[2] ?? 0} · tangencial ${c.by_relevance[1] ?? 0}`}>
            <Badge text={`${c.slug} · ${c.files}`} color="#2b6cb0" />
          </span>
        ))}
      </div>
      {summary.suggestions.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontWeight: 600 }}>Capabilities sugeridas pelo inventário</div>
          {summary.suggestions.map((s: any) => (
            <div key={s.id} style={{ display: "flex", gap: 8, alignItems: "flex-start", padding: "4px 0", borderTop: "1px solid #edf2f7" }}>
              <div style={{ flex: 1 }}>
                <strong>{s.name}</strong>{" "}
                <span style={dica}>({s.hits} lote(s))</span>
                <div style={dica}>{s.rationale}</div>
                {s.example_files?.length > 0 && (
                  <div style={{ ...dica, fontFamily: "monospace" }}>{s.example_files.slice(0, 4).join(", ")}</div>
                )}
              </div>
              {admin && (
                <button
                  style={{ ...btn, padding: "4px 10px", fontSize: 12, whiteSpace: "nowrap" }}
                  title={`Criar capability ${slugify(s.name)} no domain ${s.domain_slug}`}
                  onClick={async () => {
                    try {
                      await post("/admin/capabilities", {
                        slug: slugify(s.name),
                        domain_slug: s.domain_slug,
                        name: s.name,
                        description: s.rationale,
                      });
                      onCriada(`Capability ${slugify(s.name)} criada. Re-inventarie para ligar os arquivos a ela.`);
                    } catch (e: any) {
                      onErro(e.message);
                    }
                  }}
                >
                  Criar capability
                </button>
              )}
            </div>
          ))}
        </div>
      )}
      <a href={`/discovery?source=${source.id}`} style={{ ...dica, color: "#2b6cb0" }}>ver runs desta source →</a>
    </div>
  );
}

export default function SourcesPage() {
  const [sources, setSources] = useState<any[] | null>(null);
  const [runs, setRuns] = useState<any[]>([]);
  const [domains, setDomains] = useState<any[]>([]);
  const [capabilities, setCapabilities] = useState<any[]>([]);
  const [admin, setAdmin] = useState(false);
  const [aberta, setAberta] = useState<string | null>(null);
  const [aba, setAba] = useState<"inventario" | "campanha" | "livre">("inventario");
  const [summaries, setSummaries] = useState<Record<string, any>>({});
  const [msg, setMsg] = useState<string | null>(null);

  const reload = useCallback(() => {
    get("/sources").then(setSources).catch(() => setSources([]));
    get("/discovery/runs").then(setRuns).catch(() => {});
    get("/admin/domains")
      .then((d) => {
        setDomains(d);
        setAdmin(true);
      })
      .catch(() => setAdmin(false));
    get("/admin/capabilities").then(setCapabilities).catch(() => {});
  }, []);
  useEffect(reload, [reload]);

  const loadSummary = useCallback((id: string) => {
    get(`/sources/${id}/inventory/summary`)
      .then((s) => setSummaries((prev) => ({ ...prev, [id]: s })))
      .catch(() => {});
  }, []);
  useEffect(() => {
    if (aberta) loadSummary(aberta);
  }, [aberta, loadSummary]);

  const runsDa = (id: string) => runs.filter((r) => r.source_id === id);
  const abaStyle = (a: string) => ({
    ...btn,
    padding: "6px 12px",
    fontSize: 13,
    background: aba === a ? "#2b6cb0" : "#edf2f7",
    color: aba === a ? "#fff" : "#1a202c",
    border: aba === a ? "none" : "1px solid #cbd5e0",
  });

  return (
    <Shell title="Sources (§10)">
      {msg && (
        <div style={{ ...card, background: "#fffaf0", border: "1px solid #f6ad55" }}>
          {msg}{" "}
          <a style={{ cursor: "pointer", color: "#2b6cb0" }} onClick={() => setMsg(null)}>
            fechar
          </a>
        </div>
      )}
      {admin && (
        <div style={{ marginBottom: 14 }}>
          <NovaSource
            domains={domains}
            onCriada={() => {
              setMsg(null);
              reload();
            }}
            onErro={setMsg}
          />
        </div>
      )}
      {sources === null && <p>Carregando…</p>}
      {sources?.length === 0 && <p style={{ color: "#718096" }}>Nenhuma source registrada.</p>}
      {sources?.map((s) => {
        const rs = runsDa(s.id);
        const custo = rs.reduce((acc, r) => acc + (r.cost_usd || 0), 0);
        return (
          <div key={s.id} style={card}>
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <Badge text={s.type} color="#2b6cb0" />
              {s.domain_slug && <Badge text={s.domain_slug} />}
              <strong style={{ flex: 1 }}>{s.name}</strong>
              <span style={{ fontSize: 12, color: "#718096" }}>
                {rs.length} run(s) · US$ {custo.toFixed(2)}
              </span>
              <button style={btn} onClick={() => setAberta(aberta === s.id ? null : s.id)}>
                {aberta === s.id ? "Fechar" : "Detalhes"}
              </button>
            </div>
            <div style={{ fontSize: 13, color: "#718096", marginTop: 4 }}>
              {s.repository ?? s.location ?? "—"}
              {s.branch ? ` @ ${s.branch}` : ""}
              {s.commit ? ` (${s.commit.slice(0, 8)})` : ""}
            </div>

            {aberta === s.id && (
              <div style={{ marginTop: 10 }}>
                {s.repository && (
                  <>
                    <h4 style={{ margin: "8px 0 4px" }}>Inventário</h4>
                    <ResumoInventario
                      source={s}
                      summary={summaries[s.id]}
                      domains={domains}
                      admin={admin}
                      onCriada={(m: string) => {
                        setMsg(m);
                        reload();
                        loadSummary(s.id);
                      }}
                      onErro={setMsg}
                    />
                  </>
                )}
                {admin && s.repository && (
                  <>
                    <div style={{ display: "flex", gap: 6, marginTop: 12 }}>
                      <button style={abaStyle("inventario")} onClick={() => setAba("inventario")}>1. Inventariar</button>
                      <button style={abaStyle("campanha")} onClick={() => setAba("campanha")}>2. Discovery dirigido</button>
                      <button style={abaStyle("livre")} onClick={() => setAba("livre")}>Varredura livre</button>
                    </div>
                    {aba === "inventario" && (
                      <Inventariar source={s} domains={domains} capabilities={capabilities} onOk={(m: string) => { setMsg(m); reload(); }} onErro={setMsg} />
                    )}
                    {aba === "campanha" && (
                      <Campanha source={s} domains={domains} capabilities={capabilities} summary={summaries[s.id]} onOk={(m: string) => { setMsg(m); reload(); }} onErro={setMsg} />
                    )}
                    {aba === "livre" && (
                      <RodarDiscovery source={s} domains={domains} capabilities={capabilities} onOk={(m: string) => { setMsg(m); reload(); }} onErro={setMsg} />
                    )}
                  </>
                )}
                <h4 style={{ margin: "12px 0 6px" }}>Runs de discovery</h4>
                {rs.length === 0 && (
                  <p style={{ fontSize: 13, color: "#718096" }}>Nenhum run para esta source.</p>
                )}
                {rs.slice(0, 15).map((r) => (
                  <div
                    key={r.id}
                    style={{
                      fontSize: 13,
                      padding: 8,
                      borderRadius: 6,
                      background: "#f7fafc",
                      marginBottom: 6,
                    }}
                    title={r.error ?? ""}
                  >
                    <Badge text={r.agent === "inventory" ? "inventário" : r.target_file ? "dirigido" : r.agent} />{" "}
                    <Badge text={r.status} color={RUN_STATUS[r.status] ?? "#718096"} />{" "}
                    <span style={{ color: "#718096" }}>
                      {r.domain}
                      {r.capability ? `/${r.capability}` : ""}
                      {r.target_file ? ` · ${r.target_file}${r.line_range ? ` [${r.line_range}]` : ""}` : ""} ·{" "}
                      {r.started_at?.slice(0, 16).replace("T", " ")}
                    </span>
                    <div style={{ marginTop: 4 }}>
                      {r.agent === "inventory"
                        ? `${r.candidates_created} arquivo(s) inventariado(s) · ${r.questions_created} sugestão(ões)`
                        : `${r.candidates_created} candidates · ${r.questions_created} questions · ${r.evidence_rejected} evidência(s) inválida(s)`}{" "}
                      · <strong>US$ {(r.cost_usd || 0).toFixed(2)}</strong>
                      {r.commit && (
                        <span style={{ color: "#a0aec0" }}> · commit {r.commit.slice(0, 8)}</span>
                      )}
                      {r.workspace_clean === "no" && (
                        <Badge text="workspace sujo!" color="#c53030" />
                      )}
                    </div>
                    {r.error && (
                      <div style={{ color: "#c53030", marginTop: 4 }}>
                        {String(r.error).slice(0, 200)}
                      </div>
                    )}
                  </div>
                ))}
                {rs.length > 15 && (
                  <a href={`/discovery?source=${s.id}`} style={{ fontSize: 13, color: "#2b6cb0" }}>
                    ver todos os {rs.length} runs em Discovery →
                  </a>
                )}
              </div>
            )}
          </div>
        );
      })}
    </Shell>
  );
}
