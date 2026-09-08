class KindleNotAttachedError(Exception):
    pass


class KindleNotReadableError(Exception):
    pass


class DefinitionCurationError(Exception):
    pass


class DefinitionsUnavailableError(DefinitionCurationError):
    pass


class CSVExportError(Exception):
    pass


class AnkiSyncError(Exception):
    pass


class FullSyncRequiredError(AnkiSyncError):
    pass
