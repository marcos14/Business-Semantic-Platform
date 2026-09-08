"""bsp-agent: executor remoto do harness na máquina de um membro da equipe.

O agente só executa: recebe da API um pacote fechado (prompt, schema, modelo, commit),
garante um clone em cache no commit pedido, roda `claude -p` com a credencial da própria
máquina (ANTHROPIC_API_KEY ou `claude` logado) e devolve o resultado. Nunca toca o banco.
"""

AGENT_VERSION = "0.1.0"
