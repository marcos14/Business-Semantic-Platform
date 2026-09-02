"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { get, post } from "@/lib/api";
import { Badge, Shell, btn, card } from "@/components/ui";

const TIPO: Record<string, string> = {
  review_needed: "Revisão necessária",
  decision_needed: "Decisão aguardando",
  canonical_challenged: "Canônico desafiado",
  mention: "Menção",
};

export default function NotificationsPage() {
  const [data, setData] = useState<any>(null);
  const reload = useCallback(() => {
    get("/notifications").then(setData).catch(() => {});
  }, []);
  useEffect(reload, [reload]);

  if (!data) return <Shell title="Notificações">Carregando…</Shell>;

  return (
    <Shell title={`Notificações (${data.unread} não lidas)`}>
      <button
        style={{ ...btn, marginBottom: 12 }}
        onClick={async () => {
          await post("/notifications/read-all");
          reload();
        }}
      >
        Marcar todas como lidas
      </button>
      {data.items.map((n: any) => (
        <div
          key={n.id}
          style={{ ...card, opacity: n.read ? 0.55 : 1, display: "flex", gap: 10, alignItems: "center" }}
        >
          <Badge text={TIPO[n.type] ?? n.type} color={n.read ? "#718096" : "#2b6cb0"} />
          <div style={{ flex: 1, fontSize: 14 }}>
            {n.atom_id ? (
              <Link href={`/atom/${encodeURIComponent(n.atom_id)}`}>{n.message}</Link>
            ) : (
              n.message
            )}
            <div style={{ fontSize: 11, color: "#a0aec0" }}>{n.at.slice(0, 16)}</div>
          </div>
          {!n.read && (
            <button
              style={{ ...btn, fontSize: 12 }}
              onClick={async () => {
                await post(`/notifications/${n.id}/read`);
                reload();
              }}
            >
              Lida
            </button>
          )}
        </div>
      ))}
    </Shell>
  );
}
