"use client";

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import { get } from "@/lib/api";
import { Badge, Shell, btn, card } from "@/components/ui";

type Estado = "feito" | "andamento" | "pendente" | "automatico";

const COR: Record<Estado, string> = {
  feito: "#276749",
  andamento: "#2b6cb0",
  pendente: "#a0aec0",
  automatico: "#6b46c1",
};
const ROTULO: Record<Estado, string> = {
  feito: "feito",
  andamento: "em andamento",
  pendente: "pendente",
  automatico: "automático",
};

type Passo = {
  n: number;
  titulo: string;
  onde: { href: string; label: string }[];
  oQueFaz: ReactNode;
  valor: ReactNode;
  estado: Estado;
  situacao: string;
};

function Etapa({ p, atual }: { p: Passo; atual: boolean }) {
  return (
    <div
      id={`passo-${p.n}`}
      style={{
        ...card,
        borderLeft: `5px solid ${COR[p.estado]}`,
        boxShadow: atual ? "0 0 0 2px #2b6cb0, 0 1px 3px rgba(0,0,0,.08)" : card.boxShadow,
      }}
    >
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <span
          style={{
            width: 30, height: 30, borderRadius: 15, background: COR[p.estado], color: "#fff",
            display: "inline-flex", alignItems: "center", justifyContent: "center", fontWeight: 700,
          }}
        >
          {p.n}
        </span>
        <h3 style={{ margin: 0, flex: 1 }}>{p.titulo}</h3>
        {atual && <Badge text="você está aqui" color="#2b6cb0" />}
        <Badge text={ROTULO[p.estado]} color={COR[p.estado]} />
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginTop: 10, fontSize: 14 }}>
        <div>
          <div style={{ fontSize: 12, color: "#718096", fontWeight: 600, textTransform: "uppercase" }}>O que faz</div>
          <div style={{ marginTop: 4 }}>{p.oQueFaz}</div>
        </div>
        <div>
          <div style={{ fontSize: 12, color: "#718096", fontWeight: 600, textTransform: "uppercase" }}>Valor gerado</div>
          <div style={{ marginTop: 4 }}>{p.valor}</div>
        </div>
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 12, flexWrap: "wrap" }}>
        <span style={{ fontSize: 13, color: "#4a5568", flex: 1 }}>
          <strong>Situação:</strong> {p.situacao}
        </span>
        {p.onde.map((o) => (
          <Link key={o.href} href={o.href} style={{ ...btn, textDecoration: "none", fontSize: 13, padding: "6px 12px" }}>
            {o.label} →
          </Link>
        ))}
      </div>
    </div>
  );
}

export default function ManualPage() {
  const [d, setD] = useState<any>({});
  const [carregando, setCarregando] = useState(true);

  useEffect(() => {
    (async () => {
      const safe = (p: string) => get(p).catch(() => null);
      const [domains, caps, sources, batches, queue, coverage, conflicts, questions] = await Promise.all([
        safe("/admin/domains"),
        safe("/admin/capabilities"),
        safe("/sources"),
        safe("/discovery/batches"),
        safe("/discovery/queue"),
        safe("/metrics/coverage"),
        safe("/conflicts"),
        safe("/questions?answered=false"),
      ]);
      let inventario = { files: 0, files_with_capability: 0, suggestions: 0 };
      for (const s of (sources ?? []).slice(0, 5)) {
        const inv = await safe(`/sources/${s.id}/inventory/summary`);
        if (inv) {
          inventario.files += inv.files;
          inventario.files_with_capability += inv.files_with_capability;
          inventario.suggestions += inv.suggestions?.length ?? 0;
        }
      }
      setD({ domains, caps, sources, batches, queue, coverage, conflicts, questions, inventario });
      setCarregando(false);
    })();
  }, []);

  const admin = d.domains !== null && d.domains !== undefined;
  const nDom = d.domains?.length ?? 0;
  const nCap = d.caps?.length ?? 0;
  const nSrc = (d.sources ?? []).filter((s: any) => s.repository).length;
  const inv = d.inventario ?? { files: 0, files_with_capability: 0, suggestions: 0 };
  const batches: any[] = d.batches ?? [];
  const invAtivas = batches.filter((b) => b.agent === "inventory" && b.active).length;
  const campAtivas = batches.filter((b) => b.agent !== "inventory" && b.active).length;
  const campTotal = batches.filter((b) => b.agent !== "inventory").length;
  const cov = d.coverage ?? {};
  const candidates = cov.candidate_atoms ?? 0;
  const canonicos = cov.canonical_atoms ?? 0;
  const autoAprov = cov.auto_approved_atoms ?? 0;
  const revisados = cov.human_reviewed_atoms ?? 0;
  const conflitos = (d.conflicts ?? []).length;
  const perguntas = (d.questions ?? []).length;
  const esperando = d.queue?.scheduled_future ?? 0;

  const passos: Passo[] = [
    {
      n: 1,
      titulo: "Cadastrar domains e capabilities",
      onde: [{ href: "/admin", label: "Admin" }],
      oQueFaz: (
        <>
          Define o vocabulário de negócio: <em>domain</em> é a área (ex.: ERP financeiro) e{" "}
          <em>capability</em> é a unidade de negócio dentro dela (ex.: nota fiscal, caixa). A descrição
          de cada capability vai no prompt dos agentes.
        </>
      ),
      valor: (
        <>
          Sem isso o agente não sabe o que procurar. Com isso, tudo que for extraído já nasce
          classificado, com dono e política de aprovação por área.
        </>
      ),
      estado: !admin ? "pendente" : nCap > 0 ? "feito" : nDom > 0 ? "andamento" : "pendente",
      situacao: !admin
        ? "requer administrador para consultar"
        : `${nDom} domain(s) e ${nCap} capability(ies) cadastradas`,
    },
    {
      n: 2,
      titulo: "Registrar a source",
      onde: [{ href: "/sources", label: "Sources" }],
      oQueFaz: (
        <>
          Aponta o repositório legado (pode ser um subdiretório do git). Toda evidência extraída
          referencia essa source, o arquivo, as linhas e o commit.
        </>
      ),
      valor: <>Rastreabilidade total: qualquer regra pode ser conferida na fonte original.</>,
      estado: nSrc > 0 ? "feito" : "pendente",
      situacao: `${nSrc} source(s) com repositório`,
    },
    {
      n: 3,
      titulo: "Inventário dos fontes",
      onde: [
        { href: "/sources", label: "Disparar em Sources" },
        { href: "/discovery", label: "Acompanhar em Discovery" },
      ],
      oQueFaz: (
        <>
          Lê cada arquivo-fonte em lotes e produz, por arquivo, um resumo em linguagem de negócio e a
          ligação com as capabilities, com relevância de 1 a 3. Áreas encontradas sem capability
          cadastrada viram sugestões.
        </>
      ),
      valor: (
        <>
          Um mapa do sistema em termos de negócio, não de pastas. É o que permite os passos seguintes
          serem <strong>dirigidos</strong>: o agente vai direto aos arquivos certos em vez de vagar por
          milhares de fontes gastando budget. Também revela capabilities que ninguém tinha listado.
        </>
      ),
      estado: invAtivas > 0 ? "andamento" : inv.files > 0 ? "feito" : "pendente",
      situacao: `${inv.files} arquivo(s) inventariado(s), ${inv.files_with_capability} ligados a capabilities, ${inv.suggestions} capability(ies) sugerida(s)` +
        (invAtivas ? ` · ${invAtivas} inventário(s) em andamento` : "") +
        (esperando ? ` · ${esperando} job(s) esperando reset da franquia` : ""),
    },
    {
      n: 4,
      titulo: "Discovery dirigido (campanha por capability)",
      onde: [
        { href: "/sources", label: "Disparar em Sources" },
        { href: "/discovery", label: "Acompanhar em Discovery" },
      ],
      oQueFaz: (
        <>
          Para uma capability, cada arquivo inventariado vira um turno do agente com o conteúdo
          numerado no prompt. Ele extrai regras, invariantes, decisões, estados e cenários, sempre com
          evidência de arquivo e linhas, e pode pedir follow-ups em arquivos relacionados.
        </>
      ),
      valor: (
        <>
          Os <em>candidates</em>: afirmações de negócio em português, cada uma amarrada a linhas
          reais do código. O kernel verifica cada citação e rejeita o que não existe, então nada
          alucinado entra na base.
        </>
      ),
      estado: campAtivas > 0 ? "andamento" : campTotal > 0 || candidates > 0 ? "feito" : "pendente",
      situacao: `${campTotal} campanha(s), ${campAtivas} em andamento · ${candidates} candidate(s) na base`,
    },
    {
      n: 5,
      titulo: "Avaliação automática de confiança",
      onde: [{ href: "/dashboard", label: "Dashboard" }],
      oQueFaz: (
        <>
          Sem tela e sem LLM: após cada run, o kernel valida o candidate, o confidence engine pontua
          pelas evidências (tipos, independência, testes, revisão humana) e a política do domain
          define o threshold. Acima dele, aprovação automática; abaixo, vai para revisão humana.
        </>
      ),
      valor: (
        <>
          Humanos só onde a máquina não tem certeza. O score é explicável: cada sinal que compôs a
          nota fica registrado.
        </>
      ),
      estado: candidates + autoAprov + canonicos > 0 ? "automatico" : "pendente",
      situacao: `${autoAprov} auto-aprovado(s) até agora`,
    },
    {
      n: 6,
      titulo: "Governança humana",
      onde: [
        { href: "/inbox", label: "Inbox" },
        { href: "/kanban", label: "Kanban" },
      ],
      oQueFaz: (
        <>
          Reviewers votam, domain experts comentam e o decision owner decide, por capability. A tela
          mostra primeiro a tradução de negócio, depois o resumo e só então o código.
        </>
      ),
      valor: (
        <>
          Decisões com autoridade e registro. O conhecimento canônico passa a ter dono, e cada
          aprovação ou rejeição fica auditável para sempre.
        </>
      ),
      estado: revisados > 0 ? "andamento" : "pendente",
      situacao: `${revisados} candidate(s) já revisado(s) por humanos`,
    },
    {
      n: 7,
      titulo: "Conflitos e questions",
      onde: [
        { href: "/conflicts", label: "Conflitos" },
        { href: "/questions", label: "Questions" },
      ],
      oQueFaz: (
        <>
          Regras que se contradizem viram um conflito com espaço de resolução. Dúvidas que o agente
          não conseguiu resolver viram questions para alguém do negócio responder.
        </>
      ),
      valor: (
        <>
          Ambiguidade explícita em vez de escondida. O que hoje só existe na cabeça de alguém vira
          pergunta registrada com resposta rastreável.
        </>
      ),
      estado: conflitos + perguntas > 0 ? "andamento" : "pendente",
      situacao: `${conflitos} conflito(s) aberto(s) · ${perguntas} question(s) sem resposta`,
    },
    {
      n: 8,
      titulo: "Conhecimento canônico e consumo",
      onde: [
        { href: "/explorer", label: "Explorer" },
        { href: "/dashboard", label: "Dashboard" },
      ],
      oQueFaz: (
        <>
          O que foi aprovado vira canônico e é exportado em YAML para um repositório git dedicado.
          O Explorer navega por domain e capability; a API entrega contexto, projeções BDD,
          tabelas de decisão e markdown para pessoas, sistemas e outros agentes.
        </>
      ),
      valor: (
        <>
          A fonte de verdade do negócio, versionada e consultável, separada do código legado. É o
          insumo para reescrever, testar ou explicar o sistema sem depender de quem o fez.
        </>
      ),
      estado: canonicos > 0 ? "andamento" : "pendente",
      situacao: `${canonicos} atom(s) canônico(s) publicados`,
    },
    {
      n: 9,
      titulo: "Corroboração (opcional, contínua)",
      onde: [{ href: "/sources", label: "Varredura livre em Sources" }],
      oQueFaz: (
        <>
          Outro agente busca, de forma independente, evidência que sustente ou contradiga os
          candidates existentes. Evidência de arquivo diferente conta como fonte independente.
        </>
      ),
      valor: (
        <>
          Sobe a confiança dos candidates fracos sem trabalho humano e reabre o roteamento
          automático do que ainda não foi votado.
        </>
      ),
      estado: "pendente",
      situacao: "dispare quando houver candidates aguardando revisão em volume",
    },
  ];

  const atual = passos.find((p) => p.estado === "andamento")?.n ?? passos.find((p) => p.estado === "pendente")?.n ?? 8;

  return (
    <Shell title="Manual · o que a plataforma faz e onde você está">
      <div style={{ ...card, background: "#ebf8ff", border: "1px solid #90cdf4" }}>
        <h3 style={{ marginTop: 0 }}>O conceito em um parágrafo</h3>
        <p style={{ margin: 0, fontSize: 14, lineHeight: 1.55 }}>
          A Business Semantic Platform reconstrói o <strong>conhecimento de negócio</strong> que está
          preso dentro de sistemas legados. Agentes de IA leem o código e <em>propõem</em> regras,
          decisões e cenários, sempre com evidência de arquivo e linhas. Um núcleo determinístico
          valida cada proposta, calcula uma confiança explicável e decide o que pode ser aprovado
          sozinho e o que precisa de gente. Humanos revisam só o necessário, resolvem conflitos e
          respondem dúvidas. O resultado é um repositório canônico, versionado e consultável, do que o
          sistema realmente faz, em português e sem depender de quem o programou.
        </p>
        <div style={{ display: "flex", gap: 14, marginTop: 10, fontSize: 13, flexWrap: "wrap" }}>
          <span><strong>Princípio 1:</strong> o agente propõe, o kernel decide.</span>
          <span><strong>Princípio 2:</strong> nada entra sem evidência verificável.</span>
          <span><strong>Princípio 3:</strong> humanos onde a máquina não tem certeza.</span>
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 10, margin: "18px 0 8px", flexWrap: "wrap" }}>
        <h2 style={{ fontSize: 18, margin: 0, flex: 1 }}>Os passos, na ordem</h2>
        {carregando ? (
          <span style={{ fontSize: 13, color: "#718096" }}>lendo a situação atual…</span>
        ) : (
          <span style={{ fontSize: 13, color: "#4a5568" }}>
            Você está no <strong>passo {atual}</strong>: {passos[atual - 1].titulo}
          </span>
        )}
      </div>

      <div style={{ display: "flex", gap: 4, marginBottom: 14 }}>
        {passos.map((p) => (
          <a
            key={p.n}
            href={`#passo-${p.n}`}
            title={`${p.n}. ${p.titulo} — ${ROTULO[p.estado]}`}
            style={{
              flex: 1, height: 10, borderRadius: 5, background: COR[p.estado],
              outline: p.n === atual ? "2px solid #1a202c" : "none", outlineOffset: 1,
            }}
          />
        ))}
      </div>

      {passos.map((p) => (
        <Etapa key={p.n} p={p} atual={!carregando && p.n === atual} />
      ))}

      <div style={{ ...card, marginTop: 18 }}>
        <h3 style={{ marginTop: 0 }}>Como o trabalho flui por trás das telas</h3>
        <pre style={{ margin: 0, fontSize: 12, lineHeight: 1.5, overflowX: "auto", background: "#f7fafc", padding: 10, borderRadius: 6 }}>
{`código legado ──inventário──▶ mapa arquivo × capability
                                    │
                            campanha dirigida (1 turno por arquivo)
                                    ▼
                    candidates + evidence (arquivo, linhas, commit)
                                    │  kernel verifica cada citação
                                    ▼
                confidence engine ──▶ acima do threshold ──▶ CANONICAL ──▶ YAML/Git ──▶ Explorer, API,
                        │                                                              projeções BDD
                        └── abaixo ──▶ Inbox / Kanban ──▶ votos e decisão ──▶ CANONICAL ou REJECTED
                                             │
                                  conflitos e questions resolvidos por pessoas`}
        </pre>
        <p style={{ fontSize: 13, color: "#4a5568", marginBottom: 0 }}>
          O harness de IA roda no seu computador, com o CLI <code>claude</code> logado, consumindo a
          fila <code>discovery</code>. Quando a franquia da conta acaba, os jobs esperam o horário de
          reset e uma sondagem a cada 10 minutos os libera assim que houver crédito. O botão
          "Liberar agora" em Discovery faz isso na hora, útil quando você troca de conta.
        </p>
      </div>
    </Shell>
  );
}
