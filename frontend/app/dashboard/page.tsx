"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { get } from "@/lib/api";
import { Shell, card } from "@/components/ui";

function Tile({ n, label }: { n: any; label: string }) {
  return (
    <div style={{ ...card, flex: 1, minWidth: 150, marginBottom: 0, textAlign: "center" }}>
      <div style={{ fontSize: 26, fontWeight: 700 }}>{n ?? "—"}</div>
      <div style={{ color: "#718096", fontSize: 12 }}>{label}</div>
    </div>
  );
}

export default function DashboardPage() {
  const [inbox, setInbox] = useState<any>(null);
  const [cov, setCov] = useState<any[] | null>(null);
  const [dist, setDist] = useState<any>(null);
  const [kpi, setKpi] = useState<any>(null);
  const [audit, setAudit] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);

  useEffect(() => {
    get("/reviews/inbox").then(setInbox).catch(() => {});
    get("/metrics/coverage-by-capability").then(setCov).catch(() => {});
    get("/metrics/confidence-distribution").then(setDist).catch(() => {});
    get("/metrics/attention").then(setKpi).catch(() => {});
    get("/metrics/audit").then(setAudit).catch(() => {});
    get("/metrics/recent-events?limit=12").then(setEvents).catch(() => {});
  }, []);

  const pct = (v: number | null) => (v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`);
  const maxBucket = dist ? Math.max(1, ...Object.values(dist.buckets).map(Number)) : 1;

  return (
    <Shell title="Dashboard">
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 16 }}>
        <Tile n={inbox?.summary?.awaiting_review} label="aguardando revisão" />
        <Tile n={inbox?.summary?.needs_decision} label="decisões suas" />
        <Tile n={inbox?.summary?.with_conflicts} label="itens com conflito" />
        <Tile n={pct(kpi?.automation_rate)} label="automation rate (§79)" />
        <Tile n={pct(kpi?.false_auto_approval_rate)} label="false auto-approval (§80)" />
        <Tile n={kpi?.median_review_latency_min != null ? `${kpi.median_review_latency_min}m` : "—"} label="mediana até decisão (§78)" />
      </div>

      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-start" }}>
        <div style={{ ...card, flex: 2, minWidth: 340 }}>
          <h3 style={{ marginTop: 0 }}>Coverage por capability (§75/§107)</h3>
          <table style={{ borderCollapse: "collapse", fontSize: 13, width: "100%" }}>
            <thead>
              <tr>
                {["capability", "total", "canônicos", "candidates", "conflitos", "questions"].map(
                  (h) => (
                    <th key={h} style={{ textAlign: "left", padding: 6, borderBottom: "2px solid #e2e8f0" }}>
                      {h}
                    </th>
                  )
                )}
              </tr>
            </thead>
            <tbody>
              {cov?.map((r) => (
                <tr key={`${r.domain}-${r.capability}`}>
                  <td style={{ padding: 6, borderBottom: "1px solid #f7fafc" }}>
                    {r.domain}/{r.capability ?? "—"}
                  </td>
                  <td style={{ padding: 6 }}>{r.total}</td>
                  <td style={{ padding: 6, color: "#276749", fontWeight: 600 }}>{r.canonical}</td>
                  <td style={{ padding: 6 }}>{r.candidates}</td>
                  <td style={{ padding: 6, color: r.open_conflicts ? "#c53030" : "#a0aec0" }}>
                    {r.open_conflicts}
                  </td>
                  <td style={{ padding: 6 }}>{r.open_questions}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div style={{ ...card, flex: 1, minWidth: 260 }}>
          <h3 style={{ marginTop: 0 }}>Distribuição de confidence (§76)</h3>
          {dist &&
            Object.entries(dist.buckets).map(([faixa, n]: [string, any]) => (
              <div key={faixa} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                <span style={{ width: 52, fontSize: 12, color: "#718096" }}>{faixa}%</span>
                <div style={{ flex: 1, background: "#edf2f7", borderRadius: 4, height: 14 }}>
                  <div
                    style={{
                      width: `${(Number(n) / maxBucket) * 100}%`,
                      height: 14,
                      borderRadius: 4,
                      background: faixa.startsWith("9") ? "#276749" : "#2b6cb0",
                    }}
                  />
                </div>
                <span style={{ width: 24, fontSize: 12 }}>{n}</span>
              </div>
            ))}
          {dist && (
            <p style={{ fontSize: 12, color: "#718096" }}>
              {pct(dist.pct_auto_approved)} auto-aprovados · {pct(dist.pct_needs_human)} para humanos
            </p>
          )}
          {audit && (
            <>
              <h3>Audit (§109)</h3>
              <ul style={{ fontSize: 13, paddingLeft: 18 }}>
                <li>{audit.auto_approved} auto-aprovadas</li>
                <li>{audit.human_approved} aprovadas por owner</li>
                <li>{audit.rejected} rejeitadas por owner</li>
                <li style={{ color: audit.reopened_canonical ? "#c53030" : "inherit" }}>
                  {audit.reopened_canonical} canonical desafiadas
                </li>
              </ul>
            </>
          )}
        </div>
      </div>

      <div style={card}>
        <h3 style={{ marginTop: 0 }}>Mudanças recentes (§107)</h3>
        {events.map((e, i) => (
          <div key={i} style={{ fontSize: 13, padding: "4px 0", borderBottom: "1px solid #f7fafc" }}>
            <span style={{ color: "#a0aec0" }}>{e.at.slice(5, 16)}</span>{" "}
            <strong>{e.type}</strong> por {e.actor}{" "}
            {e.atom_id && (
              <Link href={`/atom/${encodeURIComponent(e.atom_id)}`}>{e.atom_id}</Link>
            )}
          </div>
        ))}
      </div>
    </Shell>
  );
}
