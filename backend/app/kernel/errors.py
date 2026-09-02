class KernelError(Exception):
    """Erro de regra do kernel; traduzido para HTTP no main."""

    status_code = 400


class NotFoundError(KernelError):
    status_code = 404


class DuplicateError(KernelError):
    status_code = 409


class StaleVersionError(KernelError):
    """Optimistic locking (PRD §105): a versão esperada não confere."""

    status_code = 409


class InvalidTransitionError(KernelError):
    """Transição de lifecycle não permitida (PRD §26, §123)."""

    status_code = 409


class EvidenceRequiredError(KernelError):
    """Candidate automático sem evidence (AC-EVI-01)."""

    status_code = 422


class BodyValidationError(KernelError):
    """Body do atom não valida contra o schema do kind (PRD §13-§22)."""

    status_code = 422


class AuthorityError(KernelError):
    """Ação exige autoridade que o ator não possui (PRD §8, §123)."""

    status_code = 403
