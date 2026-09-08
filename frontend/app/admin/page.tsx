"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { API, api, get, post } from "@/lib/api";
import { Badge, Shell, btn, btnPrimary, card, input } from "@/components/ui";

const SLUG_RE = /^[a-z0-9][a-z0-9-]*$/;

/** Gera um slug válido a partir do nome (minúsculo, sem acento, hífens). */
function slugify(s: string): string {
  return s
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 100);
}

type Domain = { slug: string; name: string; evidence_profile?: string | null };
type EvidenceProfile = {
  name: string;
  site_weights?: Record<string, number>;
  same_file_weights?: Record<string, number>;
  lineage_cap?: number | null;
};
type Capability = { slug: string; domain_slug: string; name: string; description?: string | null };

const textarea = { ...input, width: "100%", minHeight: 56, fontFamily: "inherit", resize: "vertical" as const };

type Agente = {
  id: string;
  name: string;
  client_id: string;
  user_email: string | null;
  active: boolean;
  status: string;
  host?: string | null;
  agent_version?: string | null;
  cli_version?: string | null;
  last_seen_at?: string | null;
  limited_until?: string | null;
  limit_detail?: string | null;
  tasks_done: number;
  tasks_failed: number;
  cost_usd_today: number;
  cost_usd_total: number;
};

const AGENT_STATUS: Record<string, { label: string; color: string }> = {
  idle: { label: "online", color: "#276749" },
  busy: { label: "executando", color: "#2b6cb0" },
  limited: { label: "limitado", color: "#975a16" },
  paused: { label: "pausado", color: "#718096" },
  offline: { label: "offline", color: "#a0aec0" },
  revoked: { label: "revogado", color: "#c53030" },
};

function fmtVisto(iso: string | null | undefined): string {
  if (!iso) return "nunca";
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `há ${s}s`;
  if (s < 3600) return `há ${Math.floor(s / 60)}min`;
  if (s < 86400) return `há ${Math.floor(s / 3600)}h`;
  return new Date(iso).toLocaleString("pt-BR");
}

/** Executor remoto: credenciais dos agentes que rodam o harness nas máquinas da equipe. */
function AgentesRemotos({ onOk, onErro }: { onOk: (m: string) => void; onErro: (m: string) => void }) {
  const [agentes, setAgentes] = useState<Agente[]>([]);
  const [status, setStatus] = useState<any>(null);
  const [users, setUsers] = useState<any[]>([]);
  const [name, setName] = useState("");
  const [userId, setUserId] = useState("");
  const [chave, setChave] = useState<{ name: string; api_key: string } | null>(null);
  const [salvando, setSalvando] = useState(false);
  const [mostrarRevogados, setMostrarRevogados] = useState(false);

  const carregar = useCallback(async () => {
    try {
      const [a, s] = await Promise.all([
        get(`/harness/agents?include_revoked=${mostrarRevogados}`),
        get("/harness/status"),
      ]);
      setAgentes(a);
      setStatus(s);
    } catch (e: any) {
      onErro(e.message);
    }
  }, [mostrarRevogados, onErro]);

  useEffect(() => {
    carregar();
    get("/admin/users").then(setUsers).catch(() => {});
  }, [carregar]);

  const criar = async () => {
    if (!name.trim()) return onErro("Informe um nome para o agente (ex.: Laptop da Ana)");
    if (!userId) return onErro("Escolha a pessoa dona do agente");
    setSalvando(true);
    try {
      const r = await post("/harness/agents", { name: name.trim(), user_id: userId });
      setChave({ name: r.name, api_key: r.api_key });
      setName("");
      onOk("Agente criado. Copie a chave agora: ela não será mostrada de novo.");
      carregar();
    } catch (e: any) {
      onErro(e.message);
    } finally {
      setSalvando(false);
    }
  };

  const rotacionar = async (a: Agente) => {
    if (!confirm(`Gerar nova chave para "${a.name}"? A chave atual deixa de valer na hora.`)) return;
    try {
      const r = await post(`/harness/agents/${a.id}/rotate`);
      setChave({ name: r.name, api_key: r.api_key });
      onOk("Chave rotacionada. Repasse a nova chave para a pessoa.");
      carregar();
    } catch (e: any) {
      onErro(e.message);
    }
  };

  const revogar = async (a: Agente) => {
    if (!confirm(`Revogar o agente "${a.name}"? Tarefas em execução nele voltam para a fila.`)) return;
    try {
      await api(`/harness/agents/${a.id}`, { method: "DELETE" });
      onOk("Agente revogado.");
      carregar();
    } catch (e: any) {
      onErro(e.message);
    }
  };

  const remoto = status?.executor === "remote";
  return (
    <div style={{ ...card, border: "2px solid #2c7a7b" }}>
      <h3 style={{ marginTop: 0 }}>
        Agentes remotos{" "}
        <span style={{ fontSize: 13, color: "#718096", fontWeight: 400 }}>
          executor do harness: <strong>{status?.executor ?? "…"}</strong>
        </span>
      </h3>
      <p style={{ fontSize: 13, color: "#718096", marginTop: -6 }}>
        Com <code>HARNESS_EXECUTOR=remote</code> no worker, cada chamada ao <code>claude</code> vira uma
        tarefa que um agente na máquina de alguém da equipe executa com a própria chave de API. O
        servidor continua montando o prompt, verificando a evidência e gravando. Cada pessoa recebe
        uma credencial própria, revogável.
        {!remoto && (
          <>
            {" "}
            <strong>Hoje o executor é local</strong>: agentes cadastrados ficam ociosos até a troca.
          </>
        )}
      </p>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <input
          style={{ ...input, flex: 1, minWidth: 200 }}
          placeholder="Nome do agente * (ex.: Laptop da Ana)"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && criar()}
        />
        <select style={{ ...input, minWidth: 220 }} value={userId} onChange={(e) => setUserId(e.target.value)}>
          <option value="">pessoa dona do agente *</option>
          {users.filter((u) => u.active).map((u) => (
            <option key={u.id} value={u.id}>
              {u.name} ({u.email})
            </option>
          ))}
        </select>
        <button style={btnPrimary} disabled={salvando} onClick={criar}>
          {salvando ? "Criando…" : "Criar credencial"}
        </button>
      </div>

      {chave && (
        <div style={{ ...card, marginTop: 12, marginBottom: 0, background: "#f0fff4", border: "1px solid #68d391" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <strong style={{ flex: 1 }}>Chave de "{chave.name}" (mostrada uma única vez)</strong>
            <button style={btn} onClick={() => setChave(null)}>fechar</button>
          </div>
          <pre style={{ margin: "8px 0 0", padding: 8, background: "#1a202c", color: "#e2e8f0", borderRadius: 6, fontSize: 12, overflowX: "auto" }}>
            cd backend{"\n"}
            uv run bsp-agent setup --api {API} --key {chave.api_key} --name "{chave.name}"{"\n"}
            uv run bsp-agent doctor{"\n"}
            uv run bsp-agent run --max-usd-per-day 15
          </pre>
          <p style={{ fontSize: 12, color: "#4a5568", margin: "8px 0 0" }}>
            A pessoa precisa do <code>claude</code> instalado e de <code>ANTHROPIC_API_KEY</code> no ambiente (ou
            <code> --anthropic-key</code> no setup). Se a Source não tiver URL git alcançável da máquina dela,
            informe o caminho local com <code>--source &lt;source_id&gt;=&lt;pasta do repositório&gt;</code>.
          </p>
        </div>
      )}

      <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "14px 0 6px" }}>
        <span style={{ fontSize: 13, color: "#718096", flex: 1 }}>
          {agentes.length} agente(s)
          {status?.tasks && remoto && (
            <>
              {" "}· tarefas: {status.tasks.ready ?? 0} na fila · {status.tasks.leased ?? 0} em execução ·{" "}
              {status.tasks.succeeded ?? 0} concluídas · {status.tasks.failed ?? 0} falhas
            </>
          )}
        </span>
        <label style={{ fontSize: 13, display: "flex", alignItems: "center", gap: 6 }}>
          <input type="checkbox" checked={mostrarRevogados} onChange={(e) => setMostrarRevogados(e.target.checked)} />
          mostrar revogados
        </label>
        <button style={btn} onClick={carregar}>Atualizar</button>
      </div>
      {agentes.length === 0 ? (
        <p style={{ fontSize: 13, color: "#a0aec0", margin: 0 }}>Nenhum agente cadastrado.</p>
      ) : (
        <table style={{ width: "100%", fontSize: 13, borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ color: "#718096", textAlign: "left" }}>
              <th style={{ padding: "4px 6px", fontWeight: 600 }}>agente</th>
              <th style={{ padding: "4px 6px", fontWeight: 600 }}>pessoa</th>
              <th style={{ padding: "4px 6px", fontWeight: 600 }}>status</th>
              <th style={{ padding: "4px 6px", fontWeight: 600 }}>visto</th>
              <th style={{ padding: "4px 6px", fontWeight: 600 }}>versão</th>
              <th style={{ padding: "4px 6px", fontWeight: 600 }}>tarefas</th>
              <th style={{ padding: "4px 6px", fontWeight: 600 }}>custo hoje / total</th>
              <th style={{ padding: "4px 6px", width: 170 }}></th>
            </tr>
          </thead>
          <tbody>
            {agentes.map((a) => {
              const st = AGENT_STATUS[a.status] ?? { label: a.status, color: "#718096" };
              return (
                <tr key={a.id} style={{ borderTop: "1px solid #edf2f7", opacity: a.active ? 1 : 0.6 }}>
                  <td style={{ padding: "6px" }}>
                    <strong>{a.name}</strong>
                    <div style={{ fontFamily: "monospace", fontSize: 11, color: "#a0aec0" }}>{a.client_id}{a.host ? ` · ${a.host}` : ""}</div>
                  </td>
                  <td style={{ padding: "6px" }}>{a.user_email ?? "—"}</td>
                  <td style={{ padding: "6px" }} title={a.limit_detail ?? ""}>
                    <Badge text={st.label} color={st.color} />
                  </td>
                  <td style={{ padding: "6px" }}>{fmtVisto(a.last_seen_at)}</td>
                  <td style={{ padding: "6px", fontFamily: "monospace", fontSize: 12 }} title={a.cli_version ?? ""}>{a.agent_version ?? "—"}</td>
                  <td style={{ padding: "6px" }}>
                    <span style={{ color: "#276749" }}>{a.tasks_done} ok</span>
                    {a.tasks_failed > 0 && <span style={{ color: "#c53030" }}> · {a.tasks_failed} falhas</span>}
                  </td>
                  <td style={{ padding: "6px" }}>US$ {(a.cost_usd_today ?? 0).toFixed(2)} / {(a.cost_usd_total ?? 0).toFixed(2)}</td>
                  <td style={{ padding: "6px", whiteSpace: "nowrap" }}>
                    {a.active ? (
                      <>
                        <button style={{ ...btn, padding: "4px 10px", fontSize: 12 }} onClick={() => rotacionar(a)}>Nova chave</button>{" "}
                        <button style={{ ...btn, padding: "4px 10px", fontSize: 12, color: "#c53030" }} onClick={() => revogar(a)}>Revogar</button>
                      </>
                    ) : (
                      <button style={{ ...btn, padding: "4px 10px", fontSize: 12 }} onClick={() => rotacionar(a)} title="reativa com uma chave nova">Reativar</button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}

function NovoDomain({
  profiles,
  onCriado,
  onErro,
}: {
  profiles: EvidenceProfile[];
  onCriado: () => void;
  onErro: (m: string) => void;
}) {
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [evidenceProfile, setEvidenceProfile] = useState("");
  const [slugManual, setSlugManual] = useState(false);
  const [salvando, setSalvando] = useState(false);
  const slugOk = SLUG_RE.test(slug);

  const salvar = async () => {
    if (!name.trim()) return onErro("Informe o nome do domain");
    if (!slugOk) return onErro("Slug inválido: use letras minúsculas, números e hífens");
    setSalvando(true);
    try {
      await post("/admin/domains", {
        slug,
        name: name.trim(),
        ...(evidenceProfile ? { evidence_profile: evidenceProfile } : {}),
      });
      setName("");
      setSlug("");
      setEvidenceProfile("");
      setSlugManual(false);
      onCriado();
    } catch (e: any) {
      onErro(e.message);
    } finally {
      setSalvando(false);
    }
  };

  return (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
      <input
        style={{ ...input, flex: 1, minWidth: 180 }}
        placeholder="Nome * (ex.: Finance)"
        value={name}
        onChange={(e) => {
          setName(e.target.value);
          if (!slugManual) setSlug(slugify(e.target.value));
        }}
        onKeyDown={(e) => e.key === "Enter" && salvar()}
      />
      <input
        style={{ ...input, width: 200, borderColor: slug && !slugOk ? "#c53030" : undefined }}
        placeholder="slug * (ex.: finance)"
        value={slug}
        onChange={(e) => {
          setSlugManual(true);
          setSlug(e.target.value);
        }}
        onKeyDown={(e) => e.key === "Enter" && salvar()}
        title="Identificador único: letras minúsculas, números e hífens"
      />
      <select
        style={input}
        value={evidenceProfile}
        onChange={(e) => setEvidenceProfile(e.target.value)}
        title="Perfil de evidência (pesos do Confidence Engine)"
      >
        <option value="">perfil de evidência (padrão)</option>
        {profiles.map((p) => (
          <option key={p.name} value={p.name}>
            {p.name}
          </option>
        ))}
      </select>
      <button style={btnPrimary} disabled={salvando} onClick={salvar}>
        {salvando ? "Salvando…" : "Adicionar domain"}
      </button>
    </div>
  );
}

function NovaCapability({
  domains,
  domainInicial,
  onCriada,
  onErro,
}: {
  domains: Domain[];
  domainInicial: string;
  onCriada: () => void;
  onErro: (m: string) => void;
}) {
  const [domain, setDomain] = useState(domainInicial);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [description, setDescription] = useState("");
  const [slugManual, setSlugManual] = useState(false);
  const [salvando, setSalvando] = useState(false);
  const slugOk = SLUG_RE.test(slug);

  useEffect(() => setDomain(domainInicial), [domainInicial]);

  const salvar = async () => {
    if (!domain) return onErro("Selecione o domain da capability");
    if (!name.trim()) return onErro("Informe o nome da capability");
    if (!slugOk) return onErro("Slug inválido: use letras minúsculas, números e hífens");
    setSalvando(true);
    try {
      await post("/admin/capabilities", {
        slug,
        domain_slug: domain,
        name: name.trim(),
        description: description.trim() || null,
      });
      setName("");
      setSlug("");
      setDescription("");
      setSlugManual(false);
      onCriada();
    } catch (e: any) {
      onErro(e.message);
    } finally {
      setSalvando(false);
    }
  };

  return (
    <div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <select style={input} value={domain} onChange={(e) => setDomain(e.target.value)}>
          <option value="">domain *</option>
          {domains.map((d) => (
            <option key={d.slug} value={d.slug}>
              {d.slug}
            </option>
          ))}
        </select>
        <input
          style={{ ...input, flex: 1, minWidth: 180 }}
          placeholder="Nome * (ex.: Invoice Cancellation)"
          value={name}
          onChange={(e) => {
            setName(e.target.value);
            if (!slugManual) setSlug(slugify(e.target.value));
          }}
        />
        <input
          style={{ ...input, width: 200, borderColor: slug && !slugOk ? "#c53030" : undefined }}
          placeholder="slug * (ex.: invoice-cancellation)"
          value={slug}
          onChange={(e) => {
            setSlugManual(true);
            setSlug(e.target.value);
          }}
          title="Identificador único: letras minúsculas, números e hífens"
        />
      </div>
      <textarea
        style={{ ...textarea, marginTop: 8 }}
        placeholder="Descrição em linguagem de negócio: o que esta capability cobre (o inventário e o discovery dirigido recebem isto no prompt). Ex.: emissão e cancelamento de notas fiscais, cálculo de impostos na saída…"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
      />
      <div style={{ marginTop: 8 }}>
        <button style={btnPrimary} disabled={salvando} onClick={salvar}>
          {salvando ? "Salvando…" : "Adicionar capability"}
        </button>
      </div>
    </div>
  );
}

function LinhaCapability({ c, onSalva, onErro }: { c: Capability; onSalva: () => void; onErro: (m: string) => void }) {
  const [editando, setEditando] = useState(false);
  const [name, setName] = useState(c.name);
  const [description, setDescription] = useState(c.description ?? "");
  const salvar = async () => {
    try {
      await api(`/admin/capabilities/${c.slug}`, {
        method: "PATCH",
        body: JSON.stringify({ name: name.trim(), description: description.trim() || null }),
      });
      setEditando(false);
      onSalva();
    } catch (e: any) {
      onErro(e.message);
    }
  };
  if (editando)
    return (
      <tr style={{ borderTop: "1px solid #edf2f7", background: "#f7fafc" }}>
        <td style={{ padding: 6, fontFamily: "monospace", verticalAlign: "top" }}>{c.slug}</td>
        <td style={{ padding: 6 }} colSpan={2}>
          <input style={{ ...input, width: "100%" }} value={name} onChange={(e) => setName(e.target.value)} />
          <textarea
            style={{ ...textarea, marginTop: 6 }}
            placeholder="Descrição em linguagem de negócio"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
          <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
            <button style={{ ...btnPrimary, padding: "4px 10px", fontSize: 12 }} onClick={salvar}>Salvar</button>
            <button style={{ ...btn, padding: "4px 10px", fontSize: 12 }} onClick={() => setEditando(false)}>Cancelar</button>
          </div>
        </td>
      </tr>
    );
  return (
    <tr style={{ borderTop: "1px solid #edf2f7" }}>
      <td style={{ padding: 6, fontFamily: "monospace", verticalAlign: "top" }}>{c.slug}</td>
      <td style={{ padding: 6, verticalAlign: "top" }}>
        <div>{c.name}</div>
        <div style={{ color: c.description ? "#4a5568" : "#a0aec0", fontSize: 12, marginTop: 2 }}>
          {c.description ?? "sem descrição — o agente só terá o nome para se orientar"}
        </div>
      </td>
      <td style={{ padding: 6, textAlign: "right", verticalAlign: "top" }}>
        <button style={{ ...btn, padding: "4px 10px", fontSize: 12 }} onClick={() => setEditando(true)}>
          Editar
        </button>
      </td>
    </tr>
  );
}

export default function AdminPage() {
  const [domains, setDomains] = useState<Domain[] | null>(null);
  const [capabilities, setCapabilities] = useState<Capability[]>([]);
  const [profiles, setProfiles] = useState<EvidenceProfile[]>([]);
  const [acesso, setAcesso] = useState<"carregando" | "ok" | "negado">("carregando");
  const [filtro, setFiltro] = useState<string>("");
  const [msg, setMsg] = useState<{ tipo: "erro" | "ok"; texto: string } | null>(null);

  const reload = useCallback(() => {
    get<Domain[]>("/admin/domains")
      .then((d) => {
        setDomains(d);
        setAcesso("ok");
      })
      .catch(() => {
        setDomains([]);
        setAcesso("negado");
      });
    get<Capability[]>("/admin/capabilities").then(setCapabilities).catch(() => {});
    get<EvidenceProfile[]>("/admin/evidence-profiles").then(setProfiles).catch(() => {});
  }, []);
  useEffect(reload, [reload]);

  const capsPorDomain = useMemo(() => {
    const m: Record<string, Capability[]> = {};
    for (const c of capabilities) (m[c.domain_slug] ??= []).push(c);
    return m;
  }, [capabilities]);

  const domainsVisiveis = (domains ?? []).filter((d) => !filtro || d.slug === filtro);

  const erro = (texto: string) => setMsg({ tipo: "erro", texto });
  const ok = (texto: string) => {
    setMsg({ tipo: "ok", texto });
    reload();
  };
  const alterarPerfil = async (slug: string, evidence_profile: string | null) => {
    try {
      await api(`/admin/domains/${slug}`, { method: "PATCH", body: JSON.stringify({ evidence_profile }) });
      ok(`Perfil de evidência de ${slug}: ${evidence_profile ?? "(padrão)"}.`);
    } catch (e: any) {
      erro(e.message);
    }
  };

  return (
    <Shell title="Administração · Domains e Capabilities">
      {msg && (
        <div
          style={{
            ...card,
            background: msg.tipo === "erro" ? "#fff5f5" : "#f0fff4",
            border: `1px solid ${msg.tipo === "erro" ? "#fc8181" : "#68d391"}`,
          }}
        >
          {msg.texto}{" "}
          <a style={{ cursor: "pointer", color: "#2b6cb0" }} onClick={() => setMsg(null)}>
            fechar
          </a>
        </div>
      )}

      {acesso === "carregando" && <p>Carregando…</p>}
      {acesso === "negado" && (
        <div style={{ ...card, background: "#fffaf0", border: "1px solid #f6ad55" }}>
          Esta área exige o papel de <strong>administrador global</strong>. O primeiro
          administrador é criado com <code>python -m app.create_admin</code> (ver README).
        </div>
      )}

      {acesso === "ok" && (
        <>
          <div style={{ ...card, border: "2px solid #2b6cb0" }}>
            <h3 style={{ marginTop: 0 }}>Novo domain</h3>
            <p style={{ fontSize: 13, color: "#718096", marginTop: -6 }}>
              Um domain agrupa capabilities e define o escopo das políticas e dos papéis
              (reviewer, domain expert, decision owner).
            </p>
            <NovoDomain profiles={profiles} onCriado={() => ok("Domain criado.")} onErro={erro} />
          </div>

          <div style={{ ...card, border: "2px solid #2b6cb0" }}>
            <h3 style={{ marginTop: 0 }}>Nova capability</h3>
            <p style={{ fontSize: 13, color: "#718096", marginTop: -6 }}>
              Capability é a unidade de negócio dentro do domain. O <strong>inventário</strong> liga cada
              arquivo-fonte às capabilities e o <strong>discovery dirigido</strong> extrai regras arquivo a
              arquivo por capability. Uma boa descrição melhora os dois.
            </p>
            {domains && domains.length === 0 ? (
              <p style={{ color: "#975a16", fontSize: 13 }}>
                Crie um domain antes de cadastrar capabilities.
              </p>
            ) : (
              <NovaCapability
                domains={domains ?? []}
                domainInicial={filtro}
                onCriada={() => ok("Capability criada.")}
                onErro={erro}
              />
            )}
          </div>

          <AgentesRemotos onOk={ok} onErro={erro} />

          <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "18px 0 8px" }}>
            <h2 style={{ fontSize: 18, margin: 0, flex: 1 }}>
              Cadastrados{" "}
              <span style={{ fontSize: 13, color: "#718096", fontWeight: 400 }}>
                {domains?.length ?? 0} domain(s) · {capabilities.length} capability(ies)
              </span>
            </h2>
            {domains && domains.length > 1 && (
              <select style={input} value={filtro} onChange={(e) => setFiltro(e.target.value)}>
                <option value="">todos os domains</option>
                {domains.map((d) => (
                  <option key={d.slug} value={d.slug}>
                    {d.slug}
                  </option>
                ))}
              </select>
            )}
          </div>

          <p style={{ fontSize: 13, color: "#718096", margin: "0 0 10px" }}>
            Perfil de evidência: pesos do Confidence Engine. legacy-hostile = ERP antigo sem
            documentação/testes confiáveis: um arquivo de código já publica como provisório, dois fecham
            MEDIUM.
          </p>
          {domains?.length === 0 && <p style={{ color: "#718096" }}>Nenhum domain cadastrado ainda.</p>}
          {domainsVisiveis.map((d) => {
            const caps = capsPorDomain[d.slug] ?? [];
            return (
              <div key={d.slug} style={card}>
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <Badge text={d.slug} color="#2b6cb0" />
                  <strong style={{ flex: 1 }}>{d.name}</strong>
                  <span style={{ fontSize: 12, color: "#718096" }}>{caps.length} capability(ies)</span>
                  <select
                    style={{ ...input, padding: "4px 8px", fontSize: 12 }}
                    value={d.evidence_profile ?? ""}
                    onChange={(e) => alterarPerfil(d.slug, e.target.value || null)}
                    title="Perfil de evidência (pesos do Confidence Engine)"
                  >
                    <option value="">(padrão)</option>
                    {d.evidence_profile && !profiles.some((p) => p.name === d.evidence_profile) && (
                      <option value={d.evidence_profile}>{d.evidence_profile}</option>
                    )}
                    {profiles.map((p) => (
                      <option key={p.name} value={p.name}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                  {filtro !== d.slug && (
                    <button
                      style={btn}
                      onClick={() => setFiltro(d.slug)}
                      title="Selecionar este domain no formulário de capability"
                    >
                      Usar
                    </button>
                  )}
                </div>
                {caps.length === 0 ? (
                  <p style={{ fontSize: 13, color: "#a0aec0", margin: "8px 0 0" }}>Sem capabilities.</p>
                ) : (
                  <table style={{ width: "100%", marginTop: 10, fontSize: 13, borderCollapse: "collapse" }}>
                    <thead>
                      <tr style={{ color: "#718096", textAlign: "left" }}>
                        <th style={{ padding: "4px 6px", fontWeight: 600, width: 200 }}>slug</th>
                        <th style={{ padding: "4px 6px", fontWeight: 600 }}>nome e descrição</th>
                        <th style={{ padding: "4px 6px", width: 80 }}></th>
                      </tr>
                    </thead>
                    <tbody>
                      {caps.map((c) => (
                        <LinhaCapability key={c.slug} c={c} onSalva={() => ok("Capability atualizada.")} onErro={erro} />
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            );
          })}
        </>
      )}
    </Shell>
  );
}
