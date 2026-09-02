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
        <input style={{ ...input, flex: 2, minWidth: 220 }} placeholder="Repositório (caminho/URL git)" value={f.repository} onChange={(e) => set("repository", e.target.value)} />
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
    <div style={{ marginTop: 10, padding: 10, background: "#f7fafc", borderRadius: 8 }}>
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
              onOk();
            } catch (e: any) {
              onErro(e.message);
            }
          }}
        >
          Enfileirar run
        </button>
        <span style={{ fontSize: 12, color: "#718096" }}>
          A fila `discovery` roda em worker no HOST (onde o `claude` está logado) — ver README.
        </span>
      </div>
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

  const runsDa = (id: string) => runs.filter((r) => r.source_id === id);

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
                {admin && s.repository && (
                  <RodarDiscovery
                    source={s}
                    domains={domains}
                    capabilities={capabilities}
                    onOk={() => {
                      setMsg("Run enfileirado na fila `discovery`.");
                      reload();
                    }}
                    onErro={setMsg}
                  />
                )}
                <h4 style={{ margin: "12px 0 6px" }}>Runs de discovery</h4>
                {rs.length === 0 && (
                  <p style={{ fontSize: 13, color: "#718096" }}>Nenhum run para esta source.</p>
                )}
                {rs.map((r) => (
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
                    <Badge text={r.agent} />{" "}
                    <Badge text={r.status} color={RUN_STATUS[r.status] ?? "#718096"} />{" "}
                    <span style={{ color: "#718096" }}>
                      {r.domain}
                      {r.capability ? `/${r.capability}` : ""} ·{" "}
                      {r.started_at?.slice(0, 16).replace("T", " ")}
                    </span>
                    <div style={{ marginTop: 4 }}>
                      {r.candidates_created} candidates · {r.questions_created} questions ·{" "}
                      {r.evidence_rejected} evidência(s) inválida(s) ·{" "}
                      <strong>US$ {(r.cost_usd || 0).toFixed(2)}</strong>
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
              </div>
            )}
          </div>
        );
      })}
    </Shell>
  );
}
