"""Catálogo de tools: uma função Python vira uma tool com schema JSON.

O schema de entrada é derivado da assinatura (tipos + ``Annotated[..., Field(description)]``)
via pydantic, então o mesmo catálogo serve ao servidor MCP (``tools/list``) e ao assistente
via OpenRouter (``tools=[{type: function, ...}]``) sem escrever JSON Schema à mão.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError, create_model


class ToolError(Exception):
    """Falha de execução de uma tool, com mensagem já útil para o agente."""


@dataclass
class ToolSpec:
    name: str
    description: str
    group: str
    fn: Callable[..., Any]
    params: type[BaseModel]
    mutating: bool = False  # escreve na plataforma
    destructive: bool = False  # difícil de desfazer (decisão, revogação, exclusão)
    idempotent: bool = False

    def input_schema(self) -> dict:
        return _clean_schema(self.params.model_json_schema())

    def as_openai_tool(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema(),
            },
        }


@dataclass
class ToolRegistry:
    tools: dict[str, ToolSpec] = field(default_factory=dict)

    def tool(
        self,
        name: str,
        description: str,
        *,
        group: str,
        mutating: bool = False,
        destructive: bool = False,
        idempotent: bool = False,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            if name in self.tools:
                raise ValueError(f"Tool duplicada: {name}")
            self.tools[name] = ToolSpec(
                name=name,
                description=inspect.cleandoc(description),
                group=group,
                fn=fn,
                params=_params_model(name, fn),
                mutating=mutating or destructive,
                destructive=destructive,
                idempotent=idempotent,
            )
            return fn

        return deco

    def select(
        self, *, groups: set[str] | None = None, read_only: bool = False
    ) -> list[ToolSpec]:
        out = []
        for spec in self.tools.values():
            if groups and spec.group not in groups:
                continue
            if read_only and spec.mutating:
                continue
            out.append(spec)
        return out

    def groups(self) -> list[str]:
        return sorted({s.group for s in self.tools.values()})

    def call(self, name: str, arguments: dict | None, client: Any) -> Any:
        spec = self.tools.get(name)
        if spec is None:
            raise ToolError(f"Tool desconhecida: {name}")
        try:
            parsed = spec.params.model_validate(arguments or {})
        except ValidationError as e:
            erros = "; ".join(
                f"{'.'.join(str(p) for p in err['loc']) or '-'}: {err['msg']}"
                for err in e.errors()
            )
            raise ToolError(f"Argumentos inválidos para {name}: {erros}") from None
        return spec.fn(client, **parsed.model_dump())


def _params_model(name: str, fn: Callable[..., Any]) -> type[BaseModel]:
    sig = inspect.signature(fn)
    hints = inspect.get_annotations(fn, eval_str=True)
    fields: dict[str, Any] = {}
    for i, (pname, param) in enumerate(sig.parameters.items()):
        if i == 0:  # primeiro parâmetro é sempre o client
            continue
        ann = hints.get(pname, Any)
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[pname] = (ann, default)
    return create_model(f"{name}_params", **fields)


def _clean_schema(schema: dict) -> dict:
    """Remove ``title`` gerado pelo pydantic (ruído para o modelo) e garante ``type: object``."""

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items() if k != "title"}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    out = walk(schema)
    out.setdefault("type", "object")
    out.setdefault("properties", {})
    return out
