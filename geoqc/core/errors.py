"""Errores accionables de la base del proyecto."""


class ConfigError(ValueError):
    """Configuración incoherente, desconocida o incompleta para el modo elegido."""


class EvidenceError(ValueError):
    """Evidencia o manifiesto que no permiten una evaluación íntegra."""
