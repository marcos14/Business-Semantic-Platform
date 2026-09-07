"""Rotina envolvente de uma linha citada (o "sítio" da evidência) e mecanismo inferido.

O agente informa `symbol` (nome da procedure/function/handler) e `mechanism`; o kernel
verifica o símbolo contra o fonte — como já faz com o intervalo de linhas — procurando a
declaração mais próxima ACIMA da linha citada. Se o agente não informar, o kernel infere.
Nada aqui usa LLM: são expressões regulares por linguagem, deliberadamente simples.
"""

import re
from pathlib import Path

from app.kernel.ir.envelope import EvidenceMechanism

# Delphi/Pascal: `procedure TForm1.BtnClick(Sender: TObject);`, `function Calc(...): Double;`
_PASCAL = re.compile(
    r"^\s*(?:class\s+)?(?:procedure|function|constructor|destructor)\s+([A-Za-z_][\w.]*)",
    re.I,
)
# Python
_PYTHON = re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)")
# Go: `func (r *Repo) Save(...)` / `func Save(...)`
_GO = re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)")
# Ruby
_RUBY = re.compile(r"^\s*def\s+(?:self\.)?([A-Za-z_]\w*[?!=]?)")
# COBOL: parágrafo/seção na coluna A
_COBOL = re.compile(r"^\s{0,7}([A-Za-z0-9][\w-]*)\s*(?:SECTION)?\s*\.\s*$", re.I)
# Famílias C (Java, C#, C/C++, JS/TS, PHP, Kotlin, Scala, Groovy, Swift, Rust):
# `tipo nome(` no início de linha, sem palavras de controle.
_C_LIKE = re.compile(
    r"^\s*(?!(?:if|for|while|switch|catch|return|else|new|do|try|with|synchronized)\b)"
    r"(?:[A-Za-z_][\w<>\[\],.?:*&\s]*\s+)?(?:\*\s*)?([A-Za-z_]\w*)\s*\([^;{]*\)?\s*"
    r"(?:const\s*)?(?:throws\s+[\w,\s.]+)?(?:->\s*[\w<>\[\]?:]+\s*)?\{?\s*$"
)
_JS_ARROW = re.compile(
    r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$]\w*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>"
)
_JS_FUNC = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$]\w*)")
_RUST = re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+([A-Za-z_]\w*)")
_SQL = re.compile(
    r"^\s*create\s+(?:or\s+replace\s+)?(?:function|procedure|trigger|table|view)\s+"
    r"(?:if\s+not\s+exists\s+)?([\w.\"\[\]]+)",
    re.I,
)
_ADVPL = re.compile(r"^\s*(?:user\s+|static\s+)?function\s+([A-Za-z_]\w*)", re.I)

_BY_EXT: dict[str, tuple[re.Pattern, ...]] = {
    ".pas": (_PASCAL,), ".inc": (_PASCAL,), ".dpr": (_PASCAL,),
    ".py": (_PYTHON,),
    ".go": (_GO,),
    ".rb": (_RUBY,),
    ".cbl": (_COBOL,), ".cob": (_COBOL,),
    ".rs": (_RUST,),
    ".sql": (_SQL,),
    ".prw": (_ADVPL,), ".tlpp": (_ADVPL,),
    ".js": (_JS_FUNC, _JS_ARROW, _C_LIKE), ".mjs": (_JS_FUNC, _JS_ARROW, _C_LIKE),
    ".ts": (_JS_FUNC, _JS_ARROW, _C_LIKE), ".tsx": (_JS_FUNC, _JS_ARROW, _C_LIKE),
}
_C_FAMILY_EXTS = {".java", ".kt", ".cs", ".vb", ".php", ".c", ".cpp", ".h", ".scala",
                  ".groovy", ".swift"}

MAX_LOOKBACK = 400  # linhas: rotinas maiores que isso são raras e o custo é irrelevante


def _patterns_for(path: str) -> tuple[re.Pattern, ...]:
    ext = Path(path).suffix.lower()
    if ext in _BY_EXT:
        return _BY_EXT[ext]
    if ext in _C_FAMILY_EXTS:
        return (_C_LIKE,)
    return (_PASCAL, _PYTHON, _GO, _JS_FUNC, _C_LIKE)


def enclosing_symbol(lines: list[str], line_no: int, path: str) -> str | None:
    """Nome da rotina cuja declaração é a mais próxima ACIMA de `line_no` (1-based)."""
    if not lines or line_no < 1:
        return None
    padroes = _patterns_for(path)
    inicio = min(line_no, len(lines))
    limite = max(1, inicio - MAX_LOOKBACK)
    for i in range(inicio, limite - 1, -1):
        texto = lines[i - 1]
        for pat in padroes:
            m = pat.match(texto)
            if m:
                nome = m.group(1).strip().strip('"[]')
                if nome:
                    return nome
    return None


def verify_symbol(lines: list[str], line_no: int, path: str, claimed: str | None) -> str | None:
    """Símbolo verificado: se o agente informou um nome, ele precisa ser a rotina envolvente
    (comparação sem diferenciar maiúsculas, aceitando `TForm.Metodo` vs `Metodo`); senão,
    devolve o que o kernel inferiu."""
    inferido = enclosing_symbol(lines, line_no, path)
    if not claimed:
        return inferido
    alvo = claimed.strip().lower()
    if inferido is None:
        return None
    inf = inferido.lower()
    if alvo == inf or alvo.endswith("." + inf) or inf.endswith("." + alvo):
        return inferido
    return None


_MECH_RULES: tuple[tuple[EvidenceMechanism, re.Pattern], ...] = (
    (EvidenceMechanism.MESSAGE, re.compile(
        r"raise\s+\w*Exception|ShowMessage|MessageDlg|MsgBox|Application\.MessageBox|"
        r"throw\s+new|alert\(|flash\[|add_error|ValidationError\(", re.I)),
    (EvidenceMechanism.SQL, re.compile(
        r"\b(select|insert|update|delete|create\s+(table|trigger|procedure)|alter\s+table|"
        r"check\s*\(|foreign\s+key|not\s+null)\b", re.I)),
    (EvidenceMechanism.TEST, re.compile(
        r"\b(assert\w*|expect\(|Check(Equals|True|False)|should\b|it\(|test_)", re.I)),
    (EvidenceMechanism.UI_STATE, re.compile(
        r"\.(Enabled|Visible|ReadOnly|Checked)\s*:?=|setEnabled|setVisible|disabled\s*=",
        re.I)),
    (EvidenceMechanism.CONSTANT, re.compile(
        r"^\s*(const\b|final\s+\w+\s+[A-Z_]+\s*=|[A-Z][A-Z0-9_]{3,}\s*(=|:=)\s*[\d'\"])",
        re.I | re.M)),
    (EvidenceMechanism.VALIDATION, re.compile(
        r"\b(if|unless|when|case)\b.*(<|>|<=|>=|=|<>|!=|==).*\b(exit|abort|raise|return|"
        r"throw|error)\b|BeforePost|OnExit|OnValidate|validate", re.I)),
    (EvidenceMechanism.CALCULATION, re.compile(
        r"(:=|=)\s*[^;=\n]*[-+*/]\s*[^;=\n]*(\d|\w)|Round\(|Trunc\(|\bsum\(|percent|"
        r"\*\s*0\.\d", re.I)),
)


def infer_mechanism(excerpt: str | None) -> str | None:
    """Mecanismo inferido do trecho quando o agente não informou (heurística leve)."""
    if not excerpt:
        return None
    for mech, pat in _MECH_RULES:
        if pat.search(excerpt):
            return str(mech)
    return None


def normalize_mechanism(value: str | None, excerpt: str | None = None) -> str | None:
    """Valor do agente validado contra o enum; fora dele, cai na inferência."""
    if value:
        v = str(value).strip().upper()
        if v in EvidenceMechanism.__members__:
            return v
    return infer_mechanism(excerpt)
