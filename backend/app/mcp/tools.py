"""As tools da plataforma, agrupadas por área. Cada uma é uma chamada (ou composição de
chamadas) à API HTTP, com o RBAC do usuário autenticado.

Grupos: meta · admin · sources · discovery · knowledge · reviews · conflicts · questions ·
consume · metrics · helpdesk · notifications.

As tools do grupo ``meta`` (``platform_overview``, ``source_progress``) são compostas: cruzam
várias consultas e devolvem alertas e próximos passos — é o que faz o assistente ser um
especialista em andamento, e não só um proxy da API.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from typing import Annotated, Any, Literal

from pydantic import Field

from app.mcp.client import BspApiError, BspClient
from app.mcp.registry import ToolRegistry

registry = ToolRegistry()


def desc(text: str) -> Any:
    return Field(description=text)


# ---------- vocabulário (mesmos valores dos enums do kernel) ----------

AtomKind = Literal[
    "concept", "rule", "decision", "invariant", "state", "transition", "event", "process",
    "scenario", "exception", "conflict", "question", "capability", "message", "procedure",
]
Status = Literal[
    "DISCOVERED", "CANDIDATE", "CORROBORATING", "READY_FOR_EVALUATION", "AUTO_APPROVED",
    "PROVISIONAL", "NEEDS_HUMAN_REVIEW", "IN_REVIEW", "DECISION_PENDING", "CANONICAL",
    "REJECTED", "SUPERSEDED", "CONFLICTED", "UNKNOWN", "LEGACY_BUG",
]
Classification = Literal[
    "OBSERVED_BEHAVIOR", "INTENDED_BEHAVIOR", "MANDATED_BEHAVIOR", "LEGACY_QUIRK",
    "KNOWN_BUG", "DEPRECATED_BEHAVIOR", "UNKNOWN",
]
Risk = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
Significance = Literal["SYSTEMIC", "LOW", "MEDIUM", "HIGH"]
EvidenceType = Literal[
    "SOURCE_CODE", "TEST", "DOCUMENT", "DATABASE", "RUNTIME", "API", "UI", "CONFIGURATION",
    "HUMAN_REVIEW", "DOMAIN_EXPERT", "EXTERNAL_RULE",
]
RelationType = Literal[
    "DEPENDS_ON", "AFFECTS", "USED_BY", "GOVERNS", "TRIGGERS", "PRODUCES", "CONSUMES",
    "EXEMPLIFIED_BY", "CONTRADICTS", "SUPERSEDES", "VARIANT_OF", "INDICATES", "RESOLVED_BY",
    "APPLIES_TO",
]
SourceType = Literal[
    "source_code", "automated_test", "documentation", "database_schema", "api",
    "configuration", "runtime_trace", "manual", "ticket", "human_input",
]
Role = Literal["viewer", "reviewer", "domain_expert", "decision_owner", "administrator"]
ReviewAction = Literal[
    "CONFIRM", "REJECT", "CONFIRM_WITH_EXCEPTION", "OBSERVED_ONLY", "LEGACY_BUG",
    "NEEDS_MORE_EVIDENCE", "NEEDS_SPECIALIST", "NOT_MY_DOMAIN",
]
DecisionAction = Literal[
    "APPROVE", "REJECT", "RECLASSIFY", "MARK_KNOWN_BUG", "REQUEST_EVIDENCE", "ADD_EXCEPTION"
]
ConflictAction = Literal[
    "SELECT_ASSERTION", "NEW_INTERPRETATION", "SPLIT_BY_SCOPE", "SPLIT_BY_TIME",
    "MARK_LEGACY_BUG", "MARK_UNRESOLVED", "REQUEST_EVIDENCE",
]
ConsumerProfile = Literal[
    "helpdesk_direct", "helpdesk_copilot_n1", "helpdesk_copilot_n2", "helpdesk_copilot_n3"
]
FeedbackOutcome = Literal[
    "RESOLVED", "PARTIALLY_RESOLVED", "ESCALATED", "REOPENED", "INCORRECT", "ABANDONED",
    "UNKNOWN",
]
PolicyScope = Literal["global", "domain", "atom_kind", "significance", "capability", "risk"]
HelpdeskScope = Literal[
    "global", "consumer_profile", "domain", "capability", "classification", "significance",
    "risk",
]

PENDING_STATUSES = {
    "DISCOVERED", "CANDIDATE", "CORROBORATING", "READY_FOR_EVALUATION", "NEEDS_HUMAN_REVIEW",
    "IN_REVIEW", "DECISION_PENDING", "CONFLICTED", "UNKNOWN",
}


def _safe(sections: dict, key: str, fn: Callable[[], Any]) -> Any:
    """Executa uma consulta de um relatório composto; erro de uma seção não derruba as outras."""
    try:
        sections[key] = fn()
    except BspApiError as e:
        sections[key] = {"error": f"HTTP {e.status}: {e.detail}"}
    return sections[key]


def _ok(value: Any) -> bool:
    return not (isinstance(value, dict) and "error" in value)


# =====================================================================
# meta — identidade e visão de andamento (compostas)
# =====================================================================


@registry.tool(
    "whoami",
    "Quem sou eu na plataforma: e-mail, nome e papéis (role bindings) por domain/capability. "
    "Chame antes de ações administrativas para saber o que o usuário atual pode fazer.",
    group="meta",
)
def whoami(client: BspClient) -> Any:
    return client.get("/auth/me")


@registry.tool(
    "platform_overview",
    """Visão geral do andamento da plataforma em UMA chamada: sources cadastradas, campanhas de
    discovery ativas, estado da fila e dos workers, inbox de revisão, cobertura semântica, KPIs
    de atenção humana, conflitos e questions abertos, eventos recentes — mais uma lista de
    ALERTAS já interpretados. Comece por aqui quando perguntarem "como está o andamento?".""",
    group="meta",
)
def platform_overview(
    client: BspClient,
    domain: Annotated[str | None, desc("restringe métricas a um domain (slug)")] = None,
) -> Any:
    s: dict[str, Any] = {}
    _safe(s, "me", lambda: client.get("/auth/me"))
    _safe(s, "sources", lambda: client.get("/sources"))
    _safe(s, "batches", lambda: client.get("/discovery/batches", limit=200))
    _safe(s, "queue", lambda: client.get("/discovery/queue", limit=5))
    _safe(s, "inbox", lambda: client.get("/reviews/inbox"))
    _safe(s, "coverage", lambda: client.get("/metrics/coverage", domain=domain))
    _safe(s, "attention", lambda: client.get("/metrics/attention", domain=domain))
    _safe(s, "conflicts", lambda: client.get("/conflicts", domain=domain, state="open"))
    _safe(s, "questions", lambda: client.get("/questions", domain=domain, answered=False))
    _safe(s, "events", lambda: client.get("/metrics/recent-events", limit=10))

    alerts: list[str] = []
    sources = s["sources"] if _ok(s["sources"]) else []
    if _ok(s["sources"]):
        if not sources:
            alerts.append("Nenhuma source cadastrada: comece por create_source.")
        elif domain:
            sources = [x for x in sources if x.get("domain_slug") in (None, domain)]

    batches = s["batches"] if _ok(s["batches"]) else []
    if domain:
        batches = [b for b in batches if b.get("domain") == domain]
    active = [b for b in batches if b.get("active")]
    failed = sum(int(b.get("failed") or 0) for b in batches)
    blocked = sum(int(b.get("blocked") or 0) for b in batches)
    if failed:
        alerts.append(f"{failed} run(s) de discovery falharam; veja list_discovery_runs.")
    if blocked:
        alerts.append(
            f"{blocked} run(s) bloqueados por franquia/autenticação do `claude`; "
            "após trocar a conta ou o reset, use release_queue."
        )

    queue = s["queue"] if _ok(s["queue"]) else {}
    if queue:
        if queue.get("schema_missing"):
            alerts.append("Fila do Procrastinate sem schema: nenhum worker subiu ainda.")
        elif queue.get("pending", 0) and not queue.get("workers_alive", 0):
            alerts.append(
                f"{queue['pending']} job(s) pendentes na fila discovery e NENHUM worker vivo: "
                "suba o worker no host (uv run procrastinate --app=app.jobs.job_app worker "
                "--queues discovery)."
            )
        elif (
            queue.get("pending", 0)
            and not queue.get("running", 0)
            and not queue.get("scheduled_future", 0)
        ):
            alerts.append(
                f"{queue['pending']} job(s) pendentes na fila discovery sem nenhum em execução: o "
                "worker vivo pode ser só o do container (fila default); confirme o worker da fila "
                "discovery no host."
            )
        if queue.get("scheduled_future"):
            alerts.append(
                f"{queue['scheduled_future']} job(s) reagendados para depois "
                f"(próximo: {queue.get('next_scheduled_at')}), tipicamente esperando a "
                "franquia do harness."
            )

    inbox = s["inbox"] if _ok(s["inbox"]) else {}
    summary = inbox.get("summary", {}) if inbox else {}
    if summary.get("needs_decision"):
        alerts.append(f"{summary['needs_decision']} atom(s) aguardam SUA decisão (decision owner).")
    if summary.get("awaiting_review"):
        alerts.append(f"{summary['awaiting_review']} atom(s) aguardam revisão humana.")
    if summary.get("canonical_challenged"):
        alerts.append(f"{summary['canonical_challenged']} canônico(s) desafiados por conflito.")

    conflicts = s["conflicts"] if _ok(s["conflicts"]) else []
    if conflicts:
        alerts.append(f"{len(conflicts)} conflito(s) abertos aguardam resolução.")
    questions = s["questions"] if _ok(s["questions"]) else []
    if questions:
        alerts.append(f"{len(questions)} question(s) sem resposta para o domain expert.")

    return {
        "user": {
            "email": s["me"].get("email"),
            "name": s["me"].get("name"),
            "bindings": s["me"].get("bindings"),
        }
        if _ok(s["me"])
        else s["me"],
        "sources": {
            "total": len(sources),
            "items": [
                {
                    "id": x["id"], "name": x["name"], "type": x["type"],
                    "domain": x.get("domain_slug"), "has_repository": bool(x.get("repository")),
                }
                for x in sources
            ],
        }
        if _ok(s["sources"])
        else s["sources"],
        "discovery": {
            "active_batches": [
                {
                    "batch_id": b["batch_id"], "agent": b["agent"], "domain": b["domain"],
                    "capability": b.get("capability"), "done": b.get("done"),
                    "total": b.get("total"), "candidates": b.get("candidates"),
                    "cost_usd": b.get("cost_usd"),
                }
                for b in active
            ],
            "batches_total": len(batches),
            "failed_runs": failed,
            "blocked_runs": blocked,
            "queue": {
                k: queue.get(k)
                for k in (
                    "pending", "running", "workers_alive", "scheduled_future",
                    "next_scheduled_at", "schema_missing",
                )
            }
            if queue
            else s["queue"],
        },
        "inbox_summary": summary or s["inbox"],
        "inbox_top": [
            {
                "id": i.get("id"), "title": i.get("title"), "status": i.get("status"),
                "risk": i.get("risk"), "confidence": i.get("confidence"),
                "priority": (i.get("priority") or {}).get("score"),
            }
            for i in (inbox.get("items", []) if inbox else [])[:5]
        ],
        "coverage": s["coverage"],
        "attention": s["attention"],
        "open_conflicts": len(conflicts) if _ok(s["conflicts"]) else s["conflicts"],
        "open_questions": len(questions) if _ok(s["questions"]) else s["questions"],
        "recent_events": s["events"],
        "alerts": alerts,
    }


def _relevant_files(cap: dict) -> int:
    rel = cap.get("by_relevance") or {}
    return int(rel.get(2, rel.get("2", 0)) or 0) + int(rel.get(3, rel.get("3", 0)) or 0)


@registry.tool(
    "source_progress",
    """Andamento de UMA source legada: cadastro, inventário (arquivos por capability e
    capabilities sugeridas sem cadastro), campanhas (inventário/dirigidas) com progresso e
    custo, runs por status/agente, cobertura por capability do domain e uma lista de PRÓXIMOS
    PASSOS recomendados. Use para responder "o que falta fazer nesta source?".""",
    group="meta",
)
def source_progress(
    client: BspClient,
    source_id: Annotated[str, desc("id (UUID) da source; veja list_sources")],
) -> Any:
    s: dict[str, Any] = {}
    src = client.get(f"/sources/{source_id}")
    _safe(s, "inventory", lambda: client.get(f"/sources/{source_id}/inventory/summary"))
    _safe(s, "batches", lambda: client.get("/discovery/batches", limit=200))
    _safe(s, "runs", lambda: client.get("/discovery/runs", limit=500))
    domain = src.get("domain_slug")
    if domain:
        _safe(s, "coverage", lambda: client.get("/metrics/coverage-by-capability", domain=domain))

    batches = [
        b for b in (s["batches"] if _ok(s["batches"]) else []) if b.get("source_id") == source_id
    ]
    runs = [r for r in (s["runs"] if _ok(s["runs"]) else []) if r.get("source_id") == source_id]
    by_status = Counter(r["status"] for r in runs)
    by_agent = Counter(r["agent"] for r in runs)
    errors = []
    for r in runs:
        if r.get("error") and r["error"] not in errors:
            errors.append(r["error"])
        if len(errors) >= 3:
            break
    runs_stats = {
        "total": len(runs),
        "by_status": dict(by_status),
        "by_agent": dict(by_agent),
        "cost_usd": round(sum(float(r.get("cost_usd") or 0) for r in runs), 2),
        "candidates_created": sum(int(r.get("candidates_created") or 0) for r in runs),
        "reinforcements": sum(int(r.get("reinforcements") or 0) for r in runs),
        "questions_created": sum(int(r.get("questions_created") or 0) for r in runs),
        "evidence_rejected": sum(int(r.get("evidence_rejected") or 0) for r in runs),
        "last_run_at": max((r.get("started_at") or "" for r in runs), default=None),
        "errors_sample": errors,
    }
    inv = s["inventory"] if _ok(s["inventory"]) else {}
    coverage = s.get("coverage") if _ok(s.get("coverage", {})) else []

    steps: list[str] = []
    if not src.get("repository"):
        steps.append(
            "A source não tem `repository`: inventário e discovery exigem código-fonte no host."
        )
    if not domain:
        steps.append("A source não está ligada a um domain (domain_slug): informe-o no cadastro.")
    active = [b for b in batches if b.get("active")]
    if active:
        steps.append(
            f"{len(active)} campanha(s) em andamento; acompanhe com list_batches/queue_status "
            "antes de disparar novas."
        )
    if sum(int(b.get("blocked") or 0) for b in batches):
        steps.append(
            "Há runs bloqueados por franquia/autenticação do `claude`: verifique a conta no host "
            "e use release_queue quando os créditos voltarem."
        )
    if src.get("repository") and inv:
        if not inv.get("files"):
            steps.append("Nenhum arquivo inventariado: rode start_inventory(source_id, domain).")
        else:
            sugestoes = inv.get("suggestions") or []
            if sugestoes:
                nomes = ", ".join(x["name"] for x in sugestoes[:5])
                steps.append(
                    f"{len(sugestoes)} capability(ies) sugeridas pelo inventário sem cadastro "
                    f"({nomes}): crie-as com create_capability e re-rode start_inventory "
                    "(only_missing) para ligar os arquivos."
                )
            com_campanha = {b.get("capability") for b in batches if b.get("agent") != "inventory"}
            pendentes = [
                c for c in (inv.get("capabilities") or [])
                if c["slug"] not in com_campanha and _relevant_files(c) > 0
            ]
            if pendentes:
                top = sorted(pendentes, key=lambda c: -_relevant_files(c))[:4]
                steps.append(
                    "Capabilities inventariadas ainda sem campanha dirigida: "
                    + ", ".join(
                        f"{c['slug']} ({_relevant_files(c)} arquivos relevantes)" for c in top
                    )
                    + ". Dispare start_campaign para cada uma."
                )
            files = int(inv.get("files") or 0)
            if files and int(inv.get("files_without_capability") or 0) > files / 2:
                steps.append(
                    "Mais da metade dos arquivos não se ligou a nenhuma capability: revise as "
                    "descrições das capabilities (update_capability) — elas orientam o inventário."
                )
    if by_status.get("failed"):
        steps.append(
            f"{by_status['failed']} run(s) falharam; veja errors_sample e get_discovery_run."
        )
    if coverage:
        pend = sum(int(r.get("candidates") or 0) for r in coverage)
        if pend:
            steps.append(
                f"{pend} candidate(s) do domain aguardam funil/revisão: review_inbox, "
                "triage_pending e reroute_pending; start_evidence_search corrobora os que ainda "
                "não atingiram a faixa."
            )
    if not steps:
        steps.append("Nada pendente nesta source: acompanhe a inbox e as métricas de cobertura.")

    return {
        "source": src,
        "inventory": s["inventory"],
        "batches": batches,
        "runs": runs_stats,
        "coverage_by_capability": coverage,
        "next_steps": steps,
    }


# =====================================================================
# admin — usuários, domains, capabilities, papéis, políticas
# =====================================================================


@registry.tool("list_users", "Lista os usuários (id, e-mail, nome, ativo). Só administrador.",
               group="admin")
def list_users(client: BspClient) -> Any:
    return client.get("/admin/users")


@registry.tool(
    "create_user",
    "Cria um usuário. Ele nasce sem papéis: use grant_role em seguida. Só administrador.",
    group="admin", mutating=True,
)
def create_user(
    client: BspClient,
    email: Annotated[str, desc("e-mail (vira login)")],
    name: Annotated[str, desc("nome de exibição")],
    password: Annotated[str, desc("senha inicial (mínimo 8 caracteres)")],
) -> Any:
    return client.post("/admin/users", {"email": email, "name": name, "password": password})


@registry.tool(
    "update_user",
    "Altera nome, situação (ativo/inativo) e/ou senha de um usuário. Só administrador.",
    group="admin", mutating=True, idempotent=True,
)
def update_user(
    client: BspClient,
    user_id: Annotated[str, desc("id (UUID) do usuário; veja list_users")],
    name: Annotated[str | None, desc("novo nome")] = None,
    active: Annotated[bool | None, desc("false desativa o login (não apaga nada)")] = None,
    password: Annotated[str | None, desc("nova senha (mínimo 8)")] = None,
) -> Any:
    body = {k: v for k, v in {"name": name, "active": active, "password": password}.items()
            if v is not None}
    return client.patch(f"/admin/users/{user_id}", body)


@registry.tool("list_domains", "Lista os domains (slug, nome, perfil de evidência).",
               group="admin")
def list_domains(client: BspClient) -> Any:
    return client.get("/admin/domains")


@registry.tool(
    "create_domain",
    "Cria um domain de negócio (ex.: finance). evidence_profile: default | legacy-hostile "
    "(ERP antigo sem docs/testes confiáveis). Só administrador.",
    group="admin", mutating=True,
)
def create_domain(
    client: BspClient,
    slug: Annotated[str, desc("slug: minúsculas, números e hífens")],
    name: Annotated[str, desc("nome de exibição")],
    evidence_profile: Annotated[str | None, desc("default | legacy-hostile")] = None,
) -> Any:
    return client.post(
        "/admin/domains", {"slug": slug, "name": name, "evidence_profile": evidence_profile}
    )


@registry.tool("update_domain", "Altera nome e/ou perfil de evidência de um domain.",
               group="admin", mutating=True, idempotent=True)
def update_domain(
    client: BspClient,
    slug: str,
    name: str | None = None,
    evidence_profile: Annotated[str | None, desc("default | legacy-hostile")] = None,
) -> Any:
    body: dict = {}
    if name is not None:
        body["name"] = name
    if evidence_profile is not None:
        body["evidence_profile"] = evidence_profile
    return client.patch(f"/admin/domains/{slug}", body)


@registry.tool(
    "list_capabilities",
    "Lista capabilities (slug, domain, nome, descrição), opcionalmente de um domain.",
    group="admin",
)
def list_capabilities(
    client: BspClient,
    domain: Annotated[str | None, desc("filtra por domain (slug)")] = None,
) -> Any:
    caps = client.get("/admin/capabilities")
    return [c for c in caps if not domain or c["domain_slug"] == domain]


@registry.tool(
    "create_capability",
    "Cria uma capability em um domain. A DESCRIÇÃO orienta o inventário e o discovery "
    "dirigido (o agente a recebe no prompt): escreva o que ela cobre em linguagem de negócio.",
    group="admin", mutating=True,
)
def create_capability(
    client: BspClient,
    slug: Annotated[str, desc("slug: minúsculas, números e hífens")],
    domain_slug: str,
    name: str,
    description: Annotated[str | None, desc("o que a capability cobre (negócio)")] = None,
) -> Any:
    return client.post(
        "/admin/capabilities",
        {"slug": slug, "domain_slug": domain_slug, "name": name, "description": description},
    )


@registry.tool("update_capability", "Altera nome e/ou descrição de uma capability.",
               group="admin", mutating=True, idempotent=True)
def update_capability(
    client: BspClient, slug: str, name: str | None = None, description: str | None = None
) -> Any:
    body: dict = {}
    if name is not None:
        body["name"] = name
    if description is not None:
        body["description"] = description
    return client.patch(f"/admin/capabilities/{slug}", body)


@registry.tool(
    "list_role_bindings",
    "Lista papéis atribuídos (binding id, usuário, papel, domain, capability). "
    "Sem domain = papel global. Só administrador.",
    group="admin",
)
def list_role_bindings(
    client: BspClient,
    user_id: Annotated[str | None, desc("filtra por usuário (UUID)")] = None,
) -> Any:
    return client.get("/admin/role-bindings", user_id=user_id)


@registry.tool(
    "grant_role",
    "Atribui um papel a um usuário. Sem domain_slug o papel é GLOBAL (vale em qualquer "
    "escopo); com domain (e opcionalmente capability) vale só ali. Hierarquia: viewer < "
    "reviewer < domain_expert/decision_owner < administrator. Só administrador.",
    group="admin", mutating=True,
)
def grant_role(
    client: BspClient,
    user_id: Annotated[str, desc("UUID do usuário")],
    role: Role,
    domain_slug: str | None = None,
    capability_slug: str | None = None,
) -> Any:
    return client.post(
        "/admin/role-bindings",
        {
            "user_id": user_id, "role": role, "domain_slug": domain_slug,
            "capability_slug": capability_slug,
        },
    )


@registry.tool("revoke_role", "Remove um papel (binding) de um usuário. Só administrador.",
               group="admin", destructive=True)
def revoke_role(
    client: BspClient,
    binding_id: Annotated[str, desc("UUID do binding; veja list_role_bindings")],
) -> Any:
    return client.delete(f"/admin/role-bindings/{binding_id}")


@registry.tool(
    "list_policies",
    "Lista as políticas de confiança/roteamento (limiar canônico, piso provisório, revisores "
    "mínimos, aprovação do owner) por escopo: global, domain, atom_kind, significance, "
    "capability, risk.",
    group="admin",
)
def list_policies(client: BspClient) -> Any:
    return client.get("/admin/policies")


@registry.tool(
    "create_policy",
    "Cria uma política de roteamento. threshold = confiança mínima para CANÔNICO; "
    "provisional_floor = piso para PROVISIONAL. Escopos mais específicos precedem. "
    "Só administrador.",
    group="admin", mutating=True,
)
def create_policy(
    client: BspClient,
    name: str,
    scope_type: PolicyScope,
    selector: Annotated[str | None, desc("slug/kind/nível do escopo; global não usa")] = None,
    threshold: Annotated[float | None, desc("0..1, confiança para canônico")] = None,
    provisional_floor: Annotated[float | None, desc("0..1, piso do provisório")] = None,
    human_review_required: bool | None = None,
    min_reviewers: Annotated[int | None, desc(">= 1")] = None,
    require_owner_approval: bool | None = None,
    active: bool = True,
) -> Any:
    return client.post(
        "/admin/policies",
        {
            "name": name, "scope_type": scope_type, "selector": selector,
            "threshold": threshold, "provisional_floor": provisional_floor,
            "human_review_required": human_review_required, "min_reviewers": min_reviewers,
            "require_owner_approval": require_owner_approval, "active": active,
        },
    )


@registry.tool("delete_policy", "Exclui uma política de roteamento. Só administrador.",
               group="admin", destructive=True)
def delete_policy(client: BspClient, policy_id: Annotated[str, desc("UUID")]) -> Any:
    return client.delete(f"/admin/policies/{policy_id}")


@registry.tool(
    "list_evidence_profiles",
    "Perfis de evidência disponíveis (pesos do Confidence Engine): default e legacy-hostile.",
    group="admin",
)
def list_evidence_profiles(client: BspClient) -> Any:
    return client.get("/admin/evidence-profiles")


# =====================================================================
# sources — registro de fontes legadas e inventário
# =====================================================================


@registry.tool(
    "list_sources",
    "Lista as sources (fontes legadas): id, tipo, nome, repositório, branch, domain.",
    group="sources",
)
def list_sources(
    client: BspClient,
    domain: Annotated[str | None, desc("filtra por domain (slug)")] = None,
) -> Any:
    rows = client.get("/sources")
    return [r for r in rows if not domain or r.get("domain_slug") == domain]


@registry.tool("get_source", "Detalhe de uma source.", group="sources")
def get_source(client: BspClient, source_id: str) -> Any:
    return client.get(f"/sources/{source_id}")


@registry.tool(
    "create_source",
    "Cadastra uma fonte legada. Para código, `repository` é o caminho do repositório git NO "
    "HOST (pode ser um subdiretório, ex.: C:/legado/erp/source). Só administrador.",
    group="sources", mutating=True,
)
def create_source(
    client: BspClient,
    type: SourceType,
    name: Annotated[str, desc("nome único e legível")],
    repository: Annotated[str | None, desc("caminho do repositório git no host")] = None,
    branch: str | None = None,
    location: Annotated[str | None, desc("URL/caminho para fontes não-git")] = None,
    version: Annotated[str | None, desc("versão do sistema legado")] = None,
    domain_slug: Annotated[str | None, desc("domain ao qual a source pertence")] = None,
    metadata: dict | None = None,
) -> Any:
    return client.post(
        "/sources",
        {
            "type": type, "name": name, "repository": repository, "branch": branch,
            "location": location, "version": version, "domain_slug": domain_slug,
            "metadata": metadata,
        },
    )


@registry.tool(
    "source_inventory_summary",
    "Resumo do inventário de uma source: arquivos inventariados, por capability e relevância "
    "(1 tangencial · 2 relevante · 3 central), arquivos sem capability e capabilities "
    "sugeridas pelo agente que ainda não existem no cadastro.",
    group="sources",
)
def source_inventory_summary(client: BspClient, source_id: str) -> Any:
    return client.get(f"/sources/{source_id}/inventory/summary")


@registry.tool(
    "source_inventory",
    "Arquivos inventariados de uma source (caminho, linguagem, linhas, resumo de negócio, "
    "capabilities ligadas). Filtre por capability ou texto.",
    group="sources",
)
def source_inventory(
    client: BspClient,
    source_id: str,
    capability: Annotated[str | None, desc("só arquivos ligados a esta capability")] = None,
    q: Annotated[str | None, desc("filtro em caminho/resumo")] = None,
    limit: Annotated[int, desc("1..5000")] = 100,
) -> Any:
    return client.get(
        f"/sources/{source_id}/inventory", capability=capability, q=q, limit=limit
    )


# =====================================================================
# discovery — harness, campanhas, fila
# =====================================================================


@registry.tool(
    "start_inventory",
    "Enfileira o INVENTÁRIO de uma source (passo 1 do discovery dirigido): o harness resume "
    "cada arquivo e o liga às capabilities do domain. Exige capabilities cadastradas no domain "
    "e um worker da fila `discovery` rodando no host. Só administrador.",
    group="discovery", mutating=True,
)
def start_inventory(
    client: BspClient,
    source_id: str,
    domain: str,
    prefix: Annotated[str | None, desc("só arquivos sob este prefixo, ex.: ADM001/")] = None,
    max_files: int | None = None,
    only_missing: Annotated[bool, desc("false re-inventaria os já feitos")] = True,
    budget_usd: Annotated[float, desc("US$ por lote")] = 3.0,
) -> Any:
    return client.post(
        "/discovery/inventory",
        {
            "source_id": source_id, "domain": domain, "prefix": prefix,
            "max_files": max_files, "only_missing": only_missing, "budget_usd": budget_usd,
        },
    )


@registry.tool(
    "start_campaign",
    "Enfileira uma CAMPANHA DIRIGIDA (passo 2): um turno do harness por arquivo inventariado "
    "ligado à capability (relevância >= min_relevance). Gera candidates com evidência "
    "verificada. Só administrador.",
    group="discovery", mutating=True,
)
def start_campaign(
    client: BspClient,
    source_id: str,
    domain: str,
    capability: str,
    min_relevance: Annotated[int, desc("1..3; 2 = relevante ou central")] = 2,
    max_files: int | None = None,
    budget_usd: Annotated[float, desc("US$ por arquivo/faixa")] = 3.0,
    max_candidates: Annotated[int, desc("teto de candidates por turno")] = 12,
) -> Any:
    return client.post(
        "/discovery/campaigns",
        {
            "source_id": source_id, "domain": domain, "capability": capability,
            "min_relevance": min_relevance, "max_files": max_files, "budget_usd": budget_usd,
            "max_candidates": max_candidates,
        },
    )


@registry.tool(
    "start_discovery_run",
    "Enfileira um run ABERTO do harness no repositório inteiro (agent: code | test | "
    "corroboration). Para repositórios grandes prefira start_inventory + start_campaign. "
    "Só administrador.",
    group="discovery", mutating=True,
)
def start_discovery_run(
    client: BspClient,
    source_id: str,
    agent: Literal["code", "test", "corroboration"],
    domain: str,
    capability: str | None = None,
    scope_hint: Annotated[str, desc("módulos/pastas prioritários")] = "todo o repositório",
    budget_usd: float = 5.0,
) -> Any:
    return client.post(
        "/discovery/runs",
        {
            "source_id": source_id, "agent": agent, "domain": domain,
            "capability": capability, "scope_hint": scope_hint, "budget_usd": budget_usd,
        },
    )


@registry.tool(
    "start_evidence_search",
    "Cascata de evidência (estágio 1, mesma source): corrobora em lotes de 30 os atoms que "
    "ainda não atingiram a faixa alvo, pedindo evidência em outros sítios. Só administrador.",
    group="discovery", mutating=True,
)
def start_evidence_search(
    client: BspClient,
    source_id: str,
    domain: str,
    capability: str | None = None,
    max_batches: Annotated[int, desc("1..20 lotes de 30 atoms")] = 3,
    budget_usd: Annotated[float, desc("US$ por lote")] = 5.0,
) -> Any:
    return client.post(
        "/discovery/evidence-search",
        {
            "source_id": source_id, "domain": domain, "capability": capability,
            "max_batches": max_batches, "budget_usd": budget_usd,
        },
    )


@registry.tool(
    "list_discovery_runs",
    "Runs do harness (auditoria): status (running/succeeded/failed/limit/auth_failed), "
    "agente, custo US$, candidates criados, erro. Mais recentes primeiro.",
    group="discovery",
)
def list_discovery_runs(
    client: BspClient,
    domain: str | None = None,
    exclude: Annotated[str | None, desc("status a omitir, separados por vírgula")] = None,
    limit: Annotated[int, desc("1..500")] = 50,
) -> Any:
    return client.get("/discovery/runs", domain=domain, exclude=exclude, limit=limit)


@registry.tool("get_discovery_run", "Detalhe de um run (inclui caminho do log .jsonl).",
               group="discovery")
def get_discovery_run(client: BspClient, run_id: str) -> Any:
    return client.get(f"/discovery/runs/{run_id}")


@registry.tool(
    "list_batches",
    "Campanhas (inventário e dirigidas) com progresso agregado: done/total, jobs pendentes, "
    "falhas, bloqueios por franquia, custo e candidates.",
    group="discovery",
)
def list_batches(
    client: BspClient,
    active_only: Annotated[bool, desc("só campanhas com jobs pendentes/rodando")] = False,
    limit: int = 50,
) -> Any:
    rows = client.get("/discovery/batches", limit=limit)
    return [b for b in rows if not active_only or b.get("active")]


@registry.tool(
    "queue_status",
    "Fila do Procrastinate: pendentes, rodando, workers vivos (heartbeat), jobs reagendados "
    "(franquia) e últimos jobs. Jobs da fila `discovery` só andam com worker NO HOST.",
    group="discovery",
)
def queue_status(
    client: BspClient,
    queue: Annotated[str | None, desc("discovery (padrão) | default | null = todas")] = "discovery",
    limit: int = 20,
) -> Any:
    return client.get("/discovery/queue", queue=queue, limit=limit)


@registry.tool(
    "release_queue",
    "Antecipa para AGORA os jobs reagendados para o futuro (esperando reset de franquia). "
    "Opcionalmente só de uma campanha. Só administrador.",
    group="discovery", mutating=True, idempotent=True,
)
def release_queue(client: BspClient, batch_id: str | None = None) -> Any:
    return client.post("/discovery/queue/release", {"batch_id": batch_id})


@registry.tool(
    "harness_agents",
    "Executor do harness (local ou remoto) e os agentes remotos registrados: status (online, "
    "executando, limitado, offline), pessoa, versão, tarefas concluídas, custo do dia e limite; "
    "mais a contagem de tarefas remotas por status. No executor remoto, 'tarefa esperando sem "
    "agente online' explica campanha parada.",
    group="discovery",
)
def harness_agents(client: BspClient, include_revoked: bool = False) -> Any:
    return {
        "status": client.get("/harness/status"),
        "agents": client.get("/harness/agents", include_revoked=include_revoked),
    }


@registry.tool("cancel_job", "Cancela um job ainda pendente (todo) da fila. Só administrador.",
               group="discovery", destructive=True)
def cancel_job(client: BspClient, job_id: int) -> Any:
    return client.post(f"/discovery/queue/{job_id}/cancel")


@registry.tool(
    "triage_pending",
    "Aplica a régua de relevância aos candidates pendentes de revisão sem voto: classifica "
    "via modelo de análise (OpenRouter) e re-roteia SYSTEMIC/LOW sem humano. apply=false só "
    "conta. Só administrador.",
    group="discovery", mutating=True,
)
def triage_pending(
    client: BspClient,
    domain: str | None = None,
    limit: int = 200,
    apply: Annotated[bool, desc("false = simulação (dry-run)")] = True,
) -> Any:
    return client.post("/discovery/triage", {"domain": domain, "limit": limit, "apply": apply})


@registry.tool(
    "reroute_pending",
    "Re-roteia os pendentes de revisão SEM voto sob as faixas/políticas atuais (sem LLM): "
    "podem virar canônico, provisório ou aguardar evidência. Só administrador.",
    group="discovery", mutating=True, idempotent=True,
)
def reroute_pending(client: BspClient, domain: str | None = None, limit: int = 500) -> Any:
    return client.post("/discovery/reroute", {"domain": domain, "limit": limit})


# =====================================================================
# knowledge — atoms, evidência, relações
# =====================================================================


@registry.tool(
    "search_knowledge",
    "Busca textual (full-text em português + fuzzy no título) nos atoms com filtros. "
    "Devolve id, título, statement, status, confiança, risco.",
    group="knowledge",
)
def search_knowledge(
    client: BspClient,
    q: Annotated[str, desc("termos de busca")],
    domain: str | None = None,
    capability: str | None = None,
    status: Status | None = None,
    kind: AtomKind | None = None,
    min_confidence: Annotated[float | None, desc("0..1")] = None,
    limit: int = 25,
) -> Any:
    return client.get(
        "/search", q=q, domain=domain, capability=capability, status=status, kind=kind,
        min_confidence=min_confidence, limit=limit,
    )


@registry.tool(
    "list_atoms",
    "Lista atoms com filtros estruturados (domain, capability, kind, status, relevância, "
    "risco, classificação, faixa de confiança). Paginado (total + items).",
    group="knowledge",
)
def list_atoms(
    client: BspClient,
    domain: str | None = None,
    capability: str | None = None,
    kind: AtomKind | None = None,
    statuses: Annotated[list[Status] | None, desc("um ou mais status")] = None,
    significance: Significance | None = None,
    risk: Risk | None = None,
    classification: Classification | None = None,
    q: Annotated[str | None, desc("trecho do título")] = None,
    min_confidence: float | None = None,
    max_confidence: float | None = None,
    limit: Annotated[int, desc("1..200")] = 50,
    offset: int = 0,
) -> Any:
    return client.get(
        "/knowledge", domain=domain, capability=capability, kind=kind,
        statuses=",".join(statuses) if statuses else None, significance=significance,
        risk=risk, classification=classification, q=q, min_confidence=min_confidence,
        max_confidence=max_confidence, limit=limit, offset=offset,
    )


@registry.tool(
    "get_atom",
    "Um atom completo (envelope + body). `include` agrega: evidence (trechos e localização), "
    "confidence (sinais explicados), history (versões e eventos), impact (o que muda se ele "
    "mudar), graph (vizinhança de relações).",
    group="knowledge",
)
def get_atom(
    client: BspClient,
    atom_id: str,
    include: Annotated[
        list[Literal["evidence", "confidence", "history", "impact", "graph"]] | None,
        desc("seções extras"),
    ] = None,
) -> Any:
    out = {"atom": client.get(f"/knowledge/{atom_id}")}
    for section in include or []:
        if section == "graph":
            _safe(out, "graph", lambda: client.get("/graph", atom_id=atom_id, depth=1))
        else:
            _safe(out, section, lambda s=section: client.get(f"/knowledge/{atom_id}/{s}"))
    return out


@registry.tool(
    "create_candidate",
    "Cria um candidate HUMANO (regra, conceito, cenário...). Para rule/invariant informe "
    "`statement`; para outros kinds use `body` no formato do kind. Evidência opcional: lista "
    "de {type, summary, excerpt?, location?, source_id?, relation?}. Exige reviewer no escopo.",
    group="knowledge", mutating=True,
)
def create_candidate(
    client: BspClient,
    kind: AtomKind,
    title: str,
    domain: str,
    capability: str | None = None,
    statement: Annotated[str | None, desc("enunciado da regra/invariante")] = None,
    description: str | None = None,
    classification: Classification | None = None,
    risk: Risk | None = None,
    scope: Annotated[dict | None, desc("ex.: {\"version\": \"12.4\"}")] = None,
    effective: Annotated[dict | None, desc("vigência, ex.: {\"from\": \"2024-01-01\"}")] = None,
    body: Annotated[dict | None, desc("body específico do kind (substitui statement)")] = None,
    evidence: list[dict] | None = None,
) -> Any:
    if body is None and statement is not None:
        body = {"statement": statement}
    return client.post(
        "/knowledge/candidates",
        {
            "kind": kind, "title": title, "domain": domain, "capability": capability,
            "description": description or statement, "classification": classification,
            "risk": risk, "scope": scope, "effective": effective, "body": body,
            "evidence": evidence or [],
        },
    )


@registry.tool(
    "update_atom",
    "Edita campos de um atom (título, descrição, classificação, risco, escopo, vigência, "
    "body). Exige expected_lock_version (veja get_atom) — optimistic locking.",
    group="knowledge", mutating=True,
)
def update_atom(
    client: BspClient,
    atom_id: str,
    expected_lock_version: int,
    title: str | None = None,
    description: str | None = None,
    classification: Classification | None = None,
    risk: Risk | None = None,
    scope: dict | None = None,
    effective: dict | None = None,
    body: dict | None = None,
) -> Any:
    changes = {
        k: v
        for k, v in {
            "title": title, "description": description, "classification": classification,
            "risk": risk, "scope": scope, "effective": effective, "body": body,
        }.items()
        if v is not None
    }
    return client.patch(
        f"/knowledge/{atom_id}", {"expected_lock_version": expected_lock_version, **changes}
    )


@registry.tool(
    "change_atom_status",
    "Transição de lifecycle explícita (ex.: REJECTED, CANONICAL, SUPERSEDED). Canonicalizar "
    "exige decision owner no escopo. Prefira o fluxo de revisão (vote/decide) quando houver.",
    group="knowledge", destructive=True,
)
def change_atom_status(
    client: BspClient, atom_id: str, status: Status, reason: str, expected_lock_version: int
) -> Any:
    return client.post(
        f"/knowledge/{atom_id}/status",
        {"status": status, "reason": reason, "expected_lock_version": expected_lock_version},
    )


@registry.tool(
    "add_evidence",
    "Anexa evidência a um atom (suporte ou contradição). Evidência humana: type "
    "HUMAN_REVIEW/DOMAIN_EXPERT com summary. Recalcula a confiança. Exige reviewer.",
    group="knowledge", mutating=True,
)
def add_evidence(
    client: BspClient,
    atom_id: str,
    type: EvidenceType,
    summary: Annotated[str | None, desc("o que a evidência garante, em negócio")] = None,
    excerpt: Annotated[str | None, desc("trecho técnico literal")] = None,
    location: Annotated[dict | None, desc("{file, start_line, end_line, symbol?}")] = None,
    source_id: str | None = None,
    relation: Literal["supports", "contradicts"] = "supports",
    metadata: Annotated[dict | None, desc("ex.: {\"mechanism\": \"VALIDATION\"}")] = None,
) -> Any:
    return client.post(
        f"/knowledge/{atom_id}/evidence",
        {
            "type": type, "summary": summary, "excerpt": excerpt, "location": location,
            "source_id": source_id, "relation": relation, "metadata": metadata,
        },
    )


@registry.tool("add_relation", "Cria uma relação dirigida entre dois atoms (graph semântico).",
               group="knowledge", mutating=True)
def add_relation(client: BspClient, atom_id: str, to_atom: str, type: RelationType) -> Any:
    return client.post(f"/knowledge/{atom_id}/relations", {"to_atom": to_atom, "type": type})


@registry.tool(
    "evaluate_atom",
    "Recalcula confiança e roteamento de um atom (faixas CANONICAL/PROVISIONAL/"
    "NEEDS_HUMAN_REVIEW). Devolve a decisão e os sinais.",
    group="knowledge", mutating=True, idempotent=True,
)
def evaluate_atom(client: BspClient, atom_id: str) -> Any:
    return client.post(f"/knowledge/{atom_id}/evaluate")


@registry.tool(
    "translate_evidence",
    "Gera (via modelo de análise) a tradução de negócio de uma evidência sem summary.",
    group="knowledge", mutating=True, idempotent=True,
)
def translate_evidence(client: BspClient, atom_id: str, evidence_id: str) -> Any:
    return client.post(f"/knowledge/{atom_id}/evidence/{evidence_id}/translate")


@registry.tool(
    "lint_knowledge",
    "Roda o linter semântico: erros e avisos de consistência nos atoms visíveis.",
    group="knowledge",
)
def lint_knowledge(client: BspClient) -> Any:
    return client.get("/knowledge/lint")


@registry.tool(
    "new_canonical_version",
    "Publica uma nova versão de um atom CANÔNICO com alterações (histórico preservado). "
    "Exige decision owner no escopo.",
    group="knowledge", destructive=True,
)
def new_canonical_version(
    client: BspClient,
    atom_id: str,
    expected_lock_version: int,
    reason: str,
    title: str | None = None,
    description: str | None = None,
    classification: Classification | None = None,
    risk: Risk | None = None,
    scope: dict | None = None,
    effective: dict | None = None,
    body: dict | None = None,
) -> Any:
    changes = {
        k: v
        for k, v in {
            "title": title, "description": description, "classification": classification,
            "risk": risk, "scope": scope, "effective": effective, "body": body,
        }.items()
        if v is not None
    }
    return client.post(
        f"/knowledge/{atom_id}/new-version",
        {"expected_lock_version": expected_lock_version, "reason": reason, **changes},
    )


@registry.tool(
    "supersede_atom",
    "Marca um atom canônico como SUPERSEDED por outro atom canônico. Decision owner.",
    group="knowledge", destructive=True,
)
def supersede_atom(
    client: BspClient,
    atom_id: str,
    by: Annotated[str, desc("id do atom canônico substituto")],
    reason: str,
    expected_lock_version: int,
) -> Any:
    return client.post(
        f"/knowledge/{atom_id}/supersede",
        {"by": by, "reason": reason, "expected_lock_version": expected_lock_version},
    )


# =====================================================================
# reviews — governança humana
# =====================================================================


@registry.tool(
    "review_inbox",
    "Inbox de revisão do usuário: só o que EXIGE ação humana, ordenado por prioridade "
    "(risco, confiança, conflitos, idade, centralidade) + resumo (aguardando revisão, "
    "decisão, conflitos, canônicos desafiados, provisórios, aguardando evidência).",
    group="reviews",
)
def review_inbox(client: BspClient) -> Any:
    return client.get("/reviews/inbox")


@registry.tool("review_kanban", "Kanban do funil por coluna de lifecycle, filtrável.",
               group="reviews")
def review_kanban(
    client: BspClient, domain: str | None = None, capability: str | None = None
) -> Any:
    return client.get("/reviews/kanban", domain=domain, capability=capability)


@registry.tool(
    "decision_room",
    "Decision Room de um atom: evidência, confiança explicada, votos, comentários, conflitos "
    "e o que a política exige para fechar.",
    group="reviews",
)
def decision_room(client: BspClient, atom_id: str) -> Any:
    return client.get(f"/reviews/{atom_id}")


@registry.tool("start_review", "Move um atom para IN_REVIEW (abre a discussão). Reviewer.",
               group="reviews", mutating=True, idempotent=True)
def start_review(client: BspClient, atom_id: str) -> Any:
    return client.post(f"/reviews/{atom_id}/start")


@registry.tool(
    "vote",
    "Registra o voto do usuário em um atom (um voto ativo por revisor). CONFIRM em provisório "
    "pode canonicalizar direto se a política dispensar o owner. Reviewer no escopo.",
    group="reviews", mutating=True,
)
def vote(
    client: BspClient, atom_id: str, action: ReviewAction, comment: str | None = None
) -> Any:
    return client.post(f"/reviews/{atom_id}/vote", {"action": action, "comment": comment})


@registry.tool(
    "bulk_vote",
    "O mesmo voto em vários atoms (revisão por filtro). Cada um passa pelos gates do voto "
    "individual; falhas voltam por atom.",
    group="reviews", mutating=True,
)
def bulk_vote(
    client: BspClient,
    atom_ids: Annotated[list[str], desc("1..200 ids")],
    action: ReviewAction,
    comment: str | None = None,
) -> Any:
    return client.post(
        "/reviews/inbox/bulk", {"atom_ids": atom_ids, "action": action, "comment": comment}
    )


@registry.tool("comment", "Comenta na Decision Room de um atom. Reviewer.",
               group="reviews", mutating=True)
def comment(client: BspClient, atom_id: str, text: str) -> Any:
    return client.post(f"/reviews/{atom_id}/comment", {"text": text})


@registry.tool("request_evidence", "Pede mais evidência para um atom (volta a CORROBORATING).",
               group="reviews", mutating=True)
def request_evidence(client: BspClient, atom_id: str, note: str) -> Any:
    return client.post(f"/reviews/{atom_id}/request-evidence", {"note": note})


@registry.tool("ready_for_decision", "Marca o atom como pronto para decisão do owner.",
               group="reviews", mutating=True, idempotent=True)
def ready_for_decision(client: BspClient, atom_id: str) -> Any:
    return client.post(f"/reviews/{atom_id}/ready-for-decision")


@registry.tool(
    "decide",
    "Decisão final do DECISION OWNER: APPROVE (vira canônico), REJECT, RECLASSIFY (informe "
    "classification), MARK_KNOWN_BUG, REQUEST_EVIDENCE, ADD_EXCEPTION (informe "
    "exception_title/condition). Exige expected_lock_version.",
    group="reviews", destructive=True,
)
def decide(
    client: BspClient,
    atom_id: str,
    action: DecisionAction,
    reason: str,
    expected_lock_version: int,
    classification: Classification | None = None,
    exception_title: str | None = None,
    exception_condition: str | None = None,
) -> Any:
    body: dict = {
        "action": action, "reason": reason, "expected_lock_version": expected_lock_version,
        "classification": classification,
    }
    if exception_title and exception_condition:
        body["exception"] = {"title": exception_title, "condition": exception_condition}
    return client.post(f"/reviews/{atom_id}/decision", body)


@registry.tool(
    "audit_sample",
    "Amostra aleatória de PROVISIONAL sem voto no escopo: a fila curta de auditoria que "
    "calibra o piso provisório (false_provisional_rate).",
    group="reviews",
)
def audit_sample(
    client: BspClient, domain: str | None = None, capability: str | None = None, n: int = 10
) -> Any:
    return client.get("/reviews/inbox/audit-sample", domain=domain, capability=capability, n=n)


@registry.tool(
    "suggest_decomposition",
    "Pede ao Review Assistant sugestões de quebra de uma regra composta em sub-regras. "
    "Não grava nada.",
    group="reviews",
)
def suggest_decomposition(client: BspClient, atom_id: str) -> Any:
    return client.post(f"/reviews/{atom_id}/suggest-decomposition")


@registry.tool(
    "apply_decomposition",
    "Aplica a decomposição: cria as sub-regras (SUPERSEDES a original, que vira REJECTED). "
    "rules = [{title, statement, scope?}, ...] (>= 2). Decision owner.",
    group="reviews", destructive=True,
)
def apply_decomposition(
    client: BspClient,
    atom_id: str,
    rules: list[dict],
    reason: str,
    expected_lock_version: int,
) -> Any:
    return client.post(
        f"/reviews/{atom_id}/decompose",
        {"rules": rules, "reason": reason, "expected_lock_version": expected_lock_version},
    )


# =====================================================================
# conflicts / questions
# =====================================================================


@registry.tool("list_conflicts", "Conflitos entre atoms (abertos por padrão).",
               group="conflicts")
def list_conflicts(
    client: BspClient,
    domain: str | None = None,
    state: Annotated[str | None, desc("open | resolved | null = todos")] = "open",
) -> Any:
    return client.get("/conflicts", domain=domain, state=state)


@registry.tool(
    "get_conflict",
    "Conflict View: assertions em disputa, evidência e confiança de cada lado, votos.",
    group="conflicts",
)
def get_conflict(client: BspClient, conflict_id: str) -> Any:
    return client.get(f"/conflicts/{conflict_id}")


@registry.tool(
    "detect_conflicts",
    "Roda a detecção de conflitos no escopo (heurística; use_llm=true adiciona o modelo de "
    "análise). Reviewer.",
    group="conflicts", mutating=True,
)
def detect_conflicts(
    client: BspClient, domain: str, capability: str | None = None, use_llm: bool = False
) -> Any:
    return client.post(
        "/conflicts/detect", {"domain": domain, "capability": capability, "use_llm": use_llm}
    )


@registry.tool(
    "resolve_conflict",
    "Resolve um conflito (decision owner): SELECT_ASSERTION (params.atom_id), "
    "NEW_INTERPRETATION, SPLIT_BY_SCOPE, SPLIT_BY_TIME, MARK_LEGACY_BUG, MARK_UNRESOLVED, "
    "REQUEST_EVIDENCE.",
    group="conflicts", destructive=True,
)
def resolve_conflict(
    client: BspClient,
    conflict_id: str,
    action: ConflictAction,
    reason: str,
    expected_lock_version: int,
    params: dict | None = None,
) -> Any:
    return client.post(
        f"/conflicts/{conflict_id}/resolve",
        {
            "action": action, "reason": reason, "expected_lock_version": expected_lock_version,
            "params": params or {},
        },
    )


@registry.tool("list_questions", "Questions abertas pelos agentes/humanos, com filtros.",
               group="questions")
def list_questions(
    client: BspClient,
    domain: str | None = None,
    capability: str | None = None,
    answered: Annotated[bool | None, desc("true só respondidas; false só abertas")] = None,
) -> Any:
    return client.get("/questions", domain=domain, capability=capability, answered=answered)


@registry.tool("answer_question", "Responde uma question (domain expert no escopo).",
               group="questions", mutating=True)
def answer_question(client: BspClient, question_id: str, answer: str) -> Any:
    return client.post(f"/questions/{question_id}/answer", {"answer": answer})


@registry.tool("assign_question", "Atribui uma question a um usuário (por e-mail).",
               group="questions", mutating=True, idempotent=True)
def assign_question(client: BspClient, question_id: str, assignee_email: str) -> Any:
    return client.post(
        f"/questions/{question_id}/assign", {"assignee_email": assignee_email}
    )


@registry.tool(
    "convert_question_to_rule",
    "Converte uma question respondida em um candidate de regra. Domain expert.",
    group="questions", mutating=True,
)
def convert_question_to_rule(
    client: BspClient, question_id: str, title: str, statement: str, scope: dict | None = None
) -> Any:
    return client.post(
        f"/questions/{question_id}/convert-to-rule",
        {"title": title, "statement": statement, "scope": scope},
    )


# =====================================================================
# consume — explorer, context package, projeções
# =====================================================================


@registry.tool(
    "explorer",
    "Árvore Domain → Capability com contagens por kind e canônicos; com domain+capability, "
    "os atoms daquela capability agrupados por kind.",
    group="consume",
)
def explorer(client: BspClient, domain: str | None = None, capability: str | None = None) -> Any:
    if domain and capability:
        return client.get(f"/explorer/{domain}/{capability}")
    tree = client.get("/explorer")
    return [d for d in tree if not domain or d["slug"] == domain]


@registry.tool(
    "context_package",
    "Context package de uma capability para consumo por IA/humano: por padrão só canônico; "
    "inclua provisórios/candidates explicitamente. format=markdown devolve texto pronto.",
    group="consume",
)
def context_package(
    client: BspClient,
    capability: str,
    task: Annotated[str | None, desc("tarefa que orienta a seleção")] = None,
    include_candidates: bool = False,
    include_provisional: bool = False,
    format: Literal["json", "markdown"] = "json",
) -> Any:
    return client.get(
        "/context", capability=capability, task=task, include_candidates=include_candidates,
        include_provisional=include_provisional, format=format,
    )


@registry.tool(
    "projection",
    "Projeções do conhecimento: bdd (feature Gherkin da capability, ou de um scenario com "
    "atom_id), markdown (documento da capability), state_machine (capability), "
    "decision_table (atom de decisão).",
    group="consume",
)
def projection(
    client: BspClient,
    kind: Literal["bdd", "markdown", "state_machine", "decision_table"],
    capability: str | None = None,
    atom_id: str | None = None,
    canonical_only: bool = True,
) -> Any:
    if kind == "bdd":
        if atom_id:
            return client.get(f"/projections/bdd/{atom_id}")
        return client.get("/projections/bdd", capability=capability, canonical_only=canonical_only)
    if kind == "decision_table":
        return client.get(f"/projections/decision-table/{atom_id}")
    if kind == "state_machine":
        return client.get("/projections/state-machine", capability=capability)
    return client.get("/projections/markdown", capability=capability)


# =====================================================================
# metrics
# =====================================================================


@registry.tool(
    "metrics",
    "Métricas semânticas: coverage (cobertura: canônicos, provisórios, candidates, regras "
    "com/sem evidência, sem owner), coverage_by_capability, confidence_distribution (buckets "
    "e % auto/provisório/humano), attention (KPIs de atenção humana, latências, "
    "provisional_audit.false_provisional_rate), audit (dashboard de auditoria).",
    group="metrics",
)
def metrics(
    client: BspClient,
    report: Literal[
        "coverage", "coverage_by_capability", "confidence_distribution", "attention", "audit"
    ],
    domain: str | None = None,
    capability: str | None = None,
) -> Any:
    path = "/metrics/" + report.replace("_", "-")
    if report == "coverage":
        return client.get(path, domain=domain, capability=capability)
    return client.get(path, domain=domain)


@registry.tool("recent_events", "Últimos eventos do audit trail (tipo, atom, ator, quando).",
               group="metrics")
def recent_events(client: BspClient, limit: Annotated[int, desc("1..100")] = 20) -> Any:
    return client.get("/metrics/recent-events", limit=limit)


# =====================================================================
# helpdesk
# =====================================================================


@registry.tool(
    "helpdesk_ask",
    "Monta o pacote de conhecimento governado para uma pergunta de suporte (answerability, "
    "ação recomendada, conhecimento citável, perguntas de esclarecimento, escalonamento). "
    "Perfis: helpdesk_direct (usuário final), copilot_n1/n2/n3. context: {version, "
    "document_state, error_messages: [...]}.",
    group="helpdesk",
)
def helpdesk_ask(
    client: BspClient,
    question: str,
    consumer_profile: ConsumerProfile = "helpdesk_copilot_n1",
    domain: str | None = None,
    capability: str | None = None,
    context: dict | None = None,
    persist_interaction: Annotated[bool, desc("false = não grava a interação")] = True,
) -> Any:
    return client.post(
        "/helpdesk/context",
        {
            "question": question, "consumer_profile": consumer_profile, "domain": domain,
            "capability": capability, "context": context or {},
            "persist_interaction": persist_interaction,
        },
    )


@registry.tool(
    "helpdesk_feedback",
    "Registra o resultado de um atendimento (interação do helpdesk_ask). Correção de um "
    "reviewer vira candidate com evidência de revisão humana.",
    group="helpdesk", mutating=True, idempotent=True,
)
def helpdesk_feedback(
    client: BspClient,
    interaction_id: str,
    outcome: FeedbackOutcome,
    idempotency_key: str | None = None,
    helpful_atom_ids: list[str] | None = None,
    misleading_atom_ids: list[str] | None = None,
    missing_information: str | None = None,
    correction: str | None = None,
    ticket_reference: str | None = None,
) -> Any:
    return client.post(
        f"/helpdesk/interactions/{interaction_id}/feedback",
        {
            "idempotency_key": idempotency_key or f"mcp-{interaction_id}-{outcome}",
            "outcome": outcome, "helpful_atom_ids": helpful_atom_ids or [],
            "misleading_atom_ids": misleading_atom_ids or [],
            "missing_information": missing_information, "correction": correction,
            "ticket_reference": ticket_reference,
        },
    )


@registry.tool(
    "helpdesk_report",
    "Relatórios do help desk: metrics (volume, answerability, ações, feedback), gaps "
    "(perguntas sem resposta suficiente = lacunas de conhecimento), freshness (evidências "
    "possivelmente desatualizadas frente ao HEAD da source).",
    group="helpdesk",
)
def helpdesk_report(
    client: BspClient,
    report: Literal["metrics", "gaps", "freshness"],
    domain: str | None = None,
    capability: str | None = None,
    limit: int = 50,
) -> Any:
    if report == "gaps":
        return client.get("/helpdesk/gaps", limit=limit)
    if report == "freshness":
        return client.get("/helpdesk/freshness", domain=domain, capability=capability, limit=limit)
    return client.get("/helpdesk/metrics", domain=domain, capability=capability)


@registry.tool("helpdesk_policies", "Políticas de exposição do help desk por perfil/escopo.",
               group="helpdesk")
def helpdesk_policies(client: BspClient) -> Any:
    return client.get("/helpdesk/policies")


@registry.tool(
    "helpdesk_create_policy",
    "Cria uma política de exposição do help desk (quais status/confiança podem ser "
    "entregues a cada perfil, se inclui excerpt/localização). Só administrador.",
    group="helpdesk", mutating=True,
)
def helpdesk_create_policy(
    client: BspClient,
    name: str,
    consumer_profile: ConsumerProfile,
    allowed_statuses: Annotated[list[Status], desc("status entregáveis")],
    scope_type: HelpdeskScope = "global",
    selector: str | None = None,
    minimum_confidence: Annotated[dict | None, desc("por risco, ex.: {\"HIGH\": 0.8}")] = None,
    allow_stale: bool = False,
    allow_conflicted: bool = False,
    critical_requires_escalation: bool = True,
    include_evidence_excerpt: bool = False,
    include_internal_location: bool = False,
    max_context_tokens: int = 8000,
) -> Any:
    return client.post(
        "/helpdesk/policies",
        {
            "name": name, "consumer_profile": consumer_profile, "scope_type": scope_type,
            "selector": selector, "allowed_statuses": allowed_statuses,
            "minimum_confidence": minimum_confidence or {}, "allow_stale": allow_stale,
            "allow_conflicted": allow_conflicted,
            "critical_requires_escalation": critical_requires_escalation,
            "include_evidence_excerpt": include_evidence_excerpt,
            "include_internal_location": include_internal_location,
            "max_context_tokens": max_context_tokens,
        },
    )


@registry.tool("helpdesk_update_policy", "Altera campos de uma política do help desk.",
               group="helpdesk", mutating=True, idempotent=True)
def helpdesk_update_policy(
    client: BspClient,
    policy_id: str,
    changes: Annotated[dict, desc("campos a alterar (mesmos de helpdesk_create_policy)")],
) -> Any:
    return client.patch(f"/helpdesk/policies/{policy_id}", changes)


@registry.tool("helpdesk_clients", "Credenciais de aplicações consumidoras do help desk.",
               group="helpdesk")
def helpdesk_clients(client: BspClient) -> Any:
    return client.get("/helpdesk/clients")


@registry.tool(
    "helpdesk_create_client",
    "Cria uma credencial de máquina (X-BSP-API-Key) ligada a um usuário RBAC. A chave só "
    "aparece nesta resposta. Só administrador.",
    group="helpdesk", mutating=True,
)
def helpdesk_create_client(
    client: BspClient,
    name: str,
    user_id: Annotated[str, desc("UUID do usuário RBAC que dá o escopo")],
    allowed_profiles: list[ConsumerProfile],
    rate_limit_per_minute: int = 60,
    expires_at: Annotated[str | None, desc("ISO 8601")] = None,
) -> Any:
    return client.post(
        "/helpdesk/clients",
        {
            "name": name, "user_id": user_id, "allowed_profiles": allowed_profiles,
            "rate_limit_per_minute": rate_limit_per_minute, "expires_at": expires_at,
        },
    )


@registry.tool("helpdesk_rotate_client", "Rotaciona a chave de uma aplicação (nova chave).",
               group="helpdesk", destructive=True)
def helpdesk_rotate_client(client: BspClient, credential_id: str) -> Any:
    return client.post(f"/helpdesk/clients/{credential_id}/rotate")


@registry.tool("helpdesk_revoke_client", "Revoga a credencial de uma aplicação.",
               group="helpdesk", destructive=True)
def helpdesk_revoke_client(client: BspClient, credential_id: str) -> Any:
    return client.delete(f"/helpdesk/clients/{credential_id}")


@registry.tool(
    "helpdesk_refresh_freshness",
    "Recompara as evidências de uma source com o HEAD do repositório (freshness). Admin.",
    group="helpdesk", mutating=True, idempotent=True,
)
def helpdesk_refresh_freshness(client: BspClient, source_id: str) -> Any:
    return client.post(f"/helpdesk/freshness/sources/{source_id}/refresh")


# =====================================================================
# notifications
# =====================================================================


@registry.tool("notifications", "Notificações in-app do usuário (e quantas não lidas).",
               group="notifications")
def notifications(client: BspClient, unread_only: bool = False) -> Any:
    return client.get("/notifications", unread_only=unread_only)


@registry.tool(
    "mark_notifications_read",
    "Marca uma notificação (id) ou todas como lidas.",
    group="notifications", mutating=True, idempotent=True,
)
def mark_notifications_read(client: BspClient, notification_id: str | None = None) -> Any:
    if notification_id:
        return client.post(f"/notifications/{notification_id}/read")
    return client.post("/notifications/read-all")
