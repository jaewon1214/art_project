from pydantic import BaseModel


class TransformerDraft(BaseModel):
    title: str
    abstract: str
    introduction: str
    body: str
    conclusion: str