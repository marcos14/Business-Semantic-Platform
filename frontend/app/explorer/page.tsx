"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { API, get, getToken } from "@/lib/api";
import { Badge, ConfidenceBar, Shell, StatusBadge, btn, card, input } from "@/components/ui";

const KIND_LABEL: Record<string, string> = {
  concept: "Conceitos",
  rule: "Regras",
  decision: "Decisões",
  invariant: "Invariantes",
  state: "Estados",
  transition: "Transições",
  process: "Processos",
  scenario: "Cenários",
  exception: "Exceções",
  question: "Questions",
  conflict: "Conflitos",
};

export default function ExplorerPage() {
  const [tree, setTree] = useState<any[] | null>(null);
  const [sel, setSel] = useState<{ domain: string; cap: string } | null>(null);
  const [detail, setDetail] = useState<any>(null);
  const [q, setQ] = useState("");
  const [results, setResults] = useState<any[] | null>(null);
  const [proj, setProj] = useState<{ title: string; text: string } | null>(null);

  useEffect(() => {
    get("/explorer").then(setTree).catch(() => setTree([]));
  }, []);

  useEffect(() => {
    if (!sel) return;
    setDetail(null);
    get(`/explorer/${sel.domain}/${sel.cap}`).then(setDetail).catch(() => {});
  }, [sel]);

  async function buscar() {
    if (q.length < 2) return;
    const r = await get(`/search?q=${encodeURIComponent(q)}`);
    setResults(r.items);
  }

  async function verProjecao(titulo: string, path: string) {
    const r = await fetch(`${API}${path}`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    });
    const text = await r.text();
    setProj({ title: titulo, text });
  }

  return (
    <Shell title="Knowledge Explorer">
      <div style={{ ...card, display: "flex", gap: 8 }}>
        <input
          style={{ ...input, flex: 1 }}
          placeholder="Busca full-text e fuzzy (§53) — ex.: fatura vencida"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && buscar()}
        />
        <button style={btn} onClick={buscar}>
          Buscar
        </button>
        {results && (
          <button style={btn} onClick={() => setResults(null)}>
            Limpar
          </button>
        )}
      </div>

      {results && (
        <div style={card}>
          <h3 style={{ marginTop: 0 }}>Resultados ({results.length})</h3>
          {results.map((i) => (
            <Link key={i.id} href={`/atom/${encodeURIComponent(i.id)}`} style={{ textDecoration: "none", color: "inherit" }}>
              <div style={{ padding: "8px 0", borderBottom: "1px solid #edf2f7" }}>
                <Badge text={i.kind} /> <StatusBadge status={i.status} />{" "}
                <Badge text={i.match} color="#718096" />
                <div style={{ fontWeight: 600, marginTop: 4 }}>{i.title}</div>
                <div style={{ fontSize: 12, color: "#718096" }}>
                  {i.domain}/{i.capability ?? "—"}
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}

      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-start" }}>
        <div style={{ ...card, minWidth: 260, flex: "0 0 280px" }}>
          <h3 style={{ marginTop: 0 }}>Domains</h3>
          {tree === null && <p>Carregando…</p>}
          {tree?.map((d) => (
            <div key={d.slug} style={{ marginBottom: 10 }}>
              <div style={{ fontWeight: 700 }}>{d.name}</div>
              {d.capabilities.map((c: any) => (
                <div
                  key={c.slug}
                  onClick={() => setSel({ domain: d.slug, cap: c.slug })}
                  style={{
                    cursor: "pointer",
                    padding: "6px 10px",
                    borderRadius: 6,
                    background:
                      sel?.domain === d.slug && sel?.cap === c.slug ? "#ebf8ff" : "transparent",
                    fontSize: 14,
                  }}
                >
                  {c.name}{" "}
                  <span style={{ color: "#718096", fontSize: 12 }}>
                    ({c.canonical}/{c.total} canônicos)
                  </span>
                </div>
              ))}
            </div>
          ))}
        </div>

        <div style={{ flex: 1, minWidth: 320 }}>
          {sel && (
            <div style={{ ...card }}>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
                <button
                  style={btn}
                  onClick={() =>
                    verProjecao("Context Package (§61-§63)", `/context?capability=${sel.cap}&format=markdown`)
                  }
                >
                  Context Package
                </button>
                <button
                  style={btn}
                  onClick={() => verProjecao("BDD / Gherkin (§65)", `/projections/bdd?capability=${sel.cap}`)}
                >
                  BDD
                </button>
                <button
                  style={btn}
                  onClick={() =>
                    verProjecao("Documentação (§64)", `/projections/markdown?capability=${sel.cap}`)
                  }
                >
                  Doc Markdown
                </button>
              </div>
              {!detail && <p>Carregando…</p>}
              {detail &&
                Object.entries(detail.kinds).map(([kind, atoms]: [string, any]) => (
                  <div key={kind} style={{ marginBottom: 12 }}>
                    <h4 style={{ margin: "6px 0" }}>
                      {KIND_LABEL[kind] ?? kind} ({atoms.length})
                    </h4>
                    {atoms.map((a: any) => (
                      <Link
                        key={a.id}
                        href={`/atom/${encodeURIComponent(a.id)}`}
                        style={{ textDecoration: "none", color: "inherit" }}
                      >
                        <div
                          style={{
                            display: "flex",
                            gap: 8,
                            alignItems: "center",
                            padding: "5px 0",
                            borderBottom: "1px solid #f7fafc",
                            fontSize: 14,
                          }}
                        >
                          <StatusBadge status={a.status} />
                          <span style={{ flex: 1 }}>{a.title}</span>
                          <ConfidenceBar value={a.confidence} />
                        </div>
                      </Link>
                    ))}
                  </div>
                ))}
            </div>
          )}
          {proj && (
            <div style={card}>
              <div style={{ display: "flex", alignItems: "center" }}>
                <h3 style={{ margin: 0, flex: 1 }}>{proj.title}</h3>
                <button style={btn} onClick={() => setProj(null)}>
                  Fechar
                </button>
              </div>
              <pre
                style={{
                  background: "#f7fafc",
                  border: "1px solid #e2e8f0",
                  borderRadius: 8,
                  padding: 12,
                  overflowX: "auto",
                  fontSize: 13,
                  whiteSpace: "pre-wrap",
                }}
              >
                {proj.text}
              </pre>
            </div>
          )}
        </div>
      </div>
    </Shell>
  );
}
