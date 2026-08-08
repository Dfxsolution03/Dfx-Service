from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.models.auth import User
from app.permissions.dependencies import get_current_user
from app.schemas.auth import StandardSuccessResponse
from app.services.wishlist_service import WishlistService

router = APIRouter()


@router.post(
    "/customer/wishlist/{product_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add Product to Wishlist (Customer)",
    description="Adds a product to the authenticated customer's wishlist. 409 if already present.",
)
async def add_to_wishlist(
    product_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    item = await WishlistService.add_to_wishlist(db, current_user, product_id)
    return StandardSuccessResponse(
        success=True,
        message="Product added to wishlist",
        data={"item": item.model_dump(mode="json")},
    )


@router.delete(
    "/customer/wishlist/{product_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Remove Product from Wishlist (Customer)",
    description="Removes a product from the authenticated customer's wishlist.",
)
async def remove_from_wishlist(
    product_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    await WishlistService.remove_from_wishlist(db, current_user, product_id)
    return StandardSuccessResponse(
        success=True,
        message="Product removed from wishlist",
        data={},
    )


@router.get(
    "/customer/wishlist",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="List Wishlist (Customer)",
    description="Returns the authenticated customer's wishlist, with joined product info.",
)
async def list_wishlist(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    items = await WishlistService.get_wishlist(db, current_user)
    return StandardSuccessResponse(
        success=True,
        message="Wishlist retrieved successfully",
        data={"items": [i.model_dump(mode="json") for i in items]},
    )
