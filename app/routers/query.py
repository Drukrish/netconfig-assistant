from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.services.generator import answer_question

router = APIRouter()


async def get_session():
    async with AsyncSessionLocal() as session:
        yield session


class QueryRequest(BaseModel):
    question: str


class QueryResponse(BaseModel):
    answer: str | None
    citations: list[str]
    verified: bool
    reason: str


@router.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest, session: AsyncSession = Depends(get_session)) -> QueryResponse:
    result = await answer_question(session, req.question)
    return QueryResponse(
        answer=result.answer,
        citations=result.citations if result.citation_check.passed else [],
        verified=result.citation_check.passed,
        reason=result.citation_check.reason,
    )
