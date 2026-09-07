"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { get, post } from "@/lib/api";
import {
  Badge,
  ConfidenceBar,
  RiskBadge,
  STATUS_LABEL,
  Shell,
  SignificanceBadge,
  StatusBadge,
  btn,
  btnPrimary,
  card,
  input,
} from "@/components/ui";

type ExplorerCapability = { slug: string; name: string; canonical: number; total: number };
type ExplorerDomain = { slug: string; name: string; capabilities: ExplorerCapability[] };

type Item = {
  id: string;
  kind?: string;
  title: string;
  status: string;
  confidence: number | null;
  risk: string | null;
  significance?: string | null;
  classification?: string | null;
  domain?: string;
  capability?: string | null;
  body?: { statement?: string | null } | null;
  statement?: string | null;
};

type BulkResult = {
  action: string;
  ok: number;
  failed: number;
  results: { id: string; ok: boolean; status?: string; error?: string }[];
};

const STATUS_OPCOES = ["PROVISIONAL", "NEEDS_HUMAN_REVIEW", "CANONICAL", "CORROBORATING"];
const SIGNIFICANCE_OPCOES = ["HIGH", "MEDIUM", "LOW", "SYSTEMIC"];

const statementDe = (i: Item) => i.body?.statement ?? i.statement ?? null;

function Linha({ i, marcado, onToggle }: { i: Item; marcado: boolean; onToggle: () => void }) {
  const st = statementDe(i);
  return (
    <div
      style={{
        display: "flex",
        gap: 10,
        alignItems: "flex-start",
        padding: "8px 0",
        borderBottom: "1px solid #edf2f7",
      }}
    >
      <input type="checkbox" checked={marcado} onChange={onToggle} style={{ marginTop: 4 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
          <StatusBadge status={i.status} />
          <SignificanceBadge significance={i.significance} />
          <RiskBadge risk={i.risk} />
          {i.classification && <Badge text={i.classification} color="#6b46c1" />}
          <Link
            href={`/atom/${encodeURIComponent(i.id)}`}
            style={{ fontWeight: 600, color: "inherit", textDecoration: "none" }}
          >
            {i.title}
          </Link>
        </div>
        {st && <div style={{ fontSize: 13, color: "#4a5568", marginTop: 4 }}>{st}</div>}
        {(i.domain || i.kind) && (
          <div style={{ fontSize: 12, color: "#a0aec0", marginTop: 2 }}>
            {i.domain}
            {i.capability ? ` / ${i.capability}` : ""}
            {i.kind ? ` · ${i.kind}` : ""}
          </div>
        )}
      </div>
      <ConfidenceBar value={i.confidence} />
    </div>
  );
}

export default function ProvisionalPage() {
  const [tree, setTree] = useState<ExplorerDomain[]>([]);
  const [domain, setDomain] = useState("");
  const [capability, setCapability] = useState("");
  const [status, setStatus] = useState("PROVISIONAL");
  const [significance, setSignificance] = useState("");
  const [minConf, setMinConf] = useState("");
  const [maxConf, setMaxConf] = useState("");
  const [q, setQ] = useState("");

  const [lista, setLista] = useState<{ total: number; items: Item[] } | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const [amostra, setAmostra] = useState<{ items: Item[]; sampled_from: number } | null>(null);
  const [amostrando, setAmostrando] = useState(false);

  const [sel, setSel] = useState<Set<string>>(new Set());
  const [comment, setComment] = useState("");
  const [executando, setExecutando] = useState(false);
  const [resultado, setResultado] = useState<BulkResult | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    get<ExplorerDomain[]>("/explorer").then(setTree).catch(() => setTree([]));
  }, []);

  const capsDoDomain = useMemo(() => {
    if (domain)
      return (tree.find((d) => d.slug === domain)?.capabilities ?? []).map((c) => ({
        key: `${domain}/${c.slug}`,
        slug: c.slug,
        label: c.name,
      }));
    return tree.flatMap((d) =>
      d.capabilities.map((c) => ({ key: `${d.slug}/${c.slug}`, slug: c.slug, label: `${d.name} / ${c.name}` }))
    );
  }, [tree, domain]);

  const montarQuery = () => {
    const p = new URLSearchParams();
    if (status) p.set("status", status);
    if (domain) p.set("domain", domain);
    if (capability) p.set("capability", capability);
    if (significance) p.set("significance", significance);
    if (minConf !== "") p.set("min_confidence", (Number(minConf) / 100).toFixed(2));
    if (maxConf !== "") p.set("max_confidence", (Number(maxConf) / 100).toFixed(2));
    if (q.trim()) p.set("q", q.trim());
    p.set("limit", "100");
    return p.toString();
  };

  const carregar = async () => {
    setCarregando(true);
    setErro(null);
    try {
      const r = await get<{ total: number; items: Item[] }>(`/knowledge?${montarQuery()}`);
      setLista(r);
    } catch (e: any) {
      setErro(e.message);
    } finally {
      setCarregando(false);
    }
  };

  useEffect(() => {
    carregar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const amostrar = async () => {
    setAmostrando(true);
    setMsg(null);
    try {
      const r = await get<{ items: Item[]; sampled_from: number }>(
        `/reviews/inbox/audit-sample?domain=${encodeURIComponent(domain)}&capability=${encodeURIComponent(capability)}&n=10`
      );
      setAmostra(r);
    } catch (e: any) {
      setMsg(`Erro ao sortear amostra: ${e.message}`);
    } finally {
      setAmostrando(false);
    }
  };

  const toggle = (id: string) =>
    setSel((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  const toggleTodos = (itens: Item[]) =>
    setSel((s) => {
      const n = new Set(s);
      const todosMarcados = itens.every((i) => n.has(i.id));
      for (const i of itens) {
        if (todosMarcados) n.delete(i.id);
        else n.add(i.id);
      }
      return n;
    });

  const titulos = useMemo(() => {
    const m: Record<string, string> = {};
    for (const i of lista?.items ?? []) m[i.id] = i.title;
    for (const i of amostra?.items ?? []) m[i.id] = i.title;
    return m;
  }, [lista, amostra]);

  const executar = async (action: "CONFIRM" | "REJECT") => {
    const ids = Array.from(sel);
    if (ids.length === 0) {
      setMsg("Selecione ao menos um item.");
      return;
    }
    if (
      action === "REJECT" &&
      !window.confirm(`Rejeitar ${ids.length} item(ns)? Cada REJECT abre a discussão humana do item.`)
    )
      return;
    setExecutando(true);
    setMsg(null);
    setResultado(null);
    try {
      const r = await post<BulkResult>("/reviews/inbox/bulk", {
        atom_ids: ids,
        action,
        ...(comment.trim() ? { comment: comment.trim() } : {}),
      });
      setResultado(r);
      setMsg(`${action} em lote: ${r.ok} ok, ${r.failed} com erro (${ids.length} selecionados).`);
      // reflete o novo status nos itens da amostra (a lista principal é recarregada)
      setAmostra((a) =>
        a
          ? {
              ...a,
              items: a.items.map((i) => {
                const res = r.results.find((x) => x.id === i.id);
                return res?.ok && res.status ? { ...i, status: res.status } : i;
              }),
            }
          : a
      );
      setSel(new Set());
      await carregar();
    } catch (e: any) {
      setMsg(`Erro: ${e.message}`);
    } finally {
      setExecutando(false);
    }
  };

  const barra = (itens: Item[]) => {
    const todos = itens.length > 0 && itens.every((i) => sel.has(i.id));
    const nAqui = itens.filter((i) => sel.has(i.id)).length;
    return (
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 6 }}>
        <label style={{ fontSize: 13, display: "flex", alignItems: "center", gap: 6, whiteSpace: "nowrap" }}>
          <input
            type="checkbox"
            checked={todos}
            disabled={itens.length === 0}
            onChange={() => toggleTodos(itens)}
          />
          Selecionar todos
        </label>
        <span style={{ fontSize: 12, color: "#718096", whiteSpace: "nowrap" }}>
          {nAqui} aqui · {sel.size} no total
        </span>
        <span style={{ flex: 1 }} />
        <input
          style={{ ...input, minWidth: 200 }}
          placeholder="comentário (opcional)"
          value={comment}
          onChange={(e) => setComment(e.target.value)}
        />
        <button
          style={{ ...btnPrimary, background: "#276749" }}
          disabled={executando || sel.size === 0}
          onClick={() => executar("CONFIRM")}
        >
          {executando ? "Aplicando…" : "Confirmar selecionados"}
        </button>
        <button
          style={{ ...btnPrimary, background: "#9b2c2c" }}
          disabled={executando || sel.size === 0}
          onClick={() => executar("REJECT")}
        >
          Rejeitar selecionados
        </button>
      </div>
    );
  };

  const msgErro = !!msg && msg.startsWith("Erro");

  return (
    <Shell title="Provisórios · revisão por filtro">
      <p style={{ fontSize: 14, color: "#4a5568", marginTop: 0 }}>
        Itens <strong>provisórios</strong> foram publicados com boa confiança, mas ainda não foram
        confirmados. Um <strong>CONFIRM</strong> de um reviewer pode canonicalizá-los quando a política
        dispensa o owner; um <strong>REJECT</strong> abre a discussão humana. Filtre por domain,
        capability, relevância e faixa de confiança e trate os itens em lote.
      </p>

      <div style={card}>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <select
            style={input}
            value={domain}
            onChange={(e) => {
              setDomain(e.target.value);
              setCapability("");
            }}
          >
            <option value="">todos os domains</option>
            {tree.map((d) => (
              <option key={d.slug} value={d.slug}>
                {d.name}
              </option>
            ))}
          </select>
          <select style={input} value={capability} onChange={(e) => setCapability(e.target.value)}>
            <option value="">todas as capabilities</option>
            {capsDoDomain.map((c) => (
              <option key={c.key} value={c.slug}>
                {c.label}
              </option>
            ))}
          </select>
          <select style={input} value={status} onChange={(e) => setStatus(e.target.value)}>
            {STATUS_OPCOES.map((s) => (
              <option key={s} value={s}>
                {STATUS_LABEL[s] ?? s}
              </option>
            ))}
          </select>
          <select style={input} value={significance} onChange={(e) => setSignificance(e.target.value)}>
            <option value="">qualquer relevância</option>
            {SIGNIFICANCE_OPCOES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <input
            type="number"
            min={0}
            max={100}
            style={{ ...input, width: 120 }}
            placeholder="conf. mín. %"
            value={minConf}
            onChange={(e) => setMinConf(e.target.value)}
          />
          <input
            type="number"
            min={0}
            max={100}
            style={{ ...input, width: 120 }}
            placeholder="conf. máx. %"
            value={maxConf}
            onChange={(e) => setMaxConf(e.target.value)}
          />
          <input
            style={{ ...input, flex: 1, minWidth: 160 }}
            placeholder="título contém…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && carregar()}
          />
          <button style={btnPrimary} disabled={carregando} onClick={carregar}>
            {carregando ? "Carregando…" : "Filtrar"}
          </button>
          <button style={btn} disabled={amostrando} onClick={amostrar}>
            {amostrando ? "Sorteando…" : "Amostra de auditoria"}
          </button>
        </div>
      </div>

      {msg && (
        <div
          style={{
            ...card,
            background: msgErro ? "#fff5f5" : "#f0fff4",
            border: `1px solid ${msgErro ? "#fc8181" : "#68d391"}`,
          }}
        >
          {msg}
          {resultado && resultado.failed > 0 && (
            <ul style={{ margin: "6px 0 0", fontSize: 13, color: "#c53030" }}>
              {resultado.results
                .filter((r) => !r.ok)
                .map((r) => (
                  <li key={r.id}>
                    {titulos[r.id] ?? r.id}: {r.error ?? "erro desconhecido"}
                  </li>
                ))}
            </ul>
          )}
        </div>
      )}

      {amostra && (
        <div style={{ ...card, border: "2px solid #b7791f" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <h3 style={{ margin: 0, flex: 1 }}>
              Amostra de auditoria{" "}
              <span style={{ fontSize: 13, color: "#718096", fontWeight: 400 }}>
                {amostra.items.length} de {amostra.sampled_from} elegíveis
              </span>
            </h3>
            <button style={btn} onClick={() => setAmostra(null)}>
              Fechar
            </button>
          </div>
          <p style={{ fontSize: 13, color: "#718096", margin: "4px 0 10px" }}>
            Corte aleatório de itens provisórios sem votos, usado para calibrar o piso provisório.
          </p>
          {barra(amostra.items)}
          {amostra.items.length === 0 && (
            <p style={{ color: "#718096" }}>Nenhum item provisório sem votos para amostrar.</p>
          )}
          {amostra.items.map((i) => (
            <Linha key={i.id} i={i} marcado={sel.has(i.id)} onToggle={() => toggle(i.id)} />
          ))}
        </div>
      )}

      <div style={card}>
        <h3 style={{ marginTop: 0 }}>
          Resultados{" "}
          {lista && (
            <span style={{ fontSize: 13, color: "#718096", fontWeight: 400 }}>
              {lista.total} no total · {lista.items.length} exibidos
            </span>
          )}
        </h3>
        {erro && <p style={{ color: "#c53030" }}>Erro: {erro}</p>}
        {!lista && !erro && <p>Carregando…</p>}
        {lista && (
          <>
            {barra(lista.items)}
            {lista.items.length === 0 && <p style={{ color: "#718096" }}>Nenhum item com estes filtros.</p>}
            {lista.items.map((i) => (
              <Linha key={i.id} i={i} marcado={sel.has(i.id)} onToggle={() => toggle(i.id)} />
            ))}
          </>
        )}
      </div>
    </Shell>
  );
}
