"""
Claims routes.
GET /claims/{id}/verification — verification status and evidence chain
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from shared.database import get_db
from shared.models import Claim
from shared.schemas import ClaimVerificationResponse
from services.api.auth import verify_api_key

router = APIRouter(prefix="/claims", tags=["claims"])


@router.get("/{claim_id}/verification", response_model=ClaimVerificationResponse)
async def get_claim_verification(
    claim_id: str,
    db: Session = Depends(get_db),
    _key: str = Depends(verify_api_key),
):
    """Get verification status and evidence chain for a specific claim."""
    claim = db.query(Claim).filter(Claim.id == claim_id).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    return ClaimVerificationResponse.model_validate(claim)
