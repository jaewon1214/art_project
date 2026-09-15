class PaperGenerationError(Exception):
    """논문 생성 파이프라인에서 발생하는 통합 오류."""

    def __init__(
        self,
        message: str,
        stage: str = "unknown",
    ) -> None:
        self.message = message
        self.stage = stage

        super().__init__(message)