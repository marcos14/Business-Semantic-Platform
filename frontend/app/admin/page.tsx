"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, get, post } from "@/lib/api";
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

type Domain = { slug: string; name: string };
type Capability = { slug: string; domain_slug: string; name: string; description?: string | null };

const textarea = { ...input, width: "100%", minHeight: 56, fontFamily: "inherit", resize: "vertical" as const };

function NovoDomain({ onCriado, onErro }: { onCriado: () => void; onErro: (m: string) => void }) {
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugManual, setSlugManual] = useState(false);
  const [salvando, setSalvando] = useState(false);
  const slugOk = SLUG_RE.test(slug);

  const salvar = async () => {
    if (!name.trim()) return onErro("Informe o nome do domain");
    if (!slugOk) return onErro("Slug inválido: use letras minúsculas, números e hífens");
    setSalvando(true);
    try {
      await post("/admin/domains", { slug, name: name.trim() });
      setName("");
      setSlug("");
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
            <NovoDomain onCriado={() => ok("Domain criado.")} onErro={erro} />
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

          {domains?.length === 0 && <p style={{ color: "#718096" }}>Nenhum domain cadastrado ainda.</p>}
          {domainsVisiveis.map((d) => {
            const caps = capsPorDomain[d.slug] ?? [];
            return (
              <div key={d.slug} style={card}>
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <Badge text={d.slug} color="#2b6cb0" />
                  <strong style={{ flex: 1 }}>{d.name}</strong>
                  <span style={{ fontSize: 12, color: "#718096" }}>{caps.length} capability(ies)</span>
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
