"""Servidor MCP e assistente operacional da plataforma.

Tudo aqui é um cliente HTTP da própria API: nenhum acesso direto ao banco. Assim o RBAC,
os gates do kernel, o audit trail e a exportação canônica continuam valendo para qualquer
agente — externo (Claude Code, outro cliente MCP) ou interno (assistente via OpenRouter).

- ``client``   — cliente HTTP autenticado (JWT por login ou token pronto)
- ``registry`` — catálogo de tools (schema derivado da assinatura Python)
- ``tools``    — as tools em si, agrupadas por área da plataforma
- ``server``   — servidor MCP (stdio para Claude Code; streamable HTTP para remoto)
- ``agent``    — assistente com tool calling via OpenRouter (modelo do .env)
"""
