"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { get } from "@/lib/api";
import { Badge, Shell, card } from "@/components/ui";

export default function ConflictsPage() {
  const [state, setState] = useState("open");
  const [items, setItems] = useState<any[] | null>(null);

  useEffect(() => {
    get(`/conflicts?state=${state}`).then(setItems).catch(() => setItems([]));
  }, [state]);

  return (
    <Shell title="Conflitos">
      <div style={{ marginBottom: 14, display: "flex", gap: 8 }}>
        {["open", "resolved", "unresolved"].map((s) => (
          <button
            key={s}
            onClick={() => setState(s)}
            style={{
              padding: "6px 14px",
              borderRadius: 8,
              border: "1px solid #cbd5e0",
              background: state === s ? "#2b6cb0" : "#edf2f7",
              color: state === s ? "#fff" : "#4a5568",
              cursor: "pointer",
            }}
          >
            {s === "open" ? "Abertos" : s === "resolved" ? "Resolvidos" : "Não resolvidos"}
          </button>
        ))}
      </div>
      {items === null && <p>Carregando…</p>}
      {items?.length === 0 && <p style={{ color: "#718096" }}>Nenhum conflito {state === "open" ? "aberto" : ""}.</p>}
      {items?.map((c) => (
        <Link key={c.id} href={`/conflict/${encodeURIComponent(c.id)}`} style={{ textDecoration: "none", color: "inherit" }}>
          <div style={card}>
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <Badge text={c.reevaluation ? "reavaliação de canonical (§74)" : "conflito"} color="#c53030" />
              <span style={{ fontSize: 12, color: "#a0aec0" }}>
                {c.domain}
                {c.capability ? ` / ${c.capability}` : ""}
              </span>
            </div>
            <div style={{ fontWeight: 600, marginTop: 6 }}>{c.topic}</div>
            <div style={{ fontSize: 13, color: "#718096", marginTop: 4 }}>
              {c.about
                ? `Evidência contraditória sobre ${c.about}`
                : `${c.assertions.length} assertions em disputa`}
              {c.resolution ? ` · resolvido: ${c.resolution.action}` : ""}
            </div>
          </div>
        </Link>
      ))}
    </Shell>
  );
}
