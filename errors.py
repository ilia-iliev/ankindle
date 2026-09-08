class KindleNotAttachedError(Exception):
    pass


class KindleNotReadableError(Exception):
    pass


class DictionaryServiceError(Exception):
    pass


class DictionaryUnavailableError(DictionaryServiceError):
    pass


class DefinitionCurationError(Exception):
    pass


class CSVExportError(Exception):
    pass


class AnkiSyncError(Exception):
    pass


class FullSyncRequiredError(AnkiSyncError):
    pass
